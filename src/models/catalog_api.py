
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from src.models.catalog_contents import UpdateDiff

from .skill_watch import DriftView


class RefusalBody(BaseModel):
    """A refusal, in the shape every catalog 409 and 502 carries.

    Fields:
        code: the closed-list refusal code the client switches on.
        detail: what refused, for a log and for a developer. Never UI
            copy, and never any part of a key, a signature or a body.
    """

    code: str
    detail: Optional[str] = None


class IndexStatus(BaseModel):
    """What this server currently believes about the remote index.

    Fields:
        serial: the verified serial, or null when nothing has verified.
        generated_at: the index's own build stamp, as it signed it.
        as_of: the same instant, and the one the panel prints. It is a
            separate field because ``generated_at`` is the document's
            word for it and ``as_of`` is the user's.
        degraded: it verified, but it is older than the freshness window.
            A badge, never a refusal.
        stale: the refresh throttle has elapsed, so the next read would
            go to the network. Says nothing about whether the index is
            good.
        fetched_at: epoch seconds of the last completed round trip.
        refusal: why the most recent refresh did not replace what is
            held. Present ALONGSIDE a good index, which is the degraded
            state; absent when the last refresh succeeded.
        refreshed: whether a FORCED refresh actually went to the network.
            Only ``POST /catalog/index/refresh`` sets it, because only
            that route forces; ``false`` means the request arrived inside
            the force floor and was answered from the held snapshot.
            NULL on every other route, which means "not applicable" and
            never "no". A client must not read a null as a failure.
    """

    serial: Optional[int] = None
    generated_at: Optional[str] = None
    as_of: Optional[str] = None
    degraded: bool = False
    stale: bool = True
    fetched_at: Optional[float] = None
    refusal: Optional[RefusalBody] = None
    refreshed: Optional[bool] = None


class InstalledRef(BaseModel):
    """The local half of a catalog row: what this machine already has.

    Fields:
        install_id: the ledger id, which is what an uninstall addresses.
        scope: ``global`` or ``project``.
        project_path: the canonical project directory, empty for global.
        version: the version string that is installed, which may be
            behind the index's latest.
        update_available: the badge, computed by DIGEST rather than by
            version string, because a version string can be reused.
    """

    install_id: str
    scope: str
    project_path: str
    version: str
    update_available: bool


class CatalogItemView(BaseModel):
    """One catalog entry as the panel reads it, with its local state joined.

    Fields:
        id, kind, name, publisher, latest, card, fm, versions: the
            item exactly as the verified index carries it.
        installed: the ledger row for this item, or null when this
            machine does not have it. Null is a real answer and the
            panel paints it as "not installed".
        untrusted: this item's publisher key is not one the app pins, so
            it is LISTED and cannot be installed.
        featured_rank: position in the signed featured list (0 first), or
            null when the item is not featured or the index has no list.
        first_published_at: the oldest ``published_at`` among the item's
            versions as signed, or null when no version carries one.
        cost: the index's estimated token cost block, or null when the
            index carries none.
    """

    id: str
    kind: str
    name: str
    publisher: str
    latest: str
    card: Dict[str, Any]
    fm: Dict[str, Any]
    versions: List[Dict[str, Any]]
    installed: Optional[InstalledRef] = None
    untrusted: bool = False
    featured_rank: Optional[int] = None
    first_published_at: Optional[str] = None
    cost: Optional[Dict[str, Any]] = None


class CatalogListResponse(BaseModel):
    """``GET /catalog/items``: the index state and two item lists.

    Fields:
        index: what this server believes about the index itself.
        items: installable entries, signed by the pinned publisher key.
        untrusted: entries whose key is not pinned. NEVER HIDDEN: a
            catalog that silently drops them is indistinguishable from
            one that carries nothing from that key.
    """

    index: IndexStatus
    items: List[CatalogItemView] = Field(default_factory=list)
    untrusted: List[CatalogItemView] = Field(default_factory=list)


class CatalogItemResponse(BaseModel):
    """``GET /catalog/items/{item_id}``: one entry, with the index state.

    Fields:
        index: the same status block the list carries, so a client that
            deep-linked to one item can still show the "as of" badge.
        item: the entry.
    """

    index: IndexStatus
    item: CatalogItemView


from .catalog_loadout_api import (  # noqa: E402,F401
    LoadoutMemberPreview,
    LoadoutMemberView,
)


class InstalledItemView(BaseModel):
    """One ledger row, plus the badge computed against the current index.

    Fields:
        every ``installed_items`` column the client renders, spelled as
            the table spells it, plus ``update_available``.
    """

    install_id: str
    item_id: str
    kind: str
    publisher: str
    name: str
    version: str
    digest: str
    scope: str
    project_path: str
    auto_update: bool
    source_index_url: str
    publisher_key_id: str
    revision: int
    installed_at: str
    updated_at: str
    update_available: bool
    consent_via: str = "sheet"

    drift: Optional[DriftView] = None
    forked: bool = False

    members: Optional[List[LoadoutMemberView]] = None
    complete: Optional[bool] = None
    mod_registration: Optional[str] = None


