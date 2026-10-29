
from pydantic import BaseModel, Field


class UploadsConfig(BaseModel):
    """Browser-paste image upload configuration.
    """
    enabled: bool = True
    ttl_seconds: int = Field(default=86400, ge=1)
    sweep_interval_seconds: int = Field(default=3600, ge=1)
    max_size_mb: int = Field(default=10, ge=1)
    max_file_size_mb: int = Field(default=50, ge=1)
