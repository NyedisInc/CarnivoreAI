
import re
from typing import Optional, Dict, Literal
from pydantic import BaseModel, Field, field_validator

from src.core import terminal_background

_PACK_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class UpdatePinnedThemeRequest(BaseModel):
    """Request body for ``PATCH /sessions/{session_name}/pinned-theme``.

    SESSION-IDENTITY-V2: pin a theme id to a specific tmux session, or
    clear the pin by sending ``null``. The pinned theme overrides the
    user's global localStorage theme whenever the session is active.

    DEPRECATED in v0.7.0: superseded by ``UpdateThemeRequest`` (project-
    scoped via ``<working_dir>/.cc.theme``). This shape is kept for one
    release; the deprecated alias route forwards through to the new code
    path. Will be removed in v0.8.x.
    """
    pinned_theme: Optional[str] = Field(
        None,
        description="Theme id to pin to this session (None/null clears the pin)",
    )


class UpdateThemeRequest(BaseModel):
    """Request body for ``PATCH /sessions/{session_name}/theme`` (v0.7.0+).

    Project-scoped theme persistence: the theme id is written to
    ``<session.working_dir>/.cc.theme`` so two browsers / two machines
    pointed at the same project see the same theme without round-tripping
    a per-machine cache. ``theme_id=None`` or empty deletes the dotfile
    (clears the pin).
    """
    theme_id: Optional[str] = Field(
        None,
        description="Theme id to pin to this project's working dir (None/empty clears)",
    )


class UpdateSessionBackgroundRequest(BaseModel):
    """Request body for ``PATCH /sessions/{session_name}/background``.

    The per-session override of the terminal background image. All three
    fields absent is the request "drop back to whatever my theme ships",
    which removes the session's entry rather than storing an empty one.

    ``theme_id`` NAMES A THEME, NEVER A FILE. The override borrows the
    picture an INSTALLED theme ships, so there is no filename on this
    request at all and no way for a session to address a file in a folder
    that never declared one. That is what keeps the catalog's own name
    check (``ThemeBackgroundManifest``) the single gate on what may be
    painted.

    ``disabled`` is not ``theme_id=None``: a session whose theme ships a
    picture has to be able to say "not here", and absence already means
    "inherit".
    """

    theme_id: Optional[str] = Field(
        None,
        description="Installed theme id whose background image to borrow",
    )
    dim: Optional[float] = Field(
        None,
        description="Scrim fraction 0..1; clamped, not rejected. None inherits.",
    )
    disabled: bool = Field(
        False,
        description="Paint no background image for this session at all",
    )


class SessionBackgroundEntry(BaseModel):
    """One session's stored override, as the API reports it.

    ``image`` NAMES A FILE THIS SERVER WROTE, NEVER ONE A CLIENT NAMED. It
    is the bare filename of an upload stored under the state directory,
    composed by the server from the session's own name and the extension
    it SNIFFED out of the bytes. A client never sends this field: it is
    set by ``PUT .../background/image`` and cleared by the matching
    DELETE, and the file behind it is read back through
    ``GET .../background/image``, never through a path built from this
    string by anyone else.
    """

    theme_id: Optional[str] = Field(None, description="Theme the image comes from")
    dim: Optional[float] = Field(None, description="Scrim fraction, or null to inherit")
    disabled: bool = Field(False, description="This session paints no image")
    image: Optional[str] = Field(
        None,
        description="Bare filename of this session's uploaded image, if any",
    )


class SessionBackgroundsResponse(BaseModel):
    """Every stored per-session override, plus the constants a client needs.

    ONE REQUEST AT BOOT, NOT ONE PER ATTACH. The terminal resolves a
    background every time a session is opened, and this app cares a great
    deal about what the attach path waits on. Handing the whole map over
    once - it is one small object per session the user has ever customised
    - keeps the attach path free of a round trip it would otherwise pay on
    every navigation.
    """

    overrides: Dict[str, SessionBackgroundEntry] = Field(
        default_factory=dict,
        description="tmux session name -> that session's override",
    )
    default_dim: float = Field(
        ...,
        description=(
            "The scrim a theme gets when it names none, and where the "
            "per-session control starts. The palette-derived floor the "
            "client computes may raise it."
        ),
    )


