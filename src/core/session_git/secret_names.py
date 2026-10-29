
from __future__ import annotations

from typing import Iterable

_NAMES = frozenset({
    ".credentials.json", ".npmrc", ".pypirc", ".netrc", "_netrc", ".git-credentials", ".pgpass", ".my.cnf",
    ".htpasswd", "credentials", "credentials.json", "secrets.json", "secrets.yml", "secrets.yaml",
    "service-account.json", "service_account.json", "terraform.tfstate", "kubeconfig", ".dockercfg",
})
_PREFIXES = (".env", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "authkey_", "serviceaccount", "service-account",
             "service_account")
_SUFFIXES = (".pem", ".key", ".p8", ".p12", ".pfx", ".keystore", ".jks", ".tfvars", ".tfvars.json", ".ppk",
             ".kdbx", ".gpg", ".asc", ".mobileprovision")
_DIRS = frozenset({".aws", ".ssh", ".gnupg", ".kube"})


def is_secret_name(name: str) -> bool:
    low = name.lower()
    return low in _NAMES or low.startswith(_PREFIXES) or low.endswith(_SUFFIXES)


def is_secret_path(*paths: Iterable[str]) -> bool:
    for rel in paths:
        if not rel:
            continue
        parts = [p for p in str(rel).split("/") if p]
        if any(p.lower() in _DIRS for p in parts[:-1]) or any(is_secret_name(p) for p in parts):
            return True
    return False
