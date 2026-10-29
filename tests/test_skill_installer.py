
from __future__ import annotations

import hashlib
import io
import os
import shutil
import sys
import tarfile
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_si_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_si_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.sessions.ports import InstallRoots, Target
from src.core.skills import kinds
from src.core.skills import installer as installer_module
from src.core.skills.digest import digest_directory
from src.core.skills.install_plan import alternative_name, plan_install
from src.core.skills.install_types import (
    ALREADY_INSTALLED,
    CHOICE_INSTALL_AS,
    CHOICE_REPLACE,
    DIGEST_MISMATCH,
    NAME_RESERVED,
    NAME_TAKEN,
    SCOPE_SHADOWED,
    SCRIPTS_NOT_SUPPORTED,
    InstallPlan,
    InstallRefusal,
)
from src.core.skills.installer import (
    STAGING_BUSY,
    StagingBusy,
    apply_install,
    discard_staging,
    staging_root_for,
)
from src.core.skills.ledger import (
    GLOBAL_PROJECT_PATH,
    SCOPE_GLOBAL,
    SCOPE_PROJECT,
    InstalledItem,
    InstallLedger,
)
from src.core.skills.records import SIDECAR_NAME, read_sidecar
from src.core.skills.roots import (
    ROOT_ABSENT,
    ROOT_IS_SYMLINK,
    ROOT_PARENT_IS_SYMLINK,
)
from src.core.skills.stage import stage_archive
from src.core.skills.sweeper import MAX_CONCURRENT_STAGING
from src.models.catalog import CatalogItem, ItemVersion

PREFIX = "repo-abc123/"
PUBLISHER = "pub"
NAME = "review"
COMMIT = "a" * 40
KEY_ID = "5F522AB084F4E697"
INDEX_URL = "https://example.invalid/v1/index.json"




class FixedClock:

    def __init__(self, epoch: float = 1789574400.0) -> None:
        self._epoch = epoch

    def now(self) -> float:
        return self._epoch

    def monotonic(self) -> float:
        return 1000.0


