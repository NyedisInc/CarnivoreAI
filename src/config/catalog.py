
from pydantic import BaseModel

from src.core.catalog.client import DEFAULT_INDEX_URL
from src.core.catalog.hosted_api import DEFAULT_API_BASE_URL

CATALOG_KEY = "catalog"


class CatalogConfig(BaseModel):
    """Where this install reads its signed skills catalog from.

    Fields:
        index_url: the absolute url of the signed index document, NOT a
            base directory: the detached signature is this url with
            ``.minisig`` appended to its path. It MUST be https, and the
            fetcher refuses anything else before it opens a socket, so
            pointing this at a plain-http host fails closed rather than
            leaking which catalog this install watches.
        api_base_url: the base of the hosted api that serves ratings and
            GitHub sign in, e.g. ``https://host/api/v1``. A DIRECTORY
            here, unlike ``index_url``, because it is the root several
            paths hang off rather than one document. It belongs in this
            block and NOT in ``ui_preferences`` for the reason above: it
            decides where this app's own server opens a network
            connection, which is a server-owned and security-relevant
            fact the browser must not be able to set. It MUST be https,
            and the client refuses anything else before it opens a
            socket.
        install_backfill_done: written by ``install_reporter`` (true) once the first run
            of the always-on reporter has reported what was already installed. Install
            reporting has no switch (``docs/DECISIONS.md``, 2026-10-05); a leftover
            ``report_installs`` key in an old file is ignored (``extra="ignore"``).
    """

    index_url: str = DEFAULT_INDEX_URL
    api_base_url: str = DEFAULT_API_BASE_URL
    install_backfill_done: bool = False