class ThemeBackgroundManifest(BaseModel):
    """The optional `background` block of a theme.json: one image, one scrim.

    THE IMAGE IS A FILE INSIDE THE THEME'S OWN FOLDER (owner, 2026-09-20:
    "image has to be in the theme catelog repo. simple"), so `image` is a
    BARE FILENAME and never a path or a url. `src.core.terminal_background
    .safe_image_filename` is the one place that decides what is acceptable,
    and a theme can be installed from the skills catalog, so that value is
    attacker-controlled text.

    A BAD NAME TAKES THE WHOLE THEME OUT, ON PURPOSE. The validator RAISES
    rather than dropping the field, so `_load_manifest` logs
    `theme_manifest_validation_failed` and skips the theme - the same
    treatment a declared-but-missing `themeCss` already gets. Silently
    ignoring a traversal attempt would leave a package that tried to escape
    its directory sitting in the picker looking exactly like one that did
    not.

    `dim` is CLAMPED and never rejected: a typo in one number must not
    remove a theme from the selector. The clamp here is a sanity bound at
    the trust boundary; the number that actually protects legibility is
    derived from this theme's own palette in
    `client/js/terminal-background.js` and is always the binding one.
    """

    image: str = Field(
        ...,
        description=(
            "Bare filename of an image inside this theme's own directory. "
            "No path, no url, no scheme. Refused values take the theme out "
            "of the picker rather than painting nothing in silence."
        ),
    )
    dim: float = Field(
        terminal_background.DEFAULT_DIM,
        description=(
            "Fraction of the theme's own terminal background painted OVER "
            "the image, 0..1; clamped, not rejected. 0.8 means 80 percent "
            "theme colour and 20 percent picture."
        ),
    )

    @field_validator("image")
    @classmethod
    def _refuse_unsafe_image(cls, v: str) -> str:
        return terminal_background.safe_image_filename(v)

    @field_validator("dim")
    @classmethod
    def _clamp_dim(cls, v: float) -> float:
        return terminal_background.clamp_dim(v)


class ThemeCharactersManifest(BaseModel):
    """The optional `characters` block of a theme.json: which Pack character pack the theme wears.

    The Pack's squares (`web/src/cplugs/huddle/swarm/characters/`, docs/swarm.md
    section 13) render under every theme through `--oc-*` tokens. A theme may
    ALSO name an alternate pack, a different drawing of the same states. `pack`
    is only a NAME, a short lowercase slug the client looks up in its own table
    of built-in packs, so no theme ships drawing code; an unknown name falls
    back to the default pack on the client. Because a theme can be installed
    from the skills catalog the value is attacker-controlled text, and it ends
    up in a DOM data attribute, so a value that is not a plain slug is REFUSED
    here and takes the theme out of the picker, like an unsafe `mascot` name.
    """

    pack: str = Field(
        ...,
        description=(
            "Name of a built-in character pack, a lowercase slug of at most 32 "
            "characters (for example 'pixel'). Unknown names fall back to the "
            "default pack on the client."
        ),
    )

    @field_validator("pack")
    @classmethod
    def _refuse_unsafe_pack(cls, v: str) -> str:
        if len(v) > 32 or not _PACK_SLUG.fullmatch(v):
            raise ValueError("characters.pack must be a lowercase slug of 1 to 32 characters")
        return v