class FakeInstallRoots:

    def __init__(self, base: Path) -> None:
        self.base = base
        self.home = base / "home"
        self.state = base / "state"


    def targets_for(
        self, kind: str, scope: str, project_path: str | None
    ) -> tuple[Target, ...]:
        if not kinds.scope_supported(kind, scope):
            raise ValueError(f"{kind!r} does not install at {scope!r} scope")
        if kind == kinds.KIND_THEME:
            if project_path is not None:
                raise ValueError("a theme installs globally and takes no path")
            return (Target(harness="app", leaf_dir=self.home / "themes"),)
        if kind == kinds.KIND_LOADOUT:
            if project_path is not None:
                raise ValueError("a loadout installs globally and takes no path")
            return (
                Target(harness="catalog", leaf_dir=self.state / "loadouts"),
            )
        if kind == kinds.KIND_PLUGIN:
            if scope == SCOPE_GLOBAL:
                if project_path is not None:
                    raise ValueError("global scope takes no project_path")
                return (
                    Target(
                        harness="claude", leaf_dir=self.home / ".claude" / "skills"
                    ),
                )
            if project_path is None or not project_path.strip():
                raise ValueError("project scope requires a project_path")
            return (
                Target(
                    harness="claude",
                    leaf_dir=Path(os.path.realpath(project_path))
                    / ".claude"
                    / "skills",
                ),
            )
        if scope == SCOPE_GLOBAL:
            if project_path is not None:
                raise ValueError("global scope takes no project_path")
            return (
                Target(harness="claude", leaf_dir=self.home / ".claude" / "skills"),
                Target(harness="codex", leaf_dir=self.home / ".codex" / "skills"),
            )
        if scope == SCOPE_PROJECT:
            if project_path is None or not project_path.strip():
                raise ValueError("project scope requires a project_path")
            real = Path(os.path.realpath(project_path))
            return (
                Target(harness="claude", leaf_dir=real / ".claude" / "skills"),
                Target(harness="codex", leaf_dir=real / ".agents" / "skills"),
            )
        raise ValueError(f"unknown install scope {scope!r}")

    def required_manifest(self, kind: str) -> str:
        return kinds.manifest_name(kind)

    def _targets_at(self, scope: str, project_path: str | None):
        found = []
        for kind in kinds.KINDS:
            if not kinds.scope_supported(kind, scope):
                continue
            found.extend(self.targets_for(kind, scope, project_path))
        return found

    def trash_dir(
        self, harness: str, scope: str, project_path: str | None
    ) -> Path:
        for target in self._targets_at(scope, project_path):
            if target.harness == harness:
                return target.leaf_dir.parent / ".carnivore-trash"
        raise ValueError(f"unknown harness {harness!r}")

    def staging_dir(self) -> Path:
        return self.state / "skills" / ".staging"

    def pending_dir(self) -> Path:
        return self.state / "skills" / ".pending"

    def root_listing(self, harness: str) -> tuple[str, ...]:
        for target in self._targets_at(SCOPE_GLOBAL, None):
            if target.harness == harness:
                try:
                    with os.scandir(target.leaf_dir) as entries:
                        return tuple(sorted(entry.name for entry in entries))
                except OSError:
                    return ()
        raise ValueError(f"unknown harness {harness!r}")

    def read_only_listing(self, harness: str) -> tuple[str, ...]:
        if harness == "claude":
            return ()
        if harness != "codex":
            raise ValueError(f"unknown harness {harness!r}")
        names: set[str] = set()
        for root in (self.agents_skills(), self.codex_system()):
            if not os.path.lexists(root) or os.path.islink(root):
                continue
            try:
                with os.scandir(root) as entries:
                    names.update(entry.name for entry in entries)
            except OSError:
                continue
        return tuple(sorted(names))

    def present_harnesses(self) -> tuple[str, ...]:
        found = []
        if (self.home / ".claude").is_dir():
            found.append("claude")
        if (self.home / ".codex").is_dir() or (self.home / ".agents").is_dir():
            found.append("codex")
        return tuple(found)

    def legacy_targets_for(
        self, kind: str, scope: str, project_path: str | None
    ) -> tuple[Target, ...]:
        return ()


    def make_roots(self) -> None:
        for target in self._targets_at(SCOPE_GLOBAL, None):
            target.leaf_dir.mkdir(parents=True, exist_ok=True)

    def themes_dir(self) -> Path:
        return self.home / "themes"

    def claude_skills(self) -> Path:
        return self.home / ".claude" / "skills"

    def codex_skills(self) -> Path:
        return self.home / ".codex" / "skills"

    def agents_skills(self) -> Path:
        return self.home / ".agents" / "skills"

    def codex_system(self) -> Path:
        return self.codex_skills() / ".system"




