
import pytest

from src.core.session_token_usage.model_table import facts_for_model, estimate_cost_usd
from src.core.stats.pricing import estimate, PRICE_VERSION


@pytest.mark.parametrize("model,rates", [
    ("claude-sonnet-5-5", (2, 2.5, .2, 10)),
    ("gpt-6-astra", (10, 12.5, 1, 50)),
    ("gpt-6-sol", (2, 2.5, .2, 10)),
    ("gpt-6-luna", (.1, .125, .01, .5)),
    ("gpt-5.6-sol", (4, 5, .4, 20)),
])
def test_verified_prices_match_both_readers(model, rates):
    for index, rate in enumerate(rates):
        counts = tuple(1_000_000 if n == index else 0 for n in range(4))
        assert estimate(model, counts) == (round(rate * 1_000_000_000), PRICE_VERSION)
        assert estimate_cost_usd(model, input_tokens=counts[0],
            cache_creation_input_tokens=counts[1], cache_read_input_tokens=counts[2],
            output_tokens=counts[3]) == rate
    assert facts_for_model(model).window_tokens == (1_000_000 if model == "claude-sonnet-5-5" else None)
    assert estimate(model + "-2026-09-29", (1_000_000, 0, 0, 0))[0] == rates[0] * 1_000_000_000


@pytest.mark.parametrize("model", ["gpt-5.6-unknown", "gpt-6-sol-fast", "claude-opus-5-99"])
def test_unknown_variants_never_inherit_an_unrelated_price(model):
    assert facts_for_model(model) is None
    assert estimate(model, (1_000_000, 0, 0, 0)) == (None, None)


def test_cache_heavy_opus_usage_reconciles_to_api_equivalent():
    assert estimate("claude-opus-5-5", (1756, 4143426, 161245997, 1513807)) == (83249493400, PRICE_VERSION)
