"""
``PackMachines`` (``exchange.py``) delegates every read and write of the document here. The rules live in ``settings_sign``;
this class applies them to the stored copy: a received document is judged, stored with its signature in one write, and the
first accepted signed document from the trust anchor turns signed mode on (trust on first use, logged). An upgraded alpha that
is paired and has not signed yet mints one content-free signed revision, so the Pack enters signed mode as soon as alpha runs
this build.

Without a ``Signing`` (a test, or a Pack layer that could not reach its key) everything behaves as before #1921: nothing is
signed and every document merges by ``rev``. Blocking (config and Keychain reads): call off the loop.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

import structlog

from src.core.pack.machines import settings_doc, settings_sign
from src.core.pack.machines.config_state import ConfigState
from src.core.relay_identity.device_key import DeviceKeyUnavailable

logger = structlog.get_logger()

RefusedHook = Callable[[str, settings_sign.Verdict, settings_doc.PackSettings], None]


class SettingsCustody:

    def __init__(self, *, install_id: str, state: ConfigState, default_master: Callable[[], str],
                 signing: Optional[settings_sign.Signing] = None, paired: Callable[[], bool] = lambda: False) -> None:
        self.install_id, self.state, self.signing = install_id, state, signing
        self._default_master, self._paired = default_master, paired
        self.refused: RefusedHook = lambda sender, verdict, doc: None
        self._reported: Dict[str, Tuple[str, str, str]] = {}

    def settings(self) -> settings_doc.PackSettings:
        return self.state.stored_settings() or settings_doc.default_doc(self._default_master())

    def _signature_for(self, doc: settings_doc.PackSettings, strict: bool) -> Optional[Dict[str, str]]:
        if self.signing is None or doc.rev[1] != self.install_id:
            return None
        try:
            return self.signing.sign(doc).to_dict()
        except DeviceKeyUnavailable:
            if strict:
                raise
            logger.warning("pack_settings_sign_failed", rev=list(doc.rev))
            return None

    def held_signature(self) -> Optional[Dict[str, Any]]:
        return self.state.settings_signature() if self.state.stored_settings() is not None else None

    def mint(self, changes: Dict[str, Any], *, base: Optional[settings_doc.PackSettings] = None,
             strict: bool = False) -> settings_doc.PackSettings:
        doc = settings_doc.edited(base if base is not None else self.settings(), changes, self.install_id)
        signature = self._signature_for(doc, strict)
        self.state.save_settings(doc, signature, signed_mode=signature is not None and doc.master_install_id == self.install_id,
                                 anchor=doc.master_install_id)
        return doc

    def adopt(self, doc: settings_doc.PackSettings, signature: Optional[Dict[str, Any]] = None) -> bool:
        return self.state.save_settings(doc, signature, anchor=doc.master_install_id)

    def outgoing(self) -> Tuple[Dict[str, Any], Optional[Dict[str, str]]]:
        self.ensure_alpha_signed()
        doc = self.settings()
        signature = self.held_signature()
        parsed = settings_sign.signature_from(signature)
        if parsed is not None and parsed.signer == self.install_id:
            signature = self._signature_for(doc, strict=False)
        return doc.model_dump(mode="json"), signature

    def ensure_alpha_signed(self) -> bool:
        if self.signing is None or self.state.signed_mode():
            return False
        doc = self.settings()
        if doc.master_install_id != self.install_id or not self._paired():
            return False
        try:
            self.mint({}, strict=True)
        except (DeviceKeyUnavailable, OSError, ValueError) as exc:
            logger.warning("pack_settings_first_sign_failed", error_type=type(exc).__name__)
            return False
        logger.info("pack_settings_signed_mode_on", role="alpha", rev=doc.rev[0] + 1)
        return True

    def merge(self, raw: Any, raw_signature: Any, sender: str) -> bool:
        remote = settings_doc.from_dict(raw)
        if remote is None:
            return False
        held = self.settings()
        if self.signing is None:
            if not settings_doc.newer(remote, held):
                return False
            self.state.save_settings(remote)
            return True
        signed_mode = self.state.signed_mode()
        anchor = self.state.tofu_anchor() or held.master_install_id
        signature = settings_sign.signature_from(raw_signature)
        verdict = settings_sign.judge(held=held, remote=remote, signature=signature, self_id=self.install_id,
                                      signed_mode=signed_mode, anchor=anchor, public_key_for=self.signing.public_key_for)
        if not verdict.accepted:
            noteworthy = verdict.refused or verdict.reason == settings_sign.REASON_EQUIVOCATION
            claim = (verdict.outcome + verdict.reason, remote.rev[1], remote.master_install_id)
            if noteworthy and self._reported.get(sender) != claim:
                self._reported[sender] = claim
                logger.warning("pack_settings_refused", sender=sender[:8], outcome=verdict.outcome, reason=verdict.reason,
                               rev=list(remote.rev), master=remote.master_install_id[:8], held_master=held.master_install_id[:8])
                if verdict.refused:
                    self.refused(sender, verdict, remote)
            return False
        trusted = verdict.outcome in settings_sign.SIGNED_MODE_ON
        stored_sig = None if verdict.outcome == settings_sign.LEGACY or signature is None else signature.to_dict()
        self.state.save_settings(remote, stored_sig, signed_mode=trusted, anchor=None if trusted else anchor)
        if verdict.outcome == settings_sign.ACCEPT_TOFU:
            logger.info("pack_settings_signed_tofu", sender=sender[:8], signer=remote.rev[1][:8], rev=list(remote.rev),
                        master=remote.master_install_id[:8])
        return True