def make_tar(members: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, body in members:
            info = tarfile.TarInfo(name)
            info.mode = 0o644
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    return buffer.getvalue()


def stage(tmp_path: Path, body: bytes = b"---\nname: review\n---\n# review\n", **extra):
    skill_root = f"{PREFIX}skills/{PUBLISHER}/{NAME}/"
    members = [(f"{skill_root}SKILL.md", body)]
    members += [
        (f"{skill_root}{name}.md", content) for name, content in extra.items()
    ]
    archive = tmp_path / f"src-{len(list(tmp_path.iterdir()))}.tar.gz"
    archive.write_bytes(make_tar(members))
    dest = tmp_path / "staging" / f"s{len(list(tmp_path.iterdir()))}"
    return stage_archive(archive, dest, publisher=PUBLISHER, name=NAME)


def make_version(digest: str, *, v: str = "1.2.3", scripts: int = 0) -> ItemVersion:
    return ItemVersion(
        v=v,
        src={"repo": "o/r", "path": f"skills/{PUBLISHER}/{NAME}", "commit": COMMIT},
        digest=digest,
        size=64,
        files=1,
        scripts=scripts,
        published_at="2026-09-15T00:00:00Z",
        sig={"key_id": KEY_ID, "sig": "c2ln", "tc": "serial:7", "gsig": "Z3NpZw=="},
    )


def make_item(version: ItemVersion, *, name: str = NAME) -> CatalogItem:
    return CatalogItem(
        id=f"{PUBLISHER}/{name}",
        kind="skill",
        name=name,
        publisher=PUBLISHER,
        latest=version.v,
        card={"title": name, "brief": "a skill"},
        fm={"description": "a skill"},
        versions=[version],
    )


@pytest.fixture
def roots(tmp_path) -> FakeInstallRoots:
    made = FakeInstallRoots(tmp_path / "roots")
    made.make_roots()
    return made


@pytest.fixture
def ledger(tmp_path):
    state = tmp_path / "db"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")
    with closing(connect(db_path_for(state))) as handle:
        yield InstallLedger(handle)


def plan_for(staged, ledger, roots, **overrides):
    version = overrides.pop("version", None) or make_version(staged.digest)
    item = overrides.pop("item", None) or make_item(version)
    arguments = {
        "item": item,
        "version": version,
        "staged": staged,
        "scope": SCOPE_GLOBAL,
        "project_path": None,
        "ledger": ledger,
        "roots": roots,
        "discovery_listing": (),
    }
    arguments.update(overrides)
    return plan_install(**arguments)


def install(plan, ledger, roots, clock=None) -> InstalledItem:
    return apply_install(
        plan,
        ledger=ledger,
        roots=roots,
        clock=clock or FixedClock(),
        source_index_url=INDEX_URL,
        publisher_key_id=KEY_ID,
        consent_via="sheet",
    )




def test_the_fake_roots_satisfy_the_real_port(roots):
    assert isinstance(roots, InstallRoots)




def test_a_global_install_lands_a_real_copy_in_both_roots(tmp_path, roots, ledger):
    staged = stage(tmp_path, reference=b"notes\n")
    plan = plan_for(staged, ledger, roots)
    assert isinstance(plan, InstallPlan), plan

    stored = install(plan, ledger, roots)

    for directory in (roots.claude_skills() / NAME, roots.codex_skills() / NAME):
        assert directory.is_dir()
        assert directory.is_symlink() is False
        assert (directory / "SKILL.md").is_file()
        assert (directory / "SKILL.md").is_symlink() is False
        assert (directory / "reference.md").is_file()
        record = read_sidecar(directory)
        assert record is not None
        assert record.publisher == PUBLISHER
        assert record.name == NAME
        assert record.digest == staged.digest
        assert record.source_index_url == INDEX_URL

    assert stored.scope == SCOPE_GLOBAL
    assert stored.project_path == GLOBAL_PROJECT_PATH
    assert stored.consented_digest == staged.digest
    assert stored.publisher_key_id == KEY_ID
    assert stored.auto_update is False

    targets = ledger.targets(stored.install_id)
    assert sorted(t.harness for t in targets) == ["claude", "codex"]
    assert sorted(t.path for t in targets) == sorted(
        [str(roots.claude_skills() / NAME), str(roots.codex_skills() / NAME)]
    )


def test_the_recorded_body_sha_is_the_manifests_own_sha(tmp_path, roots, ledger):
    body = b"---\nname: review\n---\n# review\n"
    staged = stage(tmp_path, body=body)
    plan = plan_for(staged, ledger, roots)

    stored = install(plan, ledger, roots)

    assert stored.consented_body_sha == hashlib.sha256(body).hexdigest()
    assert stored.consented_body_sha != stored.consented_digest


def test_a_project_install_lands_in_claude_and_agents(tmp_path, roots, ledger):
    project = tmp_path / "proj"
    (project / ".claude" / "skills").mkdir(parents=True)
    (project / ".agents" / "skills").mkdir(parents=True)
    staged = stage(tmp_path)

    plan = plan_for(
        staged,
        ledger,
        roots,
        scope=SCOPE_PROJECT,
        project_path=str(project),
    )
    assert isinstance(plan, InstallPlan), plan
    stored = install(plan, ledger, roots)

    assert (project / ".claude" / "skills" / NAME / "SKILL.md").is_file()
    assert (project / ".agents" / "skills" / NAME / "SKILL.md").is_file()
    assert stored.scope == SCOPE_PROJECT
    assert stored.project_path == os.path.realpath(str(project))


def test_a_project_replace_displaces_into_the_project_trash_not_the_home_one(
    tmp_path, roots, ledger
):
    project = tmp_path / "proj"
    (project / ".claude" / "skills").mkdir(parents=True)
    (project / ".agents" / "skills").mkdir(parents=True)
    _hand_written_skill(project / ".claude" / "skills" / NAME)
    _hand_written_skill(project / ".agents" / "skills" / NAME)
    staged = stage(tmp_path)

    plan = plan_for(
        staged,
        ledger,
        roots,
        scope=SCOPE_PROJECT,
        project_path=str(project),
        choice=CHOICE_REPLACE,
    )
    assert isinstance(plan, InstallPlan), plan
    install(plan, ledger, roots)

    for harness_dir in (".claude", ".agents"):
        trash = project / harness_dir / ".carnivore-trash"
        displaced = [p for p in trash.iterdir() if p.name != ".gitignore"]
        assert len(displaced) == 1, f"{trash} holds {displaced}"
        assert displaced[0].name.startswith(f"{NAME}-")
        assert (displaced[0] / "notes.md").read_text() == "my own notes\n"
        assert (project / harness_dir / "skills" / NAME / SIDECAR_NAME).is_file()

    home_trash = roots.home / ".claude" / ".carnivore-trash"
    assert not home_trash.exists(), (
        "a project replace put the user's folder in the home trash, which "
        "is a different volume and a place they will not look"
    )


def test_a_project_path_is_realpathed_through_a_symlink(tmp_path, roots, ledger):
    real = tmp_path / "real-project"
    (real / ".claude" / "skills").mkdir(parents=True)
    (real / ".agents" / "skills").mkdir(parents=True)
    link = tmp_path / "linked-project"
    link.symlink_to(real, target_is_directory=True)
    staged = stage(tmp_path)

    plan = plan_for(
        staged, ledger, roots, scope=SCOPE_PROJECT, project_path=str(link)
    )
    stored = install(plan, ledger, roots)

    assert stored.project_path == os.path.realpath(str(real))
    assert stored.project_path != str(link)




def test_a_digest_that_does_not_match_the_index_is_refused(tmp_path, roots, ledger):
    staged = stage(tmp_path)

    refusal = plan_for(staged, ledger, roots, version=make_version("b" * 64))

    assert isinstance(refusal, InstallRefusal)
    assert refusal.code == DIGEST_MISMATCH
    assert not (roots.claude_skills() / NAME).exists()


def test_a_version_carrying_scripts_is_refused(tmp_path, roots, ledger):
    staged = stage(tmp_path)

    refusal = plan_for(
        staged, ledger, roots, version=make_version(staged.digest, scripts=2)
    )

    assert isinstance(refusal, InstallRefusal)
    assert refusal.code == SCRIPTS_NOT_SUPPORTED


def test_a_dot_prefixed_name_is_refused_as_reserved(tmp_path, roots, ledger):
    staged = stage(tmp_path)
    version = make_version(staged.digest)
    item = make_item(version)
    hostile = item.model_copy(update={"name": ".system"})

    refusal = plan_for(staged, ledger, roots, item=hostile, version=version)

    assert isinstance(refusal, InstallRefusal)
    assert refusal.code == NAME_RESERVED
    assert ".system" in refusal.detail


def test_a_missing_harness_root_refuses_the_whole_install(tmp_path, ledger):
    roots = FakeInstallRoots(tmp_path / "roots")
    roots.claude_skills().mkdir(parents=True)
    staged = stage(tmp_path)

    refusal = plan_for(staged, ledger, roots)

    assert isinstance(refusal, InstallRefusal)
    assert refusal.code == ROOT_ABSENT
    assert "codex" in refusal.detail
    assert not roots.codex_skills().exists(), "a refusal must not create the root"
    assert not (roots.claude_skills() / NAME).exists()


def test_a_symlinked_harness_root_refuses_the_whole_install(tmp_path, ledger):
    roots = FakeInstallRoots(tmp_path / "roots")
    roots.claude_skills().mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    roots.codex_skills().parent.mkdir(parents=True)
    roots.codex_skills().symlink_to(elsewhere, target_is_directory=True)
    staged = stage(tmp_path)

    refusal = plan_for(staged, ledger, roots)

    assert isinstance(refusal, InstallRefusal)
    assert refusal.code == ROOT_IS_SYMLINK
    assert list(elsewhere.iterdir()) == []


def test_a_symlinked_directory_above_a_harness_root_refuses_the_install(
    tmp_path, ledger
):
    roots = FakeInstallRoots(tmp_path / "roots")
    roots.claude_skills().mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "skills").mkdir(parents=True)
    roots.codex_skills().parent.symlink_to(elsewhere, target_is_directory=True)
    staged = stage(tmp_path)

    refusal = plan_for(staged, ledger, roots)

    assert isinstance(refusal, InstallRefusal)
    assert refusal.code == ROOT_PARENT_IS_SYMLINK
    assert "codex" in refusal.detail
    assert list((elsewhere / "skills").iterdir()) == []
    assert not (roots.claude_skills() / NAME).exists()


