
from __future__ import annotations

import ast
import importlib
from pathlib import Path

from src import models
from tests.helpers.guard_fold import assert_no_offenders

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "models"

MAX_LINES = 1000

MAX_INIT_LINES = 200

PUBLIC_SURFACE = frozenset({
    "AddProviderModelRequest", "AdoptSessionRequest", "AdoptSessionResponse",
    "AgentUpdateInfo", "AttachableListingStatus", "AttachableSession", "CarnivoreLinkInfo", "CheckProjectRootRequest",
    "AuthTokenResponse",
    "BrowseResponse", "CloneProjectRequest", "CommandRequest",
    "ConfigSettingsUpdateRequest", "CreateProjectRequest", "CreateSessionRequest",
    "CreateToastRequest", "DirectoryEntry", "ErrorResponse", "ForkSessionResponse",
    "HealthResponse", "LocalModelsResponse", "LocalServerInfo", "LogEntry",
    "MODEL_ID_PATTERN", "MkdirRequest", "MuteNotificationsRequest",
    "NotificationPolicyResponse", "ProjectResponse",
    "McpDropInfo", "McpHealthInfo", "ProjectMoveRequest", "ProjectMoveResponse",
    "ProviderModelsResponse", "RecentSessionsResponse", "RenameSessionRequest",
    "RespawnSessionRequest", "RespawnSessionResponse",
    "RestartAccountOption", "RestartAccountsResponse",
    "RestartPlanPreview", "RestartPreviewOption", "RestartPreviewResponse",
    "RestartSessionResponse", "ServerPrefsUpdate", "Session",
    "SessionImportStatus", "SessionInfo", "SessionRecord",
    "SessionRenamedMessage", "SessionStats", "SessionStatus", "SetUnreadRequest",
    "SessionBackgroundEntry", "SessionBackgroundsResponse",
    "SuccessResponse",
    "ThemeBackgroundManifest",
    "ThemeManifest", "Toast", "ToastAckMessage", "ToastNewMessage",
    "ToggleFavoriteCommandRequest",
    "UpdatePinnedThemeRequest", "UpdateSessionBackgroundRequest",
    "UpdateProjectRequest", "UpdateThemeRequest", "UploadImageResponse",
    "VerifyTOTPRequest", "WSCommandMessage", "WSErrorMessage",
    "WSLocalServerDetectedMessage", "WSLocalServerLostMessage", "WSLogMessage",
    "WSMessageType", "WSPTYDataMessage", "WSPTYInputMessage", "WSPTYResizeMessage",
    "WSTerminalReadyMessage",
    "WSSessionStatusMessage", "WorkspaceUpdate", "WrapperExamplesResponse",
    "WrapperListResponse", "describe_model_id_rejection", "is_valid_model_id",
    "CatalogItem", "IndexDocument", "ItemCard", "ItemFrontMatter", "ItemVersion",
    "PUBLISHER_RE", "PublisherEntry", "PublisherKey", "RESERVED_SKILL_NAMES",
    "RESERVED_THEME_NAMES",
    "BUNDLED_THEME_NAMES", "FIRST_PARTY_THEME_NAMES", "FIRST_PARTY_THEME_PUBLISHER",
    "RETIRED_THEME_NAMES",
    "ReviewBlock", "ReviewWarning", "Revocations", "RevokedKey", "RevokedVersion",
    "SKILL_NAME_RE", "SignatureBlock", "SourceRef", "is_reserved_name",
    "release_statement",
    "CompanionShell",
})

WRAPPER_ONLY = frozenset({
    "session", "recent_logs", "local_servers", "stats", "session_backend",
    "session_row_id", "parent_session_id", "label", "agent_family",
    "agent_family_source", "agent_wrapper_label", "agent_wrapper_icon", "initial_scrollback_b64",
    "activity_status", "unread", "created_by_cloude", "startup_gate",
    "notifications_muted", "status_source",
})

SESSION_ONLY = frozenset({
    "id", "pty_pid", "working_dir", "status", "created_at", "last_activity",
    "agent_type_via_fingerprint", "model",
})

BOTH_LEVELS = frozenset({"agent_type", "pinned_theme", "tmux_session"})


def _package_modules() -> list[Path]:
    return sorted(PACKAGE.glob("*.py"))


def _defined_names(module: Path) -> set[str]:
    tree = ast.parse(module.read_text())
    out: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
    return out


