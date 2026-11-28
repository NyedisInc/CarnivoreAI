from __future__ import annotations

HARNESS_DIRS: tuple[str, ...] = (
    "web/src/browse/fixtures/",
    "web/src/plugins/crate/style-guide/",
    "web/src/plugins/devwidgetlab/style-guide/",
    "web/src/plugins/flow/style-guide/",
    "web/src/plugins/taskmanager/style-guide/",
    "web/src/plugins/reviewboard/style-guide/",
    "web/src/plugins/save/style-guide/",
    "web/src/plugins/share/style-guide/",
    "web/src/lib/dialog-frame/fixtures/",
    "web/src/lib/right-drawer/fixtures/",
    "web/src/lib/sidebar-widgets/fixtures/",
    "web/src/lib/zone-shell/fixtures/",
    "web/src/opscenter/cells/files/fixtures/",
    "web/src/plugins/taskmanager/mk2/fixtures/",
    "web/src/opscenter/cells/terminal-group/fixtures/",
    "web/src/opscenter/engine/v7/fixtures/",
    "web/src/opscenter/shell/fixtures/",
    "web/src/opscenter/ui/fixtures/",
    "web/src/opscenter/widgets/fixtures/",
    "web/src/opscenter/widgets/shell/fixtures/",
    "web/src/style-guide/",
)
HARNESS_FILES: frozenset[str] = frozenset(
    {
        "web/src/opscenter/ui/InsetHostFixture.svelte",
        "web/src/widget-harness/DefectProbe.svelte",
        "web/src/widget-harness/FitProbe.svelte",
    }
)


def is_harness(rel: str) -> bool:
    return rel in HARNESS_FILES or rel.startswith(HARNESS_DIRS)