def test_a_project_install_of_a_globally_installed_name_is_refused(
    tmp_path, roots, ledger
):
    project = tmp_path / "proj"
    (project / ".claude" / "skills").mkdir(parents=True)
    (project / ".agents" / "skills").mkdir(parents=True)
    staged = stage(tmp_path)
    install(plan_for(staged, ledger, roots), ledger, roots)

    other = make_item(make_version(staged.digest))
    refusal = plan_install(
        item=other.model_copy(update={"id": f"{PUBLISHER}2/{NAME}"}),
        version=make_version(staged.digest),
        staged=staged,
        scope=SCOPE_PROJECT,
        project_path=str(project),
        ledger=ledger,
        roots=roots,
        discovery_listing=(),
    )

    assert isinstance(refusal, InstallRefusal)
    assert refusal.code == SCOPE_SHADOWED
    assert "uninstall the global copy" in refusal.detail


def test_a_global_install_while_a_project_copy_exists_lists_them(
    tmp_path, roots, ledger
):
    project = tmp_path / "proj"
    (project / ".claude" / "skills").mkdir(parents=True)
    (project / ".agents" / "skills").mkdir(parents=True)
    staged = stage(tmp_path)
    install(
        plan_for(
            staged, ledger, roots, scope=SCOPE_PROJECT, project_path=str(project)
        ),
        ledger,
        roots,
    )

    refusal = plan_install(
        item=make_item(make_version(staged.digest)).model_copy(
            update={"id": f"{PUBLISHER}2/{NAME}"}
        ),
        version=make_version(staged.digest),
        staged=staged,
        scope=SCOPE_GLOBAL,
        project_path=None,
        ledger=ledger,
        roots=roots,
        discovery_listing=(),
    )

    assert isinstance(refusal, InstallRefusal)
    assert refusal.code == SCOPE_SHADOWED
    assert os.path.realpath(str(project)) in refusal.detail


