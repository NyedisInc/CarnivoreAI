
import asyncio
import json
import sqlite3
import structlog

from src.core.catalog import first_party_listing
from src.core.design_base import theme_contract
from src.core import theme_feedback_ids, theme_paths, theme_script_digest
from src.core.skills.ledger_types import SCOPE_GLOBAL, InstalledItem
from fastapi import APIRouter, Depends, Request
from pathlib import Path
from src.api.auth import require_auth
from src.models import ThemeManifest
from typing import Callable, List, Optional, Tuple

logger = structlog.get_logger()
router = APIRouter()


def _bundled_themes_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "client" / "css" / "themes"


def _user_themes_root() -> Optional[Path]:
    return theme_paths.existing_user_themes_dir()


def _load_manifest(theme_dir: Path, source: str) -> Optional[ThemeManifest]:
    manifest_path = theme_dir / "theme.json"
    if not manifest_path.is_file():
        return None
    try:
        with manifest_path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning(
            "theme_manifest_parse_failed",
            path=str(manifest_path),
            error=str(e),
        )
        return None

    raw["source"] = source

    raw["effectsDigest"] = theme_script_digest.digest_effects(
        theme_dir, raw.get("effects")
    )

    raw["feedbackItemId"] = None
    raw["publisher"] = None
    raw["scriptTrust"] = None

    try:
        manifest = ThemeManifest(**raw)
    except Exception as e:
        logger.warning(
            "theme_manifest_validation_failed",
            path=str(manifest_path),
            error=str(e),
        )
        return None

    if manifest.id != theme_dir.name:
        logger.warning(
            "theme_manifest_id_dir_mismatch",
            manifest_id=manifest.id,
            dir_name=theme_dir.name,
            path=str(manifest_path),
        )
        return None

    theme_contract.report_manifest(manifest.id, source, manifest.cssVars)

    if manifest.themeCss:
        theme_css_path = theme_dir / manifest.themeCss
        if not theme_css_path.is_file():
            logger.warning(
                "theme_manifest_themecss_missing",
                theme_id=manifest.id,
                theme_css=manifest.themeCss,
                path=str(theme_css_path),
            )
            return None

    if manifest.background:
        image_path = theme_dir / manifest.background.image
        if not image_path.is_file():
            logger.warning(
                "theme_manifest_background_missing",
                theme_id=manifest.id,
                image=manifest.background.image,
                path=str(image_path),
                reason=(
                    "theme declares a background image its package does "
                    "not ship; the theme keeps its colours and paints no "
                    "image"
                ),
            )
            manifest = manifest.model_copy(update={"background": None})

    if manifest.mascot and not (theme_dir / manifest.mascot).is_file():
        logger.warning(
            "theme_manifest_mascot_missing",
            theme_id=manifest.id,
            mascot=manifest.mascot,
            reason="theme declares a mascot sprite its package does not ship",
        )
        manifest = manifest.model_copy(update={"mascot": None})

    return manifest


def _scan_themes_root(root: Optional[Path], source: str) -> List[ThemeManifest]:
    if root is None or not root.is_dir():
        return []
    out: List[ThemeManifest] = []
    seen_ids = set()
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError as e:
        logger.warning("themes_root_scan_failed", root=str(root), error=str(e))
        return []
    for child in entries:
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        m = _load_manifest(child, source)
        if m is None:
            continue
        if m.id in seen_ids:
            logger.warning(
                "theme_duplicate_id_skipped",
                id=m.id,
                root=str(root),
            )
            continue
        seen_ids.add(m.id)
        out.append(m)
    return out


def _theme_installs_reader(request: Request) -> Callable[[], Tuple[InstalledItem, ...]]:
    try:
        services = request.app.state.services
    except AttributeError:
        services = None

    def read() -> Tuple[InstalledItem, ...]:
        if services is None:
            logger.warning(
                "theme_feedback_ids_unavailable", reason="no_catalog_services"
            )
            return ()
        try:
            with services.catalog.ledger() as ledger:
                return ledger.list(scope=SCOPE_GLOBAL)
        except (AttributeError, sqlite3.Error) as e:
            logger.warning("theme_feedback_ids_unavailable", error=str(e))
            return ()

    return read


def _scan_both_roots(
    bundled_root: Path,
    user_root: Optional[Path],
    read_installs: Callable[[], Tuple[InstalledItem, ...]],
) -> Tuple[List[ThemeManifest], List[ThemeManifest], Tuple[InstalledItem, ...]]:
    return (
        _scan_themes_root(bundled_root, "builtin"),
        _scan_themes_root(user_root, "user"),
        read_installs(),
    )


@router.get(
    "/themes",
    response_model=List[ThemeManifest],
    dependencies=[Depends(require_auth)],
)
async def list_themes(request: Request) -> List[ThemeManifest]:
    """List discovered theme manifests (bundled + user).

    Bundled themes are sorted first (alphabetical by name within each group).
    Malformed manifests are skipped with a warning log - never 500.
    The client has its own Claude fallback, so an empty list is acceptable
    in degraded states.

    EVERY MANIFEST IS STAMPED WITH THE CATALOG ITEM IT CAN BE RATED AND
    SENT A NOTE ABOUT (``feedbackItemId``, ``publisher``), through
    :func:`src.core.theme_feedback_ids.stamp`. A bundled theme always gets
    the reserved ``bundled/<id>`` allowlist entry; a user theme gets its
    ledger row's item id and publisher when its folder still matches one;
    a hand-made theme gets neither. A catalog outage or a missing
    services container degrades this to bundled ids only rather than
    failing the route - see :func:`_theme_installs_reader`.

    THE SCAN RUNS IN A THREAD AND THE RESPONSE IS UNCHANGED BYTE FOR BYTE
    OTHERWISE. Three stages, in the order ``GET /config-files/tree`` and
    the listing pass both use: SNAPSHOT the two roots and the ledger
    reader here on the loop, where the environment override, the
    monkeypatchable module names and ``request.app.state`` live; GATHER
    the manifests, their script digests and the ledger rows in
    ``asyncio.to_thread``; APPLY the sort, the cross-root dedup, the
    shadowing warning and the feedback-id stamp back on the loop. Nothing
    about which themes are returned, or in what order, depends on where
    the work happened.
    """
    bundled_root = _bundled_themes_root()
    user_root = _user_themes_root()
    read_installs = _theme_installs_reader(request)
    bundled, user, installs = await asyncio.to_thread(
        _scan_both_roots, bundled_root, user_root, read_installs
    )
    first_party = await asyncio.to_thread(
        first_party_listing.trusted_ids, user_root, user, installs,
        first_party_listing.pinned_key_id(),
    )
    bundled.sort(key=lambda m: m.name.lower())
    user.sort(key=lambda m: m.id.lower())

    bundled_ids = {m.id for m in bundled}
    deduped_user: List[ThemeManifest] = []
    for m in user:
        if m.id in bundled_ids:
            logger.warning(
                "theme_user_shadowed_by_builtin",
                id=m.id,
                reason="user theme id collides with a bundled theme; bundled wins",
            )
            continue
        deduped_user.append(
            m.model_copy(update={"scriptTrust": "first_party"}) if m.id in first_party else m
        )

    return theme_feedback_ids.stamp(bundled + deduped_user, installs)
