
from __future__ import annotations

from typing import Mapping, Tuple

TABLE: Mapping[str, Tuple[str, str]] = {
    "widget_lab_drafts_list": ("system.widget_lab.drafts.list", "List widget drafts (folders in the Widget Lab's storage): kind, widget, state, changed files, last build."),
    "widget_lab_draft_get": ("system.widget_lab.draft.get", "One widget draft's record, changed files and last build."),
    "widget_lab_draft_create": ("system.widget_lab.draft.create", "Make a widget draft: a new widget with starter files, or a revision holding only what changes. Lab storage only."),
    "widget_lab_draft_files_list": ("system.widget_lab.draft.files.list", "List every file in a widget draft folder."),
    "widget_lab_draft_file_get": ("system.widget_lab.draft.file.get", "Read one text file of a widget draft folder, confined to the folder."),
    "widget_lab_draft_file_set": ("system.widget_lab.draft.file.set", "Write one text file inside a widget draft folder (component, fixtures, manifest entry, contract), confined to the folder."),
    "widget_lab_draft_file_delete": ("system.widget_lab.draft.file.delete", "Delete one file of a widget draft folder, confined to the folder."),
    "widget_lab_draft_rebuild": ("system.widget_lab.draft.rebuild", "Build a widget draft's live preview for the Widget Lab's compare view. Needs a source checkout (developer mode on)."),
    "widget_lab_draft_spawn": ("system.widget_lab.draft.spawn", "Start a Claude session working in a widget draft folder from its brief. Needs a source checkout (developer mode on)."),
    "widget_lab_draft_delete": ("system.widget_lab.draft.delete", "Discard a widget draft: the folder is set aside inside the Lab's storage."),
}
