
from typing import Literal, Optional, List
from pydantic import BaseModel, Field




class ProviderModelsResponse(BaseModel):
    """Response for all three provider-model endpoints.

    GET returns the current list unchanged; POST/DELETE return the list
    AFTER the mutation. The client always re-renders from this
    authoritative list rather than optimistically patching its own state.
    """
    models: List[str] = Field(default_factory=list)


class WrapperListResponse(BaseModel):
    """Response for every launch-wrapper endpoint (feat/launch-wrappers).

    Full wrapper objects (script included - never a secret, see
    ``AgentWrapper``'s docstring). The client always re-renders from this
    authoritative list rather than optimistically patching its own state,
    matching the ``ProviderModelsResponse`` convention.

    feat/universal-wrappers - ``families`` carries the serialized family
    registry (see ``src.core.agent_families``) alongside the list, so the
    settings screen can render one group per family, and the launch picker
    can label its groups, WITHOUT hardcoding a family list client-side.
    Shipped on every wrapper response rather than fetched separately
    because the two are always rendered together and a wrapper mutation
    changes a family's ``wrapper_count`` / ``in_use`` state.
    """
    wrappers: List[dict] = Field(default_factory=list)
    families: List[dict] = Field(default_factory=list)


class WrapperExamplesResponse(BaseModel):
    """Response for ``GET /api/v1/agents/wrappers/examples``.

    Offered, never auto-installed - see
    ``src.core.agent_wrappers.EXAMPLE_WRAPPERS``.
    """
    wrappers: List[dict] = Field(default_factory=list)


class ToggleFavoriteCommandRequest(BaseModel):
    """Request body for ``POST /api/v1/config/common-commands/favorite``.

    ONE command per call, with an EXPLICIT desired state rather than a
    "flip it" verb. Two clients (or one client and a stale render) can
    disagree about the current state; a flip would then produce whichever
    result arrived last, while an explicit ``favorite`` is idempotent -
    starring something already starred is a no-op, not an unstar.

    ``model_config`` forbids extra keys, matching
    ``ConfigSettingsUpdateRequest``: a typo'd field must 422 rather than
    be silently ignored while the caller believes it took effect.
    """
    model_config = {"extra": "forbid"}

    command: str = Field(..., description="Command to toggle, with or without a leading slash")
    favorite: bool = Field(..., description="True to star, False to unstar")


class SetFavoriteColorRequest(BaseModel):
    """Request body for ``POST /api/v1/config/common-commands/color``.

    ``color`` is REQUIRED and may be null: null takes the colour off, and
    making the field required means a typo'd key 422s instead of reading
    as an absent value that silently clears one. The ids are the swatch
    set in ``src.core.slash_favorites.FAVORITE_COLORS``, each naming an
    ``--oc-*`` palette token.
    """
    model_config = {"extra": "forbid"}

    command: str = Field(..., description="Favorite to mark, with or without a leading slash")
    color: Optional[Literal["yellow", "green", "cyan", "violet", "coral"]] = Field(
        ..., description="Swatch id, or null for no colour"
    )


class ReorderFavoritesRequest(BaseModel):
    """Request body for ``POST /api/v1/config/common-commands/order``.

    The COMPLETE new order. The server refuses with 409 unless it names
    exactly the stored favorites, so a reorder drawn from a stale view can
    never drop or resurrect one. The bound is
    ``src.core.slash_favorites.MAX_FAVORITES``, restated because a model
    must not import the core.
    """
    model_config = {"extra": "forbid"}

    commands: List[str] = Field(..., max_length=40, description="Every favorite, in the wanted order")


class AddProviderModelRequest(BaseModel):
    """Request body for ``POST /api/v1/providers/models``.

    ``model`` format is validated in the route handler (not a pydantic
    field_validator here) so a malformed id returns a precise 400 with a
    clear message - matching the explicit REST contract (400 invalid
    format, 409 duplicate) - rather than FastAPI's generic 422 body.
    """
    model: str = Field(
        ..., description="OpenRouter model id to add, e.g. 'openai/gpt-5.6-sol'"
    )


class LocalModelsResponse(BaseModel):
    """Response for ``GET /api/v1/providers/local/models``.

    ALWAYS 200. An LM Studio box that is off is not an API error - it is a
    STATE the picker has to render, and a 502 would make the client guess
    at the difference between "the server is down" and "your local box is
    down". Branch on ``state``, not on ``reachable``: the boolean is False
    for both ``unreachable`` and ``not-configured``, which mean opposite
    things to the person reading the screen. One says go check the machine;
    the other says go set the address.
    """
    state: str = "not-configured"
    reachable: bool = False
    host: str = ""
    models: List[str] = Field(default_factory=list)
    detail: Optional[str] = None
