
from __future__ import annotations

import pytest

from src.cplugs.publicboard.edge import EdgeConfig, PublicEdge
from tests.python.cplugs.publicboard.corpus import Case, all_cases, judge, run_corpus, untrusted_peer_cases
from tests.python.cplugs.publicboard.harness import HOST, LEAK, ServerThread, edge_for, exchange
from tests.python.cplugs.publicboard.loosened import LOOSENINGS

CASES = all_cases()


@pytest.fixture(scope="module")
def canary_port():
    with ServerThread(edge_for()) as server:
        yield server.port


@pytest.fixture(scope="module")
def stranger_port():
    with ServerThread(edge_for(peers=("203.0.113.11",))) as server:
        yield server.port


@pytest.fixture(scope="module")
def production_port():
    with ServerThread(PublicEdge(EdgeConfig.of(["127.0.0.1"], [HOST]))) as server:
        yield server.port


def test_the_corpus_is_big_enough_to_mean_something() -> None:
    assert len(CASES) >= 100, len(CASES)
    assert len({c.name for c in CASES}) == len(CASES), "case names are unique"
    assert len(untrusted_peer_cases()) >= 6


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_every_bypass_attempt_is_refused_on_a_real_socket(canary_port: int, case: Case) -> None:
    assert judge(case, exchange(canary_port, case.raw)) == []


def test_the_controls_do_reach_the_handler(canary_port: int) -> None:
    get = exchange(canary_port, CASES[0].raw)
    assert get.status == 200 and LEAK in get.body
    assert any(c.name.startswith("post good") for c in CASES)


def test_the_whole_corpus_is_green_and_every_404_is_identical(canary_port: int) -> None:
    assert run_corpus(canary_port) == []


@pytest.mark.parametrize("case", untrusted_peer_cases(), ids=[c.name for c in untrusted_peer_cases()])
def test_a_peer_that_is_not_a_trusted_proxy_gets_a_403_for_everything(stranger_port: int, case: Case) -> None:
    assert judge(case, exchange(stranger_port, case.raw)) == []


def test_production_wiring_answers_404_to_everything_that_passes_the_rules(production_port: int) -> None:
    seen = set()
    for case in CASES:
        reply = exchange(production_port, case.raw)
        assert reply.status != 200 and reply.status != 101, (case.name, reply.status)
        assert LEAK not in reply.body
        if case.allowed == {200}:
            assert reply.status == 404, (case.name, reply.status)
        if reply.status == 404:
            seen.add(reply.signature())
    assert len(seen) == 1, "one 404 shape for the whole run"


SLOW = 1.0


def test_the_whole_corpus_includes_the_slow_client_check() -> None:
    with ServerThread(edge_for(), deadline=SLOW) as server:
        assert run_corpus(server.port, slow_deadline=SLOW) == []


@pytest.mark.parametrize("name", sorted(LOOSENINGS))
def test_a_loosened_edge_turns_the_corpus_red_on_the_named_case(name: str) -> None:
    loosening = LOOSENINGS[name]
    with loosening.apply():
        with ServerThread(edge_for(), deadline=SLOW) as server:
            chosen = None if loosening.only is None else [c for c in CASES if c.name in loosening.only]
            failures = run_corpus(server.port, chosen, slow_deadline=SLOW if loosening.slow else None)
        if loosening.only is None:
            with ServerThread(edge_for(peers=("203.0.113.11",)), deadline=SLOW) as server:
                failures += run_corpus(server.port, untrusted_peer_cases())
    caught = [f for f in failures if f.startswith(loosening.catches + ":")]
    assert caught, f"{name}: expected a failure from {loosening.catches!r}; got {[f[:80] for f in failures[:4]]}"
    print(f"RED [{name}] caught by [{loosening.catches}]: {caught[0]}  ({len(failures)} failing in all)")