def test_re_installing_the_same_item_is_already_installed(tmp_path, roots, ledger):
    staged = stage(tmp_path)
    install(plan_for(staged, ledger, roots), ledger, roots)

    refusal = plan_for(staged, ledger, roots)

    assert isinstance(refusal, InstallRefusal)
    assert refusal.code == ALREADY_INSTALLED
    assert refusal.choices == ()




def _hand_written_skill(directory: Path) -> None:
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text("# mine\n")
    (directory / "notes.md").write_text("my own notes\n")


def test_an_unmanaged_folder_answers_name_taken_with_both_choices(
    tmp_path, roots, ledger
):
    _hand_written_skill(roots.claude_skills() / NAME)
    staged = stage(tmp_path, reference=b"catalog notes\n")

    refusal = plan_for(staged, ledger, roots)

    assert isinstance(refusal, InstallRefusal)
    assert refusal.code == NAME_TAKEN
    actions = [choice.action for choice in refusal.choices]
    assert actions == [CHOICE_INSTALL_AS, CHOICE_REPLACE]

    install_as, replace = refusal.choices
    assert install_as.name == f"{NAME}-carnivore"
    assert install_as.delta is None

    delta = replace.delta
    assert delta is not None
    assert delta.against == str(roots.claude_skills() / NAME)
    assert delta.added == 1, "reference.md is new"
    assert delta.removed == 1, "notes.md goes away"
    assert delta.changed == 1, "SKILL.md differs"
    existing_bytes = sum(
        p.stat().st_size for p in (roots.claude_skills() / NAME).iterdir()
    )
    staged_bytes = sum(p.stat().st_size for p in staged.path.iterdir())
    assert delta.byte_delta == staged_bytes - existing_bytes


