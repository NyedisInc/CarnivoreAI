
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any, Callable, Dict, Optional, Sequence, Tuple, Union

import structlog

from src.core.pack.machines import capabilities as caps_mod, interim_policy, link_stamps, roster_doc, roster_v2, settings_doc, settings_sign
from src.core.pack.machines.config_state import ConfigState
from src.core.relay_identity.device_key import DeviceKeyUnavailable

logger = structlog.get_logger()

RefusedHook = Callable[[str, settings_sign.Verdict, settings_doc.PackSettings], None]


class SettingsCustody:

    def __init__(self, *, install_id: str, state: ConfigState, default_master: Callable[[], str],
                 signing: Optional[settings_sign.Signing] = None, paired: Callable[[], bool] = lambda: False,
                 clock: Callable[[], float] = time.time) -> None:
        self.install_id, self.state, self.signing = install_id, state, signing
        self._default_master, self._paired, self._clock = default_master, paired, clock
        self._roster_lock = threading.Lock()
        self._roster_reported: Dict[str, Tuple[str, int]] = {}
        self.roster_refusal: Optional[Dict[str, Any]] = None
        self.link_switches_unknown = False
        self.switch_refusal: Optional[Dict[str, Any]] = None
        self.switch_refusal_changed: Callable[[], None] = lambda: None
        if signing is not None:
            signing.roster_key = self._roster_fed_key
        self.refused: RefusedHook = lambda sender, verdict, doc: None
        self._reported: Dict[str, Tuple[str, str, str]] = {}
        self.takeover_on: Callable[[], bool] = lambda: False
        self.standing: Callable[[], Optional[interim_policy.Standing]] = lambda: None
        self.on_alpha_change: Callable[[str, str], None] = lambda master, kind: None
        self._seen_generation = 0
        self._rival: Optional[str] = None

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
        return self.state.save_settings(doc, signature, anchor=doc.master_install_id, alpha_since=self._alpha_since_for(doc))

    def _alpha_since_for(self, doc: settings_doc.PackSettings) -> Optional[int]:
        if not caps_mod.mesh_on() or doc.master_install_id != self.install_id or self.settings().master_install_id == self.install_id:
            return None
        return doc.rev[0]

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

    def merge(self, raw: Any, raw_signature: Any, sender: str, raw_roster: Any = None) -> bool:
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
        case = self._takeover_case(remote, signature, raw_roster, held, sender) if signed_mode else None
        verdict = settings_sign.judge(held=held, remote=remote, signature=signature, self_id=self.install_id,
                                      signed_mode=signed_mode, anchor=anchor, public_key_for=self.signing.public_key_for,
                                      takeover=case[0] if case is not None else None)
        if verdict.outcome == settings_sign.TAKEOVER and case is not None and signature is not None:
            return self.adopt_alpha(remote, signature, case[1], case[2], case[0], sender)
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
        self.state.save_settings(remote, stored_sig, signed_mode=trusted, anchor=None if trusted else anchor,
                              alpha_since=self._alpha_since_for(remote))
        self._note_home_signed(remote, signature)
        if verdict.outcome == settings_sign.ACCEPT_TOFU:
            logger.info("pack_settings_signed_tofu", sender=sender[:8], signer=remote.rev[1][:8], rev=list(remote.rev),
                        master=remote.master_install_id[:8])
        return True


    def roster(self) -> Optional[roster_doc.Roster]:
        stored = self.state.stored_roster()
        return stored[0] if stored is not None else None

    def _roster_fed_key(self, install_id: str) -> Optional[str]:
        try:
            held = self.roster()
        except (OSError, ValueError):
            return None
        entry = held.entry(install_id) if held is not None else None
        return entry.fed_public_key if entry is not None else None

    def roster_wire(self) -> Optional[Dict[str, Any]]:
        stored = self.state.stored_roster()
        if stored is None or stored[1] is None:
            return None
        return roster_doc.to_wire(stored[0], stored[1].to_dict())

    def held_lists(self) -> Optional[Tuple[Union[roster_doc.Roster, roster_v2.RosterV2], Optional[Dict[str, Any]]]]:
        if caps_mod.mesh_on():
            stored = self.state.stored_roster_v2()
            v1 = self.roster()
            if (stored is not None and stored[1] is not None and stored[0].alpha == self.settings().master_install_id
                    and (v1 is None or stored[0].generation >= v1.generation)):
                return stored[0], self.roster_wire()
        wire = self.roster_wire()
        parsed = roster_doc.from_wire(wire)
        return (parsed[0], wire) if parsed is not None and wire is not None else None

    def _issue_roster(self, roster: roster_doc.Roster) -> None:
        assert self.signing is not None
        signature = roster_doc.sign(roster, self.signing.key(), self.install_id)
        self.state.save_roster(roster_doc.to_wire(roster, signature.to_dict()))

    def _issue_roster_v2(self, roster: roster_v2.RosterV2) -> None:
        assert self.signing is not None
        signature = roster_v2.sign_v2(roster, self.signing.key(), self.install_id)
        self.state.save_roster_v2(roster_v2.to_wire_v2(roster, signature.to_dict()))

    def roster_v2(self) -> Optional[roster_v2.RosterV2]:
        stored = self.state.stored_roster_v2()
        return stored[0] if stored is not None else None

    def roster_v2_wire(self) -> Optional[Dict[str, Any]]:
        stored = self.state.stored_roster_v2()
        return None if stored is None or stored[1] is None else roster_v2.to_wire_v2(stored[0], stored[1].to_dict())

    def merge_roster_v2(self, raw: Any, sender: str) -> bool:
        parsed = roster_v2.from_wire_v2(raw)
        if parsed is None or parsed[1] is None or self.signing is None:
            return False
        remote, signature = parsed
        with self._roster_lock:
            held, base = self.roster_v2(), self.roster_v2() or self.roster()
            if held is None and base is not None and remote.generation < base.generation:
                return False
            if held is None:
                mem_kind, mem_gen, _ = self.state.link_switches()
                if mem_kind == "ok" and mem_gen is not None and remote.generation < mem_gen:
                    return False
            if base is not None and self.interim() and signature.signer != interim_policy.effective_home(base, self.home_state()):
                current = held is not None and held.alpha == interim_policy.effective_home(base, self.home_state())
                if not current or not roster_v2.interim_same(held, remote):
                    if self._roster_reported.get(sender) != ("v2interim", remote.generation):
                        self._roster_reported[sender] = ("v2interim", remote.generation)
                        logger.warning("pack_roster_v2_refused", sender=sender[:8], outcome="interim", generation=remote.generation)
                    return False
            verdict = roster_v2.judge_v2(held=held, remote=remote, signature=signature, held_alpha=self.settings().master_install_id,
                                         held_roster_alpha=held.alpha if held is not None else None,
                                         held_generation=self.settings().rev[0], public_key_for=self.signing.public_key_for)
            if not verdict.accepted:
                claim = ("v2" + verdict.outcome + verdict.reason, remote.generation)
                if verdict.refused and self._roster_reported.get(sender) != claim:
                    self._roster_reported[sender] = claim
                    logger.warning("pack_roster_v2_refused", sender=sender[:8], outcome=verdict.outcome, generation=remote.generation)
                return False
            mem_kind, _, mem_sw = self.state.link_switches()
            stale = link_stamps.older_on(link_stamps.known(mem_sw if mem_kind == "ok" else {}, self.state.link_stamps(), held), remote)
            if stale:
                claim = ("v2switch", remote.generation)
                if self._roster_reported.get(sender) != claim:
                    self._roster_reported[sender] = claim
                    logger.warning("pack_roster_v2_refused", sender=sender[:8], outcome="switch_older", generation=remote.generation, switches=len(stale))
                self._set_switch_refusal({"signer": signature.signer, "computers": sorted(stale)})
                return False
            self.state.save_roster_v2(roster_v2.to_wire_v2(remote, signature.to_dict()))
            self._set_switch_refusal(None)
        logger.info("pack_roster_v2_taken", sender=sender[:8], sha=roster_v2.sha(roster_v2.blob(raw))[:12], generation=remote.generation)
        return True

    def _link_source(self, v1: Optional[roster_doc.Roster]) -> Tuple[str, Dict[str, bool], Dict[str, int]]:
        floor = v1.generation if v1 is not None else 0
        stored = self.state.stored_roster_v2()
        kind, mem_gen, mem = self.state.link_switches()
        mem_at = self.state.link_stamps()
        best: Optional[Tuple[int, Dict[str, bool], Dict[str, int]]] = None
        if stored is not None:
            best = (stored[0].generation, {c.install_id: bool(c.link_peers) for c in stored[0].computers}, {c.install_id: c.link_at for c in stored[0].computers})
        if kind == "ok" and mem_gen is not None:
            if best is None or mem_gen > best[0]:
                best = (mem_gen, mem, mem_at)
            elif mem_gen == best[0]:
                best = (best[0], {k: v and mem.get(k, True) for k, v in best[1].items()}, {k: max(v, mem_at.get(k, 0)) for k, v in best[2].items()})
        if best is not None and best[0] >= floor:
            return "known", best[1], best[2]
        if kind == "absent" and stored is None and self.state.alpha_since() is None and (v1 is None or v1.home == self.install_id):
            return "first", {}, {}
        return "unknown", {}, {}

    def refresh_roster(self, inputs: Sequence[roster_doc.RosterInput], *, order: Optional[Sequence[str]] = None,
                       eligible: Optional[Dict[str, bool]] = None, link_peers: Optional[Dict[str, bool]] = None) -> str:
        if self.signing is None:
            return ""
        with self._roster_lock:
            if self.settings().master_install_id != self.install_id or self.interim():
                self.roster_refusal = None
                self._set_switches_unknown(False)
                return ""
            held = self.roster()
            known = {i.install_id for i in inputs}
            if any(i not in known for i in list(order or []) + list(eligible or {}) + list(link_peers or {})) or (order is not None and set(order) != known):
                raise roster_doc.RosterRefused("order and eligibility name only computers of the Pack, and the order names all of them")
            refusal: Optional[Dict[str, Any]] = None
            v2_held = self.roster_v2() if caps_mod.mesh_on() else None
            v2_new: Optional[roster_v2.RosterV2] = None
            unknown = False
            src_kind = ""
            link_source: Optional[Dict[str, bool]] = None
            source_at: Dict[str, int] = {}
            if caps_mod.mesh_on():
                src_kind, link_source, source_at = self._link_source(held)
                unknown = src_kind == "unknown"
                self._set_switches_unknown(unknown)
            if caps_mod.mesh_on():
                try:
                    v2_new = roster_v2.plan_v2(v2_held, inputs, alpha=self.install_id, home=held.home if held is not None else None,
                                               order=order, eligible=eligible, link_peers=link_peers, source=link_source,
                                               default_on=not (unknown and bool(link_peers)))
                except roster_doc.RosterFull as full:
                    if order is not None or eligible or link_peers:
                        raise
                    refusal = {"code": "pack_full", "count": full.count, "limit": full.limit}
            try:
                candidate = roster_doc.plan(held, inputs, alpha=self.install_id, order=order, eligible=eligible)
            except roster_doc.RosterFull as full:
                candidate = None
                if held is None and v2_new is None and v2_held is None:
                    raise
                if held is not None:
                    kept = [i for i in inputs if held.entry(i.install_id) is not None or i.install_id == self.install_id]
                    kept_ids = {i.install_id for i in kept}
                    if v2_new is None and (any(on and iid not in kept_ids for iid, on in (eligible or {}).items())
                                           or (order is not None and set(order) - kept_ids)):
                        raise
                    candidate = roster_doc.plan(held, kept, alpha=self.install_id, limit=len(kept), order=order,
                                                eligible={k: v for k, v in (eligible or {}).items() if k in kept_ids} if eligible is not None else None)
                    if len(kept) < len(inputs) and not caps_mod.mesh_on():
                        refusal = {"code": "pack_full", "count": full.count, "limit": full.limit}
            if refusal is not None and self.roster_refusal != refusal:
                logger.warning("pack_roster_full", count=refusal["count"], limit=refusal["limit"])
            if caps_mod.mesh_on() and any(on and (candidate is None or candidate.entry(iid) is None) for iid, on in (eligible or {}).items()):
                raise roster_doc.RosterRefused(f"a successor must be one of the first {roster_doc.MAX_COMPUTERS} computers")
            self.roster_refusal = refusal
            usable = candidate is not None and len(candidate.computers) >= 2
            usable2 = v2_new is not None and len(v2_new.computers) >= 2 and not (unknown and not link_peers)
            if not usable and not usable2:
                return ""
            now = int(self._clock())
            reason = ((roster_doc.bump_reason(held, candidate) if usable else None) or (roster_v2.bump_reason_v2(v2_held, v2_new) if usable2 else None)
                      or ("authority" if usable2 and link_peers else None))
            try:
                if reason is not None:
                    minted = self.mint({}, strict=True)
                    v2_final = link_stamps.stamped(roster_v2.RosterV2(**{**v2_new.model_dump(), "generation": minted.rev[0], "issued_at": now}),
                                                   link_peers or {}, link_source or {}, source_at) if usable2 else None
                    if caps_mod.mesh_on() and src_kind == "known":
                        if v2_final is not None:
                            self.state.advance_link_switches(minted.rev[0], {c.install_id: bool(c.link_peers) for c in v2_final.computers},
                                                             {c.install_id: c.link_at for c in v2_final.computers})
                        else:
                            self.state.advance_link_switches(minted.rev[0], link_source or {})
                    if usable:
                        self._issue_roster(roster_doc.Roster(**{**candidate.model_dump(), "generation": minted.rev[0], "issued_at": now}))
                    if v2_final is not None:
                        self._issue_roster_v2(v2_final)
                    logger.info("pack_roster_issued", reason=reason, generation=minted.rev[0], computers=len(candidate.computers) if usable else 0)
                    return "bump:" + reason
                hint = False
                if usable and held is not None and roster_doc.hints_changed(held, candidate) and now - held.issued_at >= roster_doc.HINT_REISSUE_SECONDS:
                    self._issue_roster(roster_doc.Roster(**{**candidate.model_dump(), "generation": held.generation, "issued_at": now}))
                    hint = True
                if usable2 and v2_held is not None and roster_doc.hints_changed(v2_held, v2_new) and now - v2_held.issued_at >= roster_doc.HINT_REISSUE_SECONDS:
                    self._issue_roster_v2(roster_v2.RosterV2(**{**v2_new.model_dump(), "generation": v2_held.generation, "issued_at": now}))
                    hint = True
                return "hint" if hint else ""
            except DeviceKeyUnavailable:
                logger.warning("pack_roster_sign_failed")
            return ""

    def _set_switch_refusal(self, value: Optional[Dict[str, Any]]) -> None:
        if value != self.switch_refusal:
            self.switch_refusal = value
            self.switch_refusal_changed()

    def _set_switches_unknown(self, value: bool) -> None:
        if value != self.link_switches_unknown:
            self.link_switches_unknown = value
            logger.warning("pack_link_switches_unknown", unknown=value)

    def hand_over_roster(self, doc: settings_doc.PackSettings) -> bool:
        if self.signing is None:
            return False
        with self._roster_lock:
            v1 = self.roster()
            v2 = self.roster_v2() if caps_mod.mesh_on() and self.roster_v2_wire() is not None else None
            to_v1 = v1 is not None and doc.master_install_id != v1.alpha and v1.entry(doc.master_install_id) is not None
            to_v2 = (to_v1 and v2 is not None and v2.generation == v1.generation and doc.master_install_id != v2.alpha
                     and v2.entry(doc.master_install_id) is not None)
            if not to_v1 and not to_v2:
                return False
            now = int(self._clock())
            try:
                if to_v1:
                    home = doc.master_install_id if v1.home == self.install_id else v1.home
                    self._issue_roster(roster_doc.Roster(**{**v1.model_dump(), "alpha": doc.master_install_id, "home": home,
                                                            "generation": doc.rev[0], "issued_at": now}))
                if to_v2:
                    home = doc.master_install_id if v2.home == self.install_id else v2.home
                    self._issue_roster_v2(roster_v2.RosterV2(**{**v2.model_dump(), "alpha": doc.master_install_id, "home": home,
                                                                "generation": doc.rev[0], "issued_at": now}))
            except (DeviceKeyUnavailable, OSError, ValueError) as exc:
                logger.warning("pack_roster_handover_failed", error_type=type(exc).__name__)
                return False
            return True

    def clear_roster(self, wipe: bool = True) -> bool:
        with self._roster_lock:
            changed = self.state.clear_roster()
            self._set_switch_refusal(None)
        if wipe and caps_mod.mesh_on():
            self._forget_mesh_data()
        return changed

    def adopt_join(self, doc: settings_doc.PackSettings, signature: Optional[Dict[str, Any]] = None) -> bool:
        same = caps_mod.mesh_on() and self._same_pack(doc)
        changed = self.adopt(doc, signature)
        self.clear_roster(wipe=not same)
        return changed

    def _same_pack(self, doc: settings_doc.PackSettings) -> bool:
        try:
            held_master = self.settings().master_install_id
            if doc.master_install_id != held_master:
                return False
            held = self.held_lists()
        except (OSError, ValueError) as exc:
            logger.debug("mesh_same_pack_unreadable", error_type=type(exc).__name__)
            return False
        lst = held[0] if held else None
        return lst is None or (lst.alpha == held_master and lst.home == held_master)

    def _forget_mesh_data(self) -> None:
        from src.core.pack.machines import operating

        try:
            operating.forget_pack(self.install_id)
        except (sqlite3.Error, OSError) as exc:
            logger.warning("mesh_store_clear_failed", error=type(exc).__name__)
        from src.core.computers import mesh_removal

        try:
            mesh_removal.forget_pack()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("mesh_removal_clear_failed", error=type(exc).__name__)

    def merge_roster(self, raw: Any, sender: str) -> bool:
        parsed = roster_doc.from_wire(raw)
        if parsed is None or self.signing is None:
            return False
        remote, signature = parsed
        with self._roster_lock:
            held = self.roster()
            if held is not None and self.interim() and signature.signer != interim_policy.effective_home(held, self.home_state()):
                same, why = interim_policy.content_check(held_roster=held, new_roster=remote, held_doc=self.settings(), new_doc=self.settings())
                if not same:
                    if self._roster_reported.get(sender) != ("interim" + why, remote.generation):
                        self._roster_reported[sender] = ("interim" + why, remote.generation)
                        logger.warning("pack_roster_refused", sender=sender[:8], outcome="interim", reason=why, generation=remote.generation)
                    return False
            verdict = roster_doc.judge(held=held, remote=remote, signature=signature, held_alpha=self.settings().master_install_id,
                                       held_roster_alpha=held.alpha if held is not None else None,
                                       held_generation=self.settings().rev[0], public_key_for=self.signing.public_key_for)
            if not verdict.accepted:
                claim = (verdict.outcome + verdict.reason, remote.generation)
                if verdict.refused and self._roster_reported.get(sender) != claim:
                    self._roster_reported[sender] = claim
                    logger.warning("pack_roster_refused", sender=sender[:8], outcome=verdict.outcome, reason=verdict.reason,
                                   generation=remote.generation)
                return False
            state = self.home_state()
            self.state.save_roster(roster_doc.to_wire(remote, signature.to_dict()))
            if interim_policy.effective_home(remote, state) != interim_policy.effective_home(held, state) and state.last_home is not None:
                self.state.save_takeover_state(state.home_override, None)
        logger.info("pack_roster_taken", sender=sender[:8], generation=remote.generation, computers=len(remote.computers))
        return True


    def home_state(self) -> interim_policy.HomeState:
        override, last = self.state.takeover_state()
        return interim_policy.HomeState(override, last)

    def interim(self) -> bool:
        return interim_policy.is_interim(self.settings().master_install_id, self.roster(), self.home_state())

    def content_alpha(self) -> Optional[str]:
        return interim_policy.content_alpha(self.settings().master_install_id, self.interim())

    def can_claim(self) -> bool:
        roster = self.roster()
        if self.signing is None or roster is None or not self.takeover_on():
            return False
        entry = roster.entry(self.install_id)
        try:
            return entry is not None and entry.fed_public_key == self.signing.public_key_for(self.install_id)
        except DeviceKeyUnavailable:
            return False

    def rival_alpha(self) -> Optional[str]:
        return self._rival

    def seen_generation(self) -> int:
        return self._seen_generation

    def _note_home_signed(self, doc: settings_doc.PackSettings, signature: Optional[settings_sign.Signature]) -> None:
        if signature is None:
            return
        try:
            roster, state = self.roster(), self.home_state()
            if roster is None or signature.signer != interim_policy.effective_home(roster, state):
                return
            issued = roster.issued_at if roster.alpha == signature.signer else (state.last_home[1] if state.last_home else 0)
            last = max(state.last_home or (0, 0), (doc.rev[0], issued))
            if last != state.last_home:
                self.state.save_takeover_state(state.home_override, last)
        except (OSError, ValueError) as exc:
            logger.warning("pack_last_home_not_saved", error_type=type(exc).__name__)

    def _takeover_case(self, remote: settings_doc.PackSettings, signature: Optional[settings_sign.Signature], raw_roster: Any,
                       held: settings_doc.PackSettings, sender: str) -> Optional[Tuple[str, roster_doc.Roster, settings_sign.Signature]]:
        if signature is None or self.signing is None or signature.signer != remote.rev[1] or not self.takeover_on():
            return None
        parsed, held_roster = roster_doc.from_wire(raw_roster), self.roster()
        signer = signature.signer
        if parsed is None or held_roster is None or parsed[1] is None or remote.master_install_id != signer or signer == held.master_install_id:
            return None
        roster, rsig = parsed
        key = self.signing.public_key_for(signer)
        if (rsig.signer != signer or roster.alpha != signer or roster.generation > remote.rev[0] or key is None
                or not roster_doc.verify(roster, rsig, key) or not interim_policy.eligible(held_roster, signer)):
            return None
        self._seen_generation = max(self._seen_generation, remote.rev[0])
        state, master = self.home_state(), held.master_install_id
        home = interim_policy.effective_home(held_roster, state)
        if signer == home:
            ok, why = interim_policy.home_document_ok(state=state, interim=interim_policy.is_interim(master, held_roster, state),
                                                      generation=remote.rev[0], issued_at=roster.issued_at,
                                                      held_generation=held.rev[0])
            if not ok:
                logger.info("pack_home_document_refused", sender=sender[:8], reason=why)
            return (settings_sign.HOME, roster, rsig) if ok else None
        same, why = interim_policy.content_check(held_roster=held_roster, new_roster=roster, held_doc=held, new_doc=remote)
        if not same:
            logger.warning("pack_takeover_content_refused", sender=sender[:8], signer=signer[:8], reason=why)
            return None
        standing = self.standing()
        if master == self.install_id:
            decision, why = interim_policy.meeting_decision(
                roster=held_roster, state=state, self_id=self.install_id, self_generation=held.rev[0], other=signer,
                other_generation=remote.rev[0], silent_seconds=standing.silent.get(signer, 0.0) if standing is not None else 0.0)
            if decision == "stay" and why != "this computer wins":
                self._rival = signer
            logger.info("pack_alphas_met", other=signer[:8], decision=decision, reason=why)
            return (settings_sign.HEAL, roster, rsig) if decision == "step_down" else None
        if sender == master:
            mine, theirs = interim_policy.rank(held_roster, master), interim_policy.rank(held_roster, signer)
            higher = remote.rev[0] > held.rev[0]
            return (settings_sign.VOUCH, roster, rsig) if higher or (theirs is not None and (mine is None or theirs < mine)) else None
        if standing is None:
            return None
        ok, why = interim_policy.member_accepts(roster=held_roster, self_id=self.install_id, self_can_claim=self.can_claim(), held_alpha=master,
                                                claimant=signer, claim_generation=remote.rev[0], held_generation=held.rev[0], standing=standing)
        if not ok:
            logger.info("pack_takeover_claim_refused", signer=signer[:8], reason=why)
        return (settings_sign.CLAIM, roster, rsig) if ok else None

    def adopt_alpha(self, doc: settings_doc.PackSettings, signature: settings_sign.Signature, roster: roster_doc.Roster,
                    roster_signature: settings_sign.Signature, case: str, sender: str,
                    roster_v2_wire: Optional[Dict[str, Any]] = None) -> bool:
        with self._roster_lock:
            before_roster, state = self.roster(), self.home_state()
            before_home = interim_policy.effective_home(before_roster, state)
            home = interim_policy.effective_home(roster, state)
            last = None if home != before_home else state.last_home
            held_doc = self.settings()
            if last is None and home == before_home and before_roster is not None and held_doc.rev[1] == home:
                last = (held_doc.rev[0], before_roster.issued_at)
            if doc.rev[1] == home:
                last = max(last or (0, 0), (doc.rev[0], roster.issued_at))
            held_v2 = self.roster_v2() if caps_mod.mesh_on() and roster_v2_wire is None else None
            drop = held_v2 is not None and before_roster is not None and (held_v2.alpha != before_roster.alpha or held_v2.generation < before_roster.generation)
            try:
                self.state.save_adoption(doc, signature.to_dict(), roster_doc.to_wire(roster, roster_signature.to_dict()), state.home_override, last,
                                         roster_v2_wire=roster_v2_wire, drop_roster_v2=drop, alpha_since=self._alpha_since_for(doc))
            except (OSError, ValueError) as exc:
                logger.warning("pack_adopt_alpha_failed", error_type=type(exc).__name__)
                return False
        self._rival = None
        if drop and held_v2 is not None and before_roster is not None:
            logger.info("pack_roster_v2_dropped", held_generation=held_v2.generation, v1_generation=before_roster.generation)
        logger.info("pack_alpha_adopted", case=case, sender=sender[:8], master=doc.master_install_id[:8], generation=doc.rev[0])
        self.on_alpha_change(doc.master_install_id, case)
        return True

    def _own_alpha_documents(self, base: settings_doc.PackSettings) -> Tuple[settings_doc.PackSettings, settings_sign.Signature, roster_doc.Roster,
                                                                              settings_sign.Signature, Optional[Dict[str, Any]]]:
        assert self.signing is not None
        held = self.roster()
        if held is None or held.entry(self.install_id) is None:
            raise roster_doc.RosterRefused("no roster that lists this computer")
        doc = settings_doc.edited(base, {"master_install_id": self.install_id}, self.install_id)
        signature = self.signing.sign(doc)
        issued = int(self._clock())
        roster = roster_doc.Roster(**{**held.model_dump(), "alpha": self.install_id, "generation": doc.rev[0], "issued_at": issued})
        v2_wire: Optional[Dict[str, Any]] = None
        v2 = self.roster_v2() if caps_mod.mesh_on() and self.roster_v2_wire() is not None else None
        if (v2 is not None and v2.generation == held.generation and v2.alpha == held.alpha
                and v2.entry(self.install_id) is not None):
            signed = roster_v2.RosterV2(**{**v2.model_dump(), "alpha": self.install_id, "generation": doc.rev[0], "issued_at": issued})
            v2_wire = roster_v2.to_wire_v2(signed, roster_v2.sign_v2(signed, self.signing.key(), self.install_id).to_dict())
        return doc, signature, roster, roster_doc.sign(roster, self.signing.key(), self.install_id), v2_wire

    def claim(self) -> bool:
        if self.signing is None or not self.takeover_on():
            return False
        try:
            doc, sig, roster, rsig, v2_wire = self._own_alpha_documents(self.settings())
        except (DeviceKeyUnavailable, ValueError) as exc:
            logger.warning("pack_claim_failed", error_type=type(exc).__name__)
            return False
        return self.adopt_alpha(doc, sig, roster, rsig, settings_sign.CLAIM, self.install_id, roster_v2_wire=v2_wire)

    def reclaim_home(self) -> bool:
        if self.signing is None or not self.takeover_on():
            return False
        held = self.settings()
        base = held.model_copy(update={"rev": (max(held.rev[0], self._seen_generation), held.rev[1])})
        try:
            doc, sig, roster, rsig, v2_wire = self._own_alpha_documents(base)
        except (DeviceKeyUnavailable, ValueError) as exc:
            logger.warning("pack_reclaim_failed", error_type=type(exc).__name__)
            return False
        return self.adopt_alpha(doc, sig, roster, rsig, settings_sign.HOME, self.install_id, roster_v2_wire=v2_wire)

    def confirm_local(self) -> bool:
        with self._roster_lock:
            roster, state, master = self.roster(), self.home_state(), self.settings().master_install_id
            if roster is None or not interim_policy.is_interim(master, roster, state):
                return False
            changed = self.state.save_takeover_state(master, None)
        logger.info("pack_interim_confirmed", master=master[:8])
        return changed

    def clear_home_override(self) -> bool:
        with self._roster_lock:
            state = self.home_state()
            return state.home_override is not None and self.state.save_takeover_state(None, None)

