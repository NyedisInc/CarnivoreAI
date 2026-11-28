
from __future__ import annotations

from typing import Tuple

HEALTH_AUTOMATION_NAME: str = "backup health check"
HEALTH_SEED_KEY: str = "backup_health_check"
HEALTH_CRON: str = "*/15 * * * *"

BACKUP_MAX_AGE_DAYS: float = 14.0
BACKUP_VOLUME_ENV: str = "BACKUP_VOLUME"
BACKUP_VOLUME_OFF: str = "off"
BACKUP_DIR_GLOB: str = "state-backup-pre-*"

ALERT_SOURCE: str = "backup_health"
KEY_USB: str = "backup_health.usb_backup"
KEY_TIME_MACHINE: str = "backup_health.time_machine"
TITLE_USB_STALE: str = "app_alert.backup_health.usb_stale.title"
DETAIL_USB_STALE: str = "app_alert.backup_health.usb_stale.detail"
TITLE_USB_MISSING: str = "app_alert.backup_health.usb_missing.title"
DETAIL_USB_MISSING: str = "app_alert.backup_health.usb_missing.detail"

KEY_VAULT_UNAVAILABLE: str = "backup_health.vault_unavailable"
KEY_VAULT_STALE: str = "backup_health.vault_stale"
KEY_VAULT_UNCOVERED: str = "backup_health.vault_uncovered"
KEY_VAULT_OVER_CAP: str = "backup_health.vault_over_cap"
KEY_VAULT_DAMAGED: str = "backup_health.vault_damaged"
KEY_VAULT_MASS_GONE: str = "backup_health.vault_mass_gone"
KEY_VAULT_PURGE_UNVERIFIED: str = "backup_health.vault_purge_unverified"
KEY_VAULT_SCRUB_DAMAGED: str = "backup_health.vault_scrub_damaged"
KEY_VAULT_RESTORE_FAILED: str = "backup_health.vault_restore_failed"
KEY_VAULT_LEDGER_UNREADABLE: str = "backup_health.vault_ledger_unreadable"
VAULT_REPAIR_SCRIPT: str = "scripts/vault/repair-chunks-from-restic.sh"
TITLE_VAULT_PURGE_UNVERIFIED: str = "app_alert.backup_health.vault_purge_unverified.title"
DETAIL_VAULT_PURGE_UNVERIFIED: str = "app_alert.backup_health.vault_purge_unverified.detail"
TITLE_VAULT_SCRUB_DAMAGED: str = "app_alert.backup_health.vault_scrub_damaged.title"
DETAIL_VAULT_SCRUB_DAMAGED: str = "app_alert.backup_health.vault_scrub_damaged.detail"
TITLE_VAULT_RESTORE_FAILED: str = "app_alert.backup_health.vault_restore_failed.title"
DETAIL_VAULT_RESTORE_FAILED: str = "app_alert.backup_health.vault_restore_failed.detail"
TITLE_VAULT_LEDGER_UNREADABLE: str = "app_alert.backup_health.vault_ledger_unreadable.title"
DETAIL_VAULT_LEDGER_UNREADABLE: str = "app_alert.backup_health.vault_ledger_unreadable.detail"
TITLE_VAULT_UNAVAILABLE: str = "app_alert.backup_health.vault_unavailable.title"
DETAIL_VAULT_UNAVAILABLE: str = "app_alert.backup_health.vault_unavailable.detail"
TITLE_VAULT_STALE: str = "app_alert.backup_health.vault_stale.title"
DETAIL_VAULT_STALE: str = "app_alert.backup_health.vault_stale.detail"
TITLE_VAULT_UNCOVERED: str = "app_alert.backup_health.vault_uncovered.title"
DETAIL_VAULT_UNCOVERED: str = "app_alert.backup_health.vault_uncovered.detail"
TITLE_VAULT_OVER_CAP: str = "app_alert.backup_health.vault_over_cap.title"
DETAIL_VAULT_OVER_CAP: str = "app_alert.backup_health.vault_over_cap.detail"
TITLE_VAULT_DAMAGED: str = "app_alert.backup_health.vault_damaged.title"
DETAIL_VAULT_DAMAGED: str = "app_alert.backup_health.vault_damaged.detail"
TITLE_VAULT_MASS_GONE: str = "app_alert.backup_health.vault_mass_gone.title"
DETAIL_VAULT_MASS_GONE: str = "app_alert.backup_health.vault_mass_gone.detail"
KEY_VAULT_FROZEN: str = "backup_health.vault_frozen"
TITLE_VAULT_FROZEN: str = "app_alert.backup_health.vault_frozen.title"
DETAIL_VAULT_FROZEN: str = "app_alert.backup_health.vault_frozen.detail"
DETAIL_VAULT_FROZEN_OVER_CAP: str = "app_alert.backup_health.vault_frozen.detail_over_cap"

KEY_TRANSCRIPTS_GONE_UNPROTECTED: str = "backup_health.transcripts_gone_unprotected"
TITLE_TRANSCRIPTS_GONE_UNPROTECTED: str = "app_alert.backup_health.transcripts_gone_unprotected.title"
DETAIL_TRANSCRIPTS_GONE_UNPROTECTED: str = "app_alert.backup_health.transcripts_gone_unprotected.detail"
DETAIL_TRANSCRIPTS_GONE_UNPROTECTED_MORE: str = "app_alert.backup_health.transcripts_gone_unprotected.detail_more"

RETIRED_CATCHUP_SEED_KEY: str = "save_catchup_hourly"
RETIRED_CATCHUP_RECIPE: str = "save_catchup"
RETIRED_ALERT_KEYS: Tuple[str, ...] = ("backup_health.no_restore_points", "backup_health.summaries_failed", KEY_TIME_MACHINE)

ALERT_PREFIXES: Tuple[str, ...] = ("backup_health.",)
