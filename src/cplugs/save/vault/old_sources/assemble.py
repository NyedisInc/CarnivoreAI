
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple

import structlog

from src.cplugs.save.vault.identity import ProjectIndex
from src.cplugs.save.vault.old_sources import allowlist, archive_db, attribution, extras, folder_tree, held, labels, model, old_store, plan, tar_files
from src.cplugs.save.vault.store import Vault
from src.cplugs.save.vault.units import Sources

logger = structlog.get_logger()


@dataclass
class SourceConfig:

    archives: List[Path] = field(default_factory=list)
    folders: List[Tuple[str, Path]] = field(default_factory=list)
    old_stores: List[Path] = field(default_factory=list)
    tar_roots: List[Path] = field(default_factory=list)
    recovered_root: Optional[Path] = None
    plan_applied: Optional[Path] = None
    trash_manifests: List[Path] = field(default_factory=list)
    rows_file: Optional[Path] = None
    secret_rows: List[str] = field(default_factory=list)
    reorg_rules: List[Path] = field(default_factory=list)
    newest_only: bool = True
    quick: bool = False
    only_points: Optional[List[allowlist.PointKey]] = None


@dataclass
class Built:

    plan: plan.Plan
    extra_files: List[extras.ExtraFile]
    intake: model.Intake


def old_copies(config: SourceConfig, intake: model.Intake) -> Iterator[model.Copy]:
    for db in config.archives:
        yield from archive_db.iter_copies(Path(db), intake, newest_only=config.newest_only, trust=config.quick)
    for name, folder in config.folders:
        yield from folder_tree.iter_copies(Path(folder), intake, name)
    if config.recovered_root is not None:
        yield from folder_tree.iter_copies(Path(config.recovered_root), intake, "recovered")
    for root in config.old_stores:
        yield from old_store.iter_copies(Path(root), intake, trust=config.quick)
    for root in config.tar_roots:
        yield from tar_files.iter_copies(Path(root), intake)
        yield from folder_tree.iter_copies(Path(root), intake, "swarm-files")


def _development_roots() -> Tuple[Tuple[str, ...], str]:
    alias = Path.home() / "Development"
    real = os.path.realpath(alias)
    return (str(alias) + "/", real + "/"), real + "/"


def build(config: SourceConfig, vault: Vault, sources: Sources, projects: Sequence[dict]) -> Built:
    intake = model.Intake()
    old = list(old_copies(config, intake))
    keys = {c.key for c in old}
    held_copies = list(held.vault_copies(vault, keys, intake)) + list(held.disk_copies(sources, keys, intake))
    book = labels.LabelBook.load(config.plan_applied, config.trash_manifests, config.rows_file, config.secret_rows)
    roots, target = _development_roots()
    rules = attribution.load_rules(config.reorg_rules)
    attributor = attribution.Attributor(ProjectIndex(projects), rules, roots, target)
    planned = plan.plan_sources(old, held_copies, book, attributor, intake)
    extra_files = extras.find(Path(config.recovered_root), intake) if config.recovered_root is not None else []
    planned.refused = list(intake.refused)
    if config.only_points is not None:
        allowlist.restrict(planned, config.only_points)
    logger.info("save_import_planned", points=len(planned.points), copies=len(planned.decisions), refused=len(planned.refused))
    return Built(planned, extra_files, intake)