class ThemeManifest(BaseModel):
    """Theme manifest descriptor.

    `id` MUST match the directory name on disk - the discovery code uses the
    dir name as the canonical id and rejects manifests whose `id` field
    disagrees, since otherwise two themes could collide on the same id while
    living in different folders.
    """
    id: str = Field(..., description="Theme id; MUST match the on-disk directory name")
    name: str = Field(..., description="Human-readable display name shown in the selector")
    description: str = Field(..., description="One-line description")
    author: Optional[str] = Field(None, description="Theme author")
    version: Optional[str] = Field(None, description="Theme version (semver-ish)")
    cssVars: Dict[str, str] = Field(
        default_factory=dict,
        description="Map of CSS custom-property name -> value, applied on :root",
    )
    xterm: Dict[str, str] = Field(
        default_factory=dict,
        description="xterm.js theme object (background/foreground/ANSI palette)",
    )
    effects: Optional[str] = Field(
        None,
        description="Optional filename of an effects.js module relative to the theme dir",
    )
    effectsDigest: Optional[str] = Field(
        None,
        description=(
            "Server-stamped sha256 hex of the ``effects`` file's bytes, or "
            "null when the theme declares no script or the file could not be "
            "read. SCRIPT CONSENT IS BOUND TO THIS VALUE: an 'always allow' "
            "records the digest it was granted for, so editing effects.js "
            "revokes the grant instead of inheriting it. A null here is "
            "therefore not a neutral absence - for a user theme that DOES "
            "declare a script it means the bytes could not be named, and "
            "``theme_script_consent.decide`` refuses to run it. Client-supplied "
            "values are ignored; the server overwrites this field on every scan."
        ),
    )
    scriptTrust: Optional[Literal["first_party"]] = Field(
        None,
        description=(
            "Server-stamped. 'first_party' only for an installed theme whose "
            "install record is the owner's signed catalog release and whose "
            "folder still hashes to the signed digest; null for everything "
            "else. A theme.json value is wiped before stamping."
        ),
    )
    themeCss: Optional[str] = Field(
        None,
        description=(
            "Optional filename of a theme.css stylesheet relative to the theme "
            "dir. The client never wires this up to a <link href> - all visual "
            "theming ships through cssVars and effects.js instead, verified "
            "2026-08-19 (removed dead client/css/themes/*/theme.css files and "
            "the unused #theme-css <link> in client/index.html). This field is "
            "kept only so a manifest that still declares one and does not ship "
            "the file fails loudly in _load_manifest instead of the file being "
            "silently dropped by response_model serialization - the same class "
            "of bug that once ate every theme's audio block."
        ),
    )
    background: Optional[ThemeBackgroundManifest] = Field(
        None,
        description=(
            "Optional terminal background image block; absent means the "
            "terminal paints its flat background exactly as before"
        ),
    )
    mascot: Optional[str] = Field(
        None,
        description=(
            "Optional bare filename of a sprite inside this theme's own "
            "directory (svg or a raster type). The terminal pins it over "
            "Claude Code's Clawd; absent means Clawd is left untouched. An "
            "unsafe name takes the theme out of the picker, like a "
            "background image name."
        ),
    )
    characters: Optional[ThemeCharactersManifest] = Field(
        None,
        description=(
            "Optional character pack this theme wears (docs/swarm.md "
            "section 13); absent means the built-in default squares. Declared "
            "here so the response model does not silently drop it."
        ),
    )
    source: Literal["builtin", "user"] = Field(
        ..., description="Where the manifest was discovered - server-stamped"
    )
    feedbackItemId: Optional[str] = Field(
        None,
        description=(
            "The catalog item id this theme can be rated and sent a note "
            "about, or null when it has none. Every bundled theme carries "
            "the reserved id 'bundled/<id>'; a user theme carries the "
            "catalog item id it was installed from when its on-disk folder "
            "still matches that install; a hand-made theme carries null, "
            "meaning it cannot be rated and no note can be sent about it. "
            "SERVER-STAMPED ON EVERY SCAN, the effectsDigest rule: a "
            "hand-written theme.json cannot claim a catalog id it does not "
            "hold."
        ),
    )
    publisher: Optional[str] = Field(
        None,
        description=(
            "The catalog publisher handle this theme was installed from, "
            "or null for a bundled or hand-made theme. A bundled theme is "
            "never shown or linked as though a person published it, so "
            "this stays null even though feedbackItemId is set. "
            "SERVER-STAMPED ON EVERY SCAN, same rule as feedbackItemId."
        ),
    )

    @field_validator("mascot")
    @classmethod
    def _refuse_unsafe_mascot(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return terminal_background.safe_image_filename(
            v, terminal_background.MASCOT_EXTENSIONS
        )
