
from typing import Optional

from src.core.phone_link.pairing import PairingStore


def pair_device(store: PairingStore, ip: str, label: str = "phone", host: str = "") -> Optional[str]:
    handle = store.claim_secret(store.open_window().secret, ip, label, host).handle
    return store.complete_pending(handle, host)
