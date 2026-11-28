
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
    "save_offload_list": ("conversations.backups.offload.list",
                          "List the sessions offloaded to the backup vault, newest first: size, date, state and the reason a row is stuck; also whether the offload is on."),
    "save_offload_restore": ("conversations.backups.offload.restore",
                             "Ask the owner to put an offloaded session's conversations back from the backup vault; starts no session, overwrites nothing."),
    "save_offload_batch_start": ("conversations.backups.offload.batch_start",
                                 "Ask the owner to start a staged bulk offload of the oldest idle closed sessions; verified, held 7 days, restorable; refused while the offload setting is off."),
    "save_offload_batch_status": ("conversations.backups.offload.batch_status",
                                  "How far a staged bulk offload is, with each session's outcome."),
    "save_offload_restore_batch_start": ("conversations.backups.offload.restore_batch_start",
                                         "Ask the owner, once, to put many offloaded sessions and conversations back from the backup vault; starts no session, overwrites nothing."),
    "save_offload_restore_batch_status": ("conversations.backups.offload.restore_batch_status",
                                          "How far a bulk restore is, with each target's outcome."),
}
