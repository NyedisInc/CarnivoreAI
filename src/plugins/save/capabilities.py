
from __future__ import annotations

from typing import Mapping, Tuple

TABLE: Mapping[str, Tuple[str, str]] = {
    "save_import_preview": ("conversations.backups.import.preview",
                            "Preview taking the old archive and recovered files into the backup vault, writing nothing: counts by decision, "
                            "labels, projects, bytes and the fingerprint save_import quotes."),
    "save_import": ("conversations.backups.import.start",
                          "Ask the owner to file the previewed old archive conversations in the backup vault; add only, undoable, never "
                          "touches an old source."),
    "save_import_remove": ("conversations.backups.import.undo",
                         "Ask the owner to take back a finished old archive import: removes exactly the points it filed."),
    "save_import_check": ("conversations.backups.import.verify",
                           "Read an import run's points back from the vault and compare every file to what the run filed; reconcile every copy."),
    "save_imports_list": ("conversations.backups.import.list", "List the receipts of old archive import runs, or read one."),
    "save_import_decide": ("conversations.backups.import.review",
                           "Ask the owner to record the once-over verdict (keep or junk) on imported conversations; keep lets a junk labeled "
                           "import into deep search."),
}