class InstalledListResponse(BaseModel):
    """``GET /catalog/installed``: every row this app installed."""

    items: List[InstalledItemView] = Field(default_factory=list)


class PreviewFile(BaseModel):
    """One file the install would write.

    Fields:
        path: POSIX path relative to the skill folder root.
        size: bytes on disk, measured from the staged copy.
    """

    path: str
    size: int


class NameTakenChoice(BaseModel):
    """One way past a name collision, with what it would cost.

    Fields:
        choice: ``install_as`` or ``replace``, passed back verbatim.
        name: the folder name that choice installs under.
        added, changed, removed: file counts, NEVER a text diff.
        bytes_delta: signed; negative means the result is smaller.
        against: the existing directory those counts describe.
    """

    choice: str
    name: str
    added: Optional[int] = None
    changed: Optional[int] = None
    removed: Optional[int] = None
    bytes_delta: Optional[int] = None
    against: Optional[str] = None


class McpServerPreview(BaseModel):
    """One MCP server a staged plugin would register: the program the harness spawns.

    Fields:
        name: the server's key in ``mcpServers``.
        command, args: the FULL command line, shown verbatim on the sheet.
        env_keys: the env variable NAMES only; values are never sent.
    """

    name: str
    command: str
    args: List[str] = Field(default_factory=list)
    env_keys: List[str] = Field(default_factory=list)


class InstallPreviewResponse(BaseModel):
    """``POST /catalog/install/preview``: the whole consent surface.

    Fields:
        body: the SKILL.md text, verbatim, capped by the previewer.
        body_truncated: the cap was reached, so the text is partial.
        files, total_bytes: what would land, measured from the staged
            copy rather than taken from the index.
        publisher, version, key_id, pinned: who signed it and whether
            that key is one of the app's own constants.
        index_host: the host the index came from, so the user can see
            which catalog this is.
        digest_prefix: the first twelve characters, kept beside the
            whole value below for a compact render. For recognition, not
            for proof; the full digest was already checked.
        digest: the WHOLE folder digest, sixty-four hex characters. IT IS
            WHAT A CONSENT IS RECORDED AGAINST, so the sheet publishes it
            and the client echoes it back rather than rebuilding it: a
            consent naming the prefix would be consent to any version
            sharing those twelve characters.
        warnings: front matter keys the two harnesses disagree about.
            Warned on, never stripped.
        script_files: every file in this skill that is executable
            content, meaning anything under ``scripts/`` plus every file
            the publisher marked executable. THESE ARE ALSO IN ``files``:
            the sheet shows the whole folder and marks these, it does not
            show them instead. Empty for a skill that carries none.
        mcp_servers: every MCP server a plugin declares (command, args,
            env KEYS only). An MCP server is code the harness spawns at
            session start, so the sheet shows each in full and a
            non-empty list gates the tick like scripts do.
        requires_consent: this skill carries executable content, so
            installing it needs an explicit consent action naming these
            exact bytes. It is a STATEMENT ABOUT THE ITEM, not about
            whether consent has been given; the server decides the
            latter and answers ``consent_required`` when it has not.
        review: what a machine review said, or that it did not run.
        plan_token: names the staged copy this sheet describes, so
            pressing install does not download the tarball again.
        body_sha: sha256 of the ``SKILL.md`` FILE, not of the possibly
            capped text above. Carried on every preview and on the 409
            ``consent_required`` an update answers, because it is one of
            the two values a caller echoes back in ``consent`` once a
            person has read that text, and a sheet that withheld it left
            a script-bearing item impossible to install from a browser.
        code, detail, choices: present ONLY on the 409 that offers a way
            past a name collision, or the one that asks for fresh consent
            to changed instructions, both of which carry this same body.
    """

    body: str
    body_truncated: bool = False
    files: List[PreviewFile] = Field(default_factory=list)
    total_bytes: int = 0
    publisher: str
    version: str
    key_id: Optional[str] = None
    pinned: bool = True
    index_host: Optional[str] = None
    digest_prefix: Optional[str] = None
    digest: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    script_files: List[str] = Field(default_factory=list)
    mcp_servers: List["McpServerPreview"] = Field(default_factory=list)
    requires_consent: bool = False
    review: Optional[Dict[str, Any]] = None
    plan_token: Optional[str] = None
    body_sha: Optional[str] = None
    code: Optional[str] = None
    detail: Optional[str] = None
    choices: Optional[List[NameTakenChoice]] = None
    loadout_members: Optional[List[LoadoutMemberPreview]] = None
    mod_report: Optional[Dict[str, Any]] = None
    mod_report_sha: Optional[str] = None
    mod_flagged_ack_needed: Optional[bool] = None
    mod_settings_groups: Optional[List[str]] = None
    cplug_facts: Optional[Dict[str, Any]] = None
    cplug_facts_sha: Optional[str] = None
    diff: Optional[UpdateDiff] = None