def test_install_as_installs_under_the_suffixed_name(tmp_path, roots, ledger):
    _hand_written_skill(roots.claude_skills() / NAME)
    staged = stage(tmp_path)

    plan = plan_for(staged, ledger, roots, choice=CHOICE_INSTALL_AS)
    assert isinstance(plan, InstallPlan), plan
    stored = install(plan, ledger, roots)

    assert stored.name == alternative_name(NAME)
    assert (roots.claude_skills() / f"{NAME}-carnivore" / "SKILL.md").is_file()
    assert (roots.codex_skills() / f"{NAME}-carnivore" / "SKILL.md").is_file()
    assert (roots.claude_skills() / NAME / "notes.md").read_text() == "my own notes\n"
    assert read_sidecar(roots.claude_skills() / NAME) is None


def test_replace_moves_the_old_folder_into_the_trash_beside_skills(
    tmp_path, roots, ledger
):
    _hand_written_skill(roots.claude_skills() / NAME)
    staged = stage(tmp_path)
    clock = FixedClock()

    plan = plan_for(staged, ledger, roots, choice=CHOICE_REPLACE)
    assert isinstance(plan, InstallPlan), plan
    install(plan, ledger, roots, clock=clock)

    trash = roots.trash_dir("claude", "global", None)
    assert trash.parent == roots.claude_skills().parent
    assert trash.name == ".carnivore-trash"
    displaced = [p for p in trash.iterdir() if p.name != ".gitignore"]
    assert len(displaced) == 1
    assert displaced[0].name.startswith(f"{NAME}-")
    assert displaced[0].name != NAME, "the stamp is what keeps two apart"
    assert (displaced[0] / "notes.md").read_text() == "my own notes\n"
    assert (roots.claude_skills() / NAME / SIDECAR_NAME).is_file()


def test_a_name_in_a_read_only_root_never_offers_replace(tmp_path, roots, ledger):
    staged = stage(tmp_path)

    refusal = plan_for(
        staged, ledger, roots, discovery_listing=(".system", NAME, "other")
    )

    assert isinstance(refusal, InstallRefusal)
    assert refusal.code == NAME_TAKEN
    assert [choice.action for choice in refusal.choices] == [CHOICE_INSTALL_AS]


def test_a_dot_directory_in_the_listing_is_skipped_entirely(tmp_path, roots, ledger):
    staged = stage(tmp_path)

    plan = plan_for(
        staged,
        ledger,
        roots,
        discovery_listing=(".system", ".carnivore-trash", ".hidden"),
    )

    assert isinstance(plan, InstallPlan), plan


def test_a_symlinked_target_is_never_offered_for_replacement(
    tmp_path, roots, ledger
):
    elsewhere = tmp_path / "somewhere"
    elsewhere.mkdir()
    (roots.claude_skills() / NAME).symlink_to(elsewhere, target_is_directory=True)
    staged = stage(tmp_path)

    refusal = plan_for(staged, ledger, roots)

    assert isinstance(refusal, InstallRefusal)
    assert refusal.code == NAME_TAKEN
    assert [choice.action for choice in refusal.choices] == [CHOICE_INSTALL_AS]




