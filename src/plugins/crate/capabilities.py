
from __future__ import annotations

from typing import Mapping, Tuple

TABLE: Mapping[str, Tuple[str, str]] = {
    "crate_status": ("conversations.crates.status",
                     "Crate export status: the crate folders and their free space, the encryption defaults, the running "
                     "job and how many crates are recorded."),
    "crate_export_preview": ("conversations.crates.preview",
                             "Preview a crate export of a session or project: what it carries, leaves out and refuses, "
                             "with the fingerprint crate_export quotes."),
    "crate_backup_families": ("conversations.crates.backup_families",
                              "List the backup ticks an export of a session or project offers: conversations, and each plugin folder "
                              "(review boards) the project owns a part of, with whether each is on."),
    "crate_export": ("conversations.crates.export",
                     "Ask the owner to export a session or project to one verifiable crate file, byte exact or a "
                     "redacted share, optionally encrypted with age."),
    "crate_jobs_list": ("conversations.crates.jobs.list",
                        "List crate export, verify and copy jobs with their phase and progress, or read one job."),
    "crate_job_cancel": ("conversations.crates.jobs.cancel",
                         "Cancel the running crate job; whatever it wrote is removed."),
    "crate_bundles_list": ("conversations.crates.bundles.list",
                           "List recorded crate bundles and where each copy lives, or read one bundle and a plain "
                           "crate's contents."),
    "crate_check": ("conversations.crates.check",
                    "Verify a crate (quick, full or drill) as a job; a pass records when it was last verified."),
    "crate_unpack": ("conversations.crates.unpack",
                     "Write one conversation of a plain crate into a scratch folder laid out for a test resume."),
    "crate_copy": ("conversations.crates.copy",
                   "Copy a recorded crate to the second crate folder, verify it there and record the location."),
    "crate_remove": ("conversations.crates.remove",
                     "Ask the owner to move a crate file to the Trash; a recorded crate keeps its record and shows as removed."),
    "crate_folder_crates_list": ("conversations.crates.folders.list",
                                 "List the crate files in a crate folder, or read one plain folder crate's contents."),
    "crate_import_preview": ("conversations.crates.import.preview",
                             "Preview restoring a plain crate here, writing nothing: provenance, target folder, files, rows, "
                             "blockers and warnings."),
    "crate_import": ("conversations.crates.import.start",
                     "Ask the owner to restore a plain crate into this install, after previewing it; every restored session "
                     "comes back asleep."),
    "crate_import_undo": ("conversations.crates.import.undo",
                          "Ask the owner to undo a finished crate restore: it removes exactly what that import wrote and puts back what "
                          "it changed; anything already here or changed since stays."),
    "crate_imports_list": ("conversations.crates.import.list",
                           "List the receipts of finished crate imports, or read one."),
}