class InstallConsent(BaseModel):
    """What the caller says a person agreed to before a script-bearing install.

    CONSENT IS A RECORDED HUMAN ACT, WHICH IS WHY THIS NAMES BYTES AND
    NOT AN ITEM. An "the user agreed" flag would carry forward onto
    whatever the catalog happens to serve at install time, which is the
    one thing consent must not do. All three fields are compared against
    the copy that actually staged, and a mismatch in any of them is
    refused exactly as an absent consent is.

    Fields:
        digest: the folder digest the sheet showed. It must equal the
            digest of the staged bytes.
        body_sha: sha256 of the ``SKILL.md`` text the user read.
        scripts: the user was shown the script file list and accepted
            that this skill ships executable content. DEFAULTS TO FALSE,
            so a client that omits it has not consented to scripts; there
            is no spelling of this body that unlocks them by accident.
    """

    digest: str
    body_sha: str
    scripts: bool = False
    mod_trust: bool = False
    mod_flagged_ack: bool = False
    mod_report_sha: str = ""
    cplug_accepted: bool = False
    cplug_facts_sha: str = ""


class InstallRequest(BaseModel):
    """The body of both install endpoints.

    Fields:
        item_id: ``<publisher>/<name>``, as the index spells it.
        scope: ``global`` or ``project``. ASKED every time, never
            inferred: where somebody else's code lands is their decision.
        project_path: required for project scope, refused for global.
        choice: the answer to a previous ``name_taken`` refusal.
        plan_token: the staged copy a preview left; absent means fetch
            again, which costs bytes and nothing else.
        consent: required by ``POST /catalog/install`` for an item that
            carries executable content, ignored for one that does not.
            A preview never needs it: the preview is what produces the
            text and the file list the consent is given TO.
    """

    item_id: str
    scope: Literal["global", "project"]
    project_path: Optional[str] = None
    choice: Optional[str] = None
    plan_token: Optional[str] = None
    consent: Optional[InstallConsent] = None
    harnesses: Optional[List[Literal["claude", "codex"]]] = None
    create_roots: bool = False
    one_click: bool = False
    member_consents: Optional[Dict[str, InstallConsent]] = None


class UninstallResponse(BaseModel):
    """``DELETE /catalog/installed/{install_id}``: what was moved aside.

    Fields:
        install_id: the ledger row that was removed.
        trashed: where each installed copy now sits, one absolute path
            per copy. THE TRASH IS THE UNDO, so these are the paths a
            user is told about when they want the folder back.
        missing: copies the ledger recorded that were not on disk any
            more. REPORTED RATHER THAN FATAL: somebody removing a skill
            folder by hand is not a reason to refuse to forget it. An
            empty list is the ordinary case, and it is not the same
            answer as a null.
    """

    install_id: str
    trashed: List[str] = Field(default_factory=list)
    missing: List[str] = Field(default_factory=list)
    removable_members: List[str] = Field(default_factory=list)


class InstalledPatchRequest(BaseModel):
    """``PATCH /catalog/installed/{install_id}``: the settings a row carries.

    Fields:
        auto_update: whether this install may be replaced silently when
            the catalog publishes a new build. REFUSED for a
            project-scope row: see ``auto_update_global_only``.
        expected_revision: the ``revision`` the caller read. A write that
            names a revision the row has moved past is answered 409
            ``stale_revision`` carrying the current row, never applied on
            top of somebody else's change.
    """

    auto_update: bool
    expected_revision: int


class UpdateConsent(BaseModel):
    """What the caller says it showed the user before asking for an update.

    Fields:
        body_sha: sha256 of the ``SKILL.md`` text the user read. It must
            equal the sha of the text in the version being applied; a
            value that does not match is not consent to THAT text, so it
            is refused exactly as an absent one is.
        scripts: the user was shown this version's script file list and
            accepted that it ships executable content. REQUIRED for any
            update to a script-bearing version, including one whose
            ``SKILL.md`` did not change a byte: identical instructions
            say nothing about what the scripts beside them now do, so the
            unchanged-text shortcut does not apply to them.
        digest: the folder digest the sheet showed. REQUIRED for an
            update to a script-bearing version, where it is compared
            against the digest of the copy that actually staged, exactly
            as :class:`InstallConsent` is. OPTIONAL, and not consulted at
            all, for a version without scripts: there the agreement is
            about instructions and the instructions are the thing
            compared. It defaults to None because absent is a refusal on
            the path that reads it, so no spelling of this body agrees to
            a folder by omission.
    """

    body_sha: str
    scripts: bool = False
    digest: Optional[str] = None
    mod_trust: bool = False
    mod_flagged_ack: bool = False
    mod_report_sha: str = ""


class InstalledUpdateRequest(BaseModel):
    """``POST /catalog/installed/{install_id}/update``: apply a new version.

    Fields:
        expected_revision: as above, and checked twice - once before any
            bytes are fetched, and again as the compare-and-swap that
            actually writes the row.
        consent: present when the caller has shown the user the new
            ``SKILL.md`` and they accepted it. Absent means "only proceed
            if the instructions are byte-identical to the ones already
            consented to", which is the safe default and the one an
            automatic caller wants.
    """

    expected_revision: int
    consent: Optional[UpdateConsent] = None
