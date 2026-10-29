
from __future__ import annotations

from typing import Mapping, Tuple

TABLE: Mapping[str, Tuple[str, str]] = {
    "task_manager_dev_fold_set": ("task_manager.dev.fold.set",
                                  "Fold or unfold groups, projects or task cards in the owner's Task Manager, or close the open "
                                  "card. Screen only; no task changes."),
    "task_manager_dev_scroll_set": ("task_manager.dev.scroll.set",
                                    "Scroll the owner's Task Manager tab to the top in every browser, optionally switching to one "
                                    "project's list first. Screen only."),
    "task_manager_dev_tasks_list": ("task_manager.dev.tasks.list",
                                    "List tasks compactly (id, title, status, project, group, tag) filtered by status or project, "
                                    "or projects with task counts (view projects)."),
}
