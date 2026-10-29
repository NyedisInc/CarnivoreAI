
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

RELAY_KEY = "relay"

DEFAULT_RELAY_PUBLISH_URL = "wss://relay.carnivore.ai/publish"


DEFAULT_RELAY_CONTROL_URL = "https://api.carnivore.ai/v1/relay"

DEFAULT_LINK_TUNNEL_URL = "wss://relay.carnivore.ai/v1/link/tunnel"

DEFAULT_LINK_DOMAIN = "link.carnivore.ai"

LE_PRODUCTION_DIRECTORY = "https://acme-v02.api.letsencrypt.org/directory"
LE_STAGING_DIRECTORY = "https://acme-staging-v02.api.letsencrypt.org/directory"


def viewer_base_url(publish_url: str) -> str:
    parts = urlsplit(publish_url)
    prefix = parts.path.rsplit("/", 1)[0]
    return f"https://{parts.netloc}{prefix}"


class RelayConfig(BaseModel):
    """Whether and where shared sessions are published.

    Fields:
        enabled: on by default; False is the kill switch, meaning
            nothing is published and no outbound connection is opened.
        url: the relay's ``/publish`` endpoint. Must be ``wss://``; the
            publisher refuses anything else rather than send a bearer
            token in the clear.
        idle_flush_ms: quiet period after which each link's held-back
            redactor tail is released.
        refresh_seconds: how often the live link set is re-read from the
            store, which is how a revoke or an expiry ends a relayed share.
        control_url: the relay control plane (device registration and
            relay tokens). Must be ``https://``.
        legacy_fallback: True (today's behaviour) lets the publisher fall
            back to the shared v1 token when the device identity is
            unavailable; False never reads the legacy token at all (the
            test slots' setting, so a slot can never publish as the
            shared identity).
        link_tunnel_url / link_domain / link_acme_directory: the phone
            link's tunnel, zone and ACME directory (docs/phone-link.md).
        device_key_file: when set, the device key lives in this 0600 file
            instead of the login Keychain (test slots, whose private HOME
            has no Keychain). Empty, the default, is the Keychain.
    """

    enabled: bool = True
    url: str = DEFAULT_RELAY_PUBLISH_URL
    idle_flush_ms: int = Field(default=200, ge=1)
    refresh_seconds: float = Field(default=5.0, gt=0)
    control_url: str = DEFAULT_RELAY_CONTROL_URL
    legacy_fallback: bool = True
    link_tunnel_url: str = DEFAULT_LINK_TUNNEL_URL
    link_domain: str = DEFAULT_LINK_DOMAIN
    link_acme_directory: str = LE_PRODUCTION_DIRECTORY
    device_key_file: str = ""
