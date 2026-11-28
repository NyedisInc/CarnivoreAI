
from pydantic import BaseModel, Field

from src.core.retention import constants as K


class RetentionConfig(BaseModel):
    """Housekeeping that moves old copies to the backup drive.

    - ``enabled``: master switch; on by default. Off, the schedule idles and the run-now route still answers a dry run.
    - ``keep_db_backups``: pre-upgrade database backups kept in the state dir (newest first).
    - ``keep_rollback_bundles``: rollback app bundles kept (rollback dir plus its packed/ folder).
    - ``menubar_log_cap_mb``: total size the desktop app's log folder may reach before the oldest rotated logs roll away.
    - ``scratch_idle_hours``: a finished session's scratchpad is cleared only after nothing in its folder changed for this long.
    - ``interval_seconds``: time between runs; one also runs shortly after boot.
    """

    enabled: bool = True
    keep_db_backups: int = Field(default=K.DEFAULT_KEEP_DB_BACKUPS, ge=0)
    keep_rollback_bundles: int = Field(default=K.DEFAULT_KEEP_ROLLBACK_BUNDLES, ge=0)
    menubar_log_cap_mb: int = Field(default=K.DEFAULT_LOG_CAP_MB, ge=1)
    scratch_idle_hours: int = Field(default=K.DEFAULT_SCRATCH_IDLE_HOURS, ge=1)
    interval_seconds: int = Field(default=K.DEFAULT_INTERVAL_SECONDS, ge=3600)