def test_the_package_exists_and_holds_modules():
    modules = _package_modules()
    assert len(modules) > 2, f"expected a package, found {modules}"
    assert (PACKAGE / "__init__.py").exists()
    assert not (ROOT / "src" / "models.py").exists(), (
        "src/models.py still exists beside src/models/. A module and a "
        "package of one name is a dual path, and which one wins depends "
        "on the finder rather than on anything a reader can see."
    )


def test_every_public_name_the_flat_module_exported_still_resolves():
    missing = sorted(n for n in PUBLIC_SURFACE if not hasattr(models, n))
    assert not missing, f"names lost in the split: {missing}"


def test_the_declared_all_is_exactly_the_frozen_surface():
    assert set(models.__all__) == PUBLIC_SURFACE
    assert len(models.__all__) == len(PUBLIC_SURFACE), "duplicate in __all__"


def _owners() -> dict[str, list[Path]]:
    defined = {m: _defined_names(m) for m in _package_modules()
               if m.name != "__init__.py"}
    return {name: [m for m, names in defined.items() if name in names]
            for name in sorted(PUBLIC_SURFACE)}


def test_each_public_name_is_defined_in_exactly_one_module():
    owners = _owners()

    def check(name: str) -> None:
        found = [m.name for m in owners[name]]
        assert len(found) == 1, f"defined in {found or 'no module'}"

    assert_no_offenders("one definition per public name", owners, check)


def test_the_re_export_is_the_same_object_the_module_defines():
    owners = _owners()

    def check(name: str) -> None:
        submodule = importlib.import_module(f"src.models.{owners[name][0].stem}")
        assert getattr(models, name) is getattr(submodule, name)

    assert_no_offenders("re-export is the defining object", owners, check)


def test_a_session_built_through_the_module_is_the_root_class():
    from src.models import sessions as sessions_module

    built = sessions_module.Session(id="ses_1", working_dir="/tmp/x")
    assert isinstance(built, models.Session)
    assert type(built) is models.Session


def test_a_session_built_through_the_root_is_the_module_class():
    from src.models import sessions as sessions_module

    built = models.Session(id="ses_1", working_dir="/tmp/x")
    assert isinstance(built, sessions_module.Session)
    assert type(built) is sessions_module.Session


def test_the_nested_session_survives_validation_as_the_same_class():
    from src.models import sessions as sessions_module

    info = models.SessionInfo(
        session=sessions_module.Session(id="ses_1", working_dir="/tmp/x")
    )
    assert type(info.session) is models.Session
    assert models.SessionInfo.model_fields["session"].annotation is models.Session


def test_session_info_still_puts_its_fields_on_two_levels():
    wrapper = set(models.SessionInfo.model_fields)
    nested = set(models.Session.model_fields)

    assert WRAPPER_ONLY <= wrapper, f"left the wrapper: {sorted(WRAPPER_ONLY - wrapper)}"
    assert not (WRAPPER_ONLY & nested), (
        f"flattened DOWN onto Session: {sorted(WRAPPER_ONLY & nested)}"
    )
    assert SESSION_ONLY <= nested, f"left Session: {sorted(SESSION_ONLY - nested)}"
    assert not (SESSION_ONLY & wrapper), (
        f"flattened UP onto SessionInfo: {sorted(SESSION_ONLY & wrapper)}"
    )
    assert BOTH_LEVELS <= wrapper and BOTH_LEVELS <= nested, (
        "a field that was on both levels is now on one"
    )


def test_no_module_exceeds_the_line_guideline():
    def check(module: Path) -> None:
        count = len(module.read_text().splitlines())
        assert count <= MAX_LINES, f"{module.name} is {count} lines"

    assert_no_offenders("line guideline", _package_modules(), check,
                        label=lambda p: p.name)


def test_the_re_export_shim_stays_a_shim():
    count = len((PACKAGE / "__init__.py").read_text().splitlines())
    assert count <= MAX_INIT_LINES, f"__init__.py is {count} lines"


def test_no_module_imports_the_package_root():
    def check(module: Path) -> None:
        tree = ast.parse(module.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "src.models", f"{module.name} imports the root"
                assert not (node.level == 1 and node.module is None), (
                    f"{module.name} does a bare relative import of the package"
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "src.models", f"{module.name} imports the root"

    assert_no_offenders(
        "no import of the package root",
        [m for m in _package_modules() if m.name != "__init__.py"],
        check, label=lambda p: p.name,
    )
