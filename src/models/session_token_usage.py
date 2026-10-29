
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from src.models.provider_ledger import AccountUsage

TokenUsageState = Literal["ok", "absent", "unchecked"]

TokenUsageFamily = Literal["claude", "codex"]


class SessionTokenUsage(BaseModel):
    """Token spend and context headroom for one session.

    Description: the response of
      ``GET /api/v1/sessions/{session_id}/token-usage``. The five token
      counts are DISJOINT - ``input_tokens`` is fresh input only, with
      cached and cache-written tokens split into their own fields - so
      ``total_tokens`` is exactly their sum in both families. Both
      readers normalise to that shape.
    Inputs: n/a (a response model).
    Output: n/a.
    Example: SessionTokenUsage(state="absent", family="claude")
    """

    state: TokenUsageState = Field(
        ...,
        description=(
            "ok: a transcript was read. absent: there is no transcript or "
            "conversation id yet. unchecked: could not determine. Never "
            "collapse the last two."
        ),
    )
    family: Optional[TokenUsageFamily] = Field(
        None, description="The harness family whose store was read, when known."
    )
    model: Optional[str] = Field(
        None,
        description=(
            "The most recent per-message model id seen in the transcript. "
            "None when no message named one."
        ),
    )
    model_display_name: Optional[str] = Field(
        None,
        description=(
            "The vendor's own product name for `model`, for example "
            "'Opus 5'. None when the price table does not carry the "
            "model, in which case the client prints the raw id verbatim "
            "rather than a prettier guess."
        ),
    )
    model_cost_tier: Optional[int] = Field(
        None,
        ge=1,
        le=5,
        description=(
            "How expensive `model` is, 1 cheapest to 5 priciest, derived "
            "from its published OUTPUT price per million tokens. None "
            "when the model is not in the price table, and the client "
            "then prints the model with no tint. A CLOSED SCALE: the "
            "client's colour ramp has exactly five stops."
        ),
    )

    effort: Optional[str] = Field(
        None,
        description=(
            "The reasoning effort the most recent turn ran at, verbatim "
            "from the harness. None when no record named one, which is a "
            "harness that does not write it as much as a turn that has "
            "not happened - both are 'could not be determined' and "
            "neither is a default worth inventing."
        ),
    )

    input_tokens: Optional[int] = Field(
        None, description="Fresh (uncached) input tokens. Null unless state is ok."
    )
    output_tokens: Optional[int] = Field(
        None, description="Output tokens, reasoning included. Null unless state is ok."
    )
    cache_read_input_tokens: Optional[int] = Field(
        None, description="Input tokens served from cache. Null unless state is ok."
    )
    cache_creation_input_tokens: Optional[int] = Field(
        None, description="Input tokens written to cache. Null unless state is ok."
    )
    total_tokens: Optional[int] = Field(
        None, description="The sum of the four counts above. Null unless state is ok."
    )

    cost_estimate_usd: Optional[float] = Field(
        None,
        description=(
            "An ESTIMATE in US dollars from published list prices. Null "
            "when the model is not in the price table, which is a refusal "
            "to guess rather than a free session."
        ),
    )

    context_used_tokens: Optional[int] = Field(
        None,
        description=(
            "The prompt size of the LAST turn, which is what the next turn "
            "starts from. Not the session total."
        ),
    )
    context_window_tokens: Optional[int] = Field(
        None,
        description=(
            "The model's context window. Read from the transcript when it "
            "records one, else from the price table, else null."
        ),
    )
    context_remaining_pct: Optional[float] = Field(
        None,
        description=(
            "Percent of the window still free, 0 to 100, one decimal. Null "
            "when the window is unknown - an unknown window must never be "
            "drawn as a full or an empty bar."
        ),
    )

    as_of: str = Field(
        ...,
        description="When this was measured. ISO 8601 with a zone marker.",
    )
    detail: Optional[str] = Field(
        None,
        description=(
            "A plain sentence naming why, for the two states that are not "
            "ok. Written to be shown to a user verbatim. Carries no path."
        ),
    )

    account: Optional[AccountUsage] = Field(
        None,
        description=(
            "The provider account this session spends from, as the ledger "
            "last measured it, with its usage windows. A DIFFERENT SCOPE "
            "from every other field here: the counts above are this one "
            "conversation's, read from its transcript, while this row is "
            "the whole ACCOUNT's and is shared by every session running "
            "under the same login. None means the account could not be "
            "determined, never that the account has no limits. See "
            "src/core/session_token_usage/account_resolve.py for why it "
            "has to be deduced at all."
        ),
    )
