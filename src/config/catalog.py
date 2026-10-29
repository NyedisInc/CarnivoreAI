
from pydantic import BaseModel

from src.core.catalog.client import DEFAULT_INDEX_URL
from src.core.catalog.hosted_api import DEFAULT_API_BASE_URL

CATALOG_KEY = "catalog"


class CatalogConfig(BaseModel):
    """Where this install reads its signed skills catalog from.
    """

    index_url: str = DEFAULT_INDEX_URL
    api_base_url: str = DEFAULT_API_BASE_URL
    install_backfill_done: bool = False
