
from __future__ import annotations

from src.api.attention_routes import router
from src.core.attention.diagnostics import AttentionDiagnostics, ObservationDiagnostic


def test_route_declares_its_response_model() -> None:
    route = next(r for r in router.routes if r.path == "/sessions/attention")
    assert route.response_model is AttentionDiagnostics


def test_wire_fields_are_pinned() -> None:
    assert set(ObservationDiagnostic.model_fields) == {
        "session_id", "age_seconds", "state", "source", "matched_rule",
        "disagreement_reason", "stale", "revision",
    }