def test_a_failure_after_the_first_copy_leaves_no_target_behind(
    tmp_path, roots, ledger, monkeypatch
):
    staged = stage(tmp_path)
    plan = plan_for(staged, ledger, roots)
    assert isinstance(plan, InstallPlan), plan

    real_copy = installer_module.copy_tree
    calls: list[Path] = []

    def failing_copy(src: Path, dst: Path, **kwargs) -> None:
        calls.append(dst)
        if len(calls) == 1:
            real_copy(src, dst)
            return
        raise OSError("disk went away")

    monkeypatch.setattr("src.core.skills.installer.copy_tree", failing_copy)

    with pytest.raises(OSError):
        install(plan, ledger, roots)

    assert len(calls) == 2, "the second target must have been attempted"
    assert not (roots.claude_skills() / NAME).exists()
    assert not (roots.codex_skills() / NAME).exists()
    assert ledger.list() == ()


def test_a_ledger_refusal_removes_both_copies(tmp_path, roots, ledger):
    staged = stage(tmp_path)
    plan = plan_for(staged, ledger, roots)
    assert isinstance(plan, InstallPlan), plan
    install(plan, ledger, roots)

    other_version = make_version(staged.digest, v="2.0.0")
    other_item = make_item(other_version).model_copy(
        update={"id": f"{PUBLISHER}2/{NAME}"}
    )
    for directory in (roots.claude_skills() / NAME, roots.codex_skills() / NAME):
        shutil.rmtree(directory)

    second = plan.__class__(
        item_id=other_item.id,
        publisher=other_item.publisher,
        name=NAME,
        version="2.0.0",
        kind="skill",
        digest=staged.digest,
        body_sha=plan.body_sha,
        staged=staged.path,
        scope=SCOPE_GLOBAL,
        project_path=GLOBAL_PROJECT_PATH,
        targets=plan.targets,
        replaces=False,
    )

    with pytest.raises(Exception):
        install(second, ledger, roots)

    assert not (roots.claude_skills() / NAME).exists()
    assert not (roots.codex_skills() / NAME).exists()




def test_staging_hands_out_a_fresh_empty_directory(roots):
    first = staging_root_for(roots)
    second = staging_root_for(roots)

    assert first != second
    assert first.is_dir() and list(first.iterdir()) == []
    assert oct(first.stat().st_mode)[-3:] == "700"
    assert first.parent == roots.staging_dir()

    discard_staging(first)
    assert not first.exists()


def test_the_staging_cap_answers_staging_busy(roots):
    held = [staging_root_for(roots) for _ in range(MAX_CONCURRENT_STAGING)]

    with pytest.raises(StagingBusy) as caught:
        staging_root_for(roots)

    assert caught.value.code == STAGING_BUSY
    assert caught.value.cap == MAX_CONCURRENT_STAGING
    assert caught.value.in_use == MAX_CONCURRENT_STAGING

    discard_staging(held[0])
    freed = staging_root_for(roots)
    assert freed.is_dir(), "freeing one must let the next caller through"


def test_a_folder_with_no_manifest_is_refused_at_apply(tmp_path, roots, ledger):
    staged = stage(tmp_path)
    plan = plan_for(staged, ledger, roots)
    assert isinstance(plan, InstallPlan), plan
    (staged.path / "SKILL.md").unlink()

    with pytest.raises(FileNotFoundError):
        install(plan, ledger, roots)

    assert not (roots.claude_skills() / NAME).exists()


def test_the_installed_digest_is_the_signed_one_not_the_folders(
    tmp_path, roots, ledger
):
    staged = stage(tmp_path)
    plan = plan_for(staged, ledger, roots)
    stored = install(plan, ledger, roots)

    on_disk, _entries = digest_directory(roots.claude_skills() / NAME)
    assert stored.digest == staged.digest
    assert on_disk != staged.digest
