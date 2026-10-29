
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from tests.helpers import hosted_catalog_fake as fake
from tests.helpers import submissions_harness as h

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
YESTERDAY = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

ITEM = "example-owner/work"

UNKNOWN_ITEM = "example-owner/neverpublished"


@pytest.fixture(scope="module")
def api():
    with fake.lambda_modules(h.JWT_TEST_SECRET) as namespace:
        fake.seed_index(namespace, {ITEM})
        yield namespace


@pytest.fixture(autouse=True)
def clean(api):
    h.reset(api)


def _table(api, name):
    table = api.tables.setdefault(name, fake.FakeTable(name, api.log))
    api.store._resources[name] = table
    return table


def _report(api, item=ITEM, version="1.0.0", bearer=None, body=None):
    payload = body if body is not None else json.dumps({"version": version})
    return api.app.handler(
        h.event(
            "POST",
            f"/v1/items/{item}/installed",
            payload,
            h.token(api) if bearer is None else bearer,
        )
    )


def _summary(api, item=ITEM):
    return api.app.handler(h.event("GET", f"/v1/items/{item}/installs"))


def _writes(api):
    return [
        entry
        for entry in api.log
        if entry[0] == "s3" or entry[1] in ("put_item", "update_item", "delete_item")
    ]




def test_the_positive_control_a_good_report_is_counted(api):
    response = _report(api)
    assert response["statusCode"] == 200, h.body_of(response)
    body = h.body_of(response)
    assert body["counted"] is True
    assert body["count"] == 1
    assert body["by_version"] == {"1.0.0": 1}
    assert body["item_id"] == ITEM
    stored = _table(api, api.store.ITEMS_TABLE).stored({"item_id": ITEM})
    assert stored["install_count"] == 1
    assert stored["iv_1.0.0"] == 1




def test_an_unsigned_report_is_refused_before_anything(api):
    response = api.app.handler(
        h.event("POST", f"/v1/items/{ITEM}/installed", json.dumps({"version": "1.0.0"}))
    )
    assert response["statusCode"] == 401
    assert h.body_of(response)["code"] == "unauthorized"
    assert api.log == []


def test_a_forged_token_is_refused_before_any_table_is_touched(api):
    good = h.token(api)
    response = _report(api, bearer=good[:-4] + "aaaa")
    assert response["statusCode"] == 401
    assert api.log == []


def test_reading_the_count_needs_no_token_at_all(api):
    assert _report(api)["statusCode"] == 200
    assert _summary(api)["statusCode"] == 200




def test_an_unknown_item_is_refused_before_any_table_write(api):
    response = _report(api, item=UNKNOWN_ITEM)
    assert response["statusCode"] == 404
    assert h.body_of(response)["code"] == "unknown_item"
    assert h.storage_calls(api) == [], api.log


def test_the_public_summary_refuses_an_unknown_item_too(api):
    response = _summary(api, item=UNKNOWN_ITEM)
    assert response["statusCode"] == 404
    assert h.body_of(response)["code"] == "unknown_item"
    assert api.log == []


def test_a_bad_item_id_never_becomes_a_table_key(api):
    response = _report(api, item="UPPER/CASE")
    assert response["statusCode"] == 400
    assert h.body_of(response)["code"] == "bad_item_id"
    assert api.log == []




@pytest.mark.parametrize("version", [
    "not-a-version",
    "",
    "1.0.0.0.0",
    "../1.0.0",
    "1.0.0 OR 1=1",
    None,
    5,
    {"version": "1.0.0"},
])
def test_a_malformed_version_is_refused_and_stores_nothing(api, version):
    response = _report(api, body=json.dumps({"version": version}))
    assert response["statusCode"] == 400, h.body_of(response)
    assert h.body_of(response)["code"] == "bad_version"
    assert _writes(api) == [], api.log


def test_a_missing_version_is_refused_rather_than_defaulted(api):
    response = _report(api, body=json.dumps({}))
    assert response["statusCode"] == 400
    assert h.body_of(response)["code"] == "bad_version"
    assert _writes(api) == []


def test_the_version_grammar_is_the_submission_one_not_a_second_copy(api):
    assert api.installs.VERSION_PATTERN == api.validate_upload.VERSION_RE.pattern




def test_reporting_the_same_install_twice_counts_it_once(api):
    first = _report(api)
    assert h.body_of(first)["counted"] is True
    assert h.body_of(first)["count"] == 1

    second = _report(api)
    assert second["statusCode"] == 200, h.body_of(second)
    assert h.body_of(second)["counted"] is False
    assert h.body_of(second)["count"] == 1
    assert h.body_of(second)["by_version"] == {"1.0.0": 1}
    stored = _table(api, api.store.ITEMS_TABLE).stored({"item_id": ITEM})
    assert stored["install_count"] == 1


def test_the_second_report_moves_no_aggregate_at_all(api):
    assert _report(api)["statusCode"] == 200
    api.log.clear()
    assert _report(api)["statusCode"] == 200
    adds = [
        entry
        for entry in api.log
        if entry[0] == api.store.ITEMS_TABLE
        and entry[1] == "update_item"
        and entry[2].get("UpdateExpression", "").startswith("ADD")
    ]
    assert adds == [], api.log


def test_a_new_version_by_the_same_account_is_a_new_install(api):
    assert _report(api, version="1.0.0")["statusCode"] == 200
    body = h.body_of(_report(api, version="1.1.0"))
    assert body["counted"] is True
    assert body["count"] == 2
    assert body["by_version"] == {"1.0.0": 1, "1.1.0": 1}


def test_two_accounts_reporting_the_same_version_both_count(api):
    assert _report(api)["statusCode"] == 200
    body = h.body_of(_report(api, bearer=h.token(api, "999", "someoneelse")))
    assert body["counted"] is True
    assert body["count"] == 2
    assert body["by_version"] == {"1.0.0": 2}




def test_the_fifty_first_report_in_a_day_is_refused_and_counts_nothing(api):
    _table(api, api.store.USERS_TABLE).seed(
        {"user_id": h.OTHER_ID},
        {"installs_day": TODAY, "installs_today": api.store.INSTALL_LIMIT},
    )
    response = _report(api)
    assert response["statusCode"] == 429
    assert h.body_of(response)["code"] == "rate_limited"
    assert _table(api, api.store.ITEMS_TABLE).stored({"item_id": ITEM}) == {}


def test_a_rate_limited_report_records_no_install_row(api):
    _table(api, api.store.USERS_TABLE).seed(
        {"user_id": h.OTHER_ID},
        {"installs_day": TODAY, "installs_today": api.store.INSTALL_LIMIT},
    )
    _report(api)
    installs_table = _table(api, api.store.INSTALLS_TABLE)
    assert installs_table.items == {}


def test_yesterdays_install_counter_is_reset_rather_than_refused(api):
    users = _table(api, api.store.USERS_TABLE)
    users.seed(
        {"user_id": h.OTHER_ID},
        {"installs_day": YESTERDAY, "installs_today": api.store.INSTALL_LIMIT},
    )
    assert _report(api)["statusCode"] == 200
    stored = users.stored({"user_id": h.OTHER_ID})
    assert stored["installs_day"] == TODAY
    assert stored["installs_today"] == 1


def test_the_install_counter_is_separate_from_votes_and_submissions(api):
    _table(api, api.store.USERS_TABLE).seed(
        {"user_id": h.OTHER_ID},
        {
            "votes_day": TODAY, "votes_today": 50,
            "submissions_day": TODAY, "submissions_today": 5,
        },
    )
    assert _report(api)["statusCode"] == 200


def test_a_refused_conditional_write_becomes_a_429_not_a_500(api, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise api.store.RateLimited("the daily limit is reached")

    monkeypatch.setattr(api.store, "claim_install", refuse)
    response = _report(api)
    assert response["statusCode"] == 429
    assert h.body_of(response)["code"] == "rate_limited"




def test_the_public_summary_carries_count_and_by_version(api):
    assert _report(api, version="1.0.0")["statusCode"] == 200
    assert _report(api, version="2.0.0", bearer=h.token(api, "999", "other"))[
        "statusCode"
    ] == 200
    response = _summary(api)
    assert response["statusCode"] == 200
    body = h.body_of(response)
    assert body["count"] == 2
    assert body["by_version"] == {"1.0.0": 1, "2.0.0": 1}
    assert body["item_id"] == ITEM


def test_an_item_nobody_installed_summarises_as_zero(api):
    body = h.body_of(_summary(api))
    assert body["count"] == 0
    assert body["by_version"] == {}


def test_the_summary_reads_one_row_and_never_the_records(api):
    assert _report(api)["statusCode"] == 200
    api.log.clear()
    assert _summary(api)["statusCode"] == 200
    assert [entry[0] for entry in api.log] == [api.store.ITEMS_TABLE]
    assert [entry[1] for entry in api.log] == ["get_item"]


def test_the_ratings_totals_are_not_disturbed_by_an_install(api):
    good = h.token(api)
    assert _report(api)["statusCode"] == 200
    assert api.app.handler(
        h.event("PUT", f"/v1/items/{ITEM}/rating", json.dumps({"stars": 5}), good)
    )["statusCode"] == 200
    assert _report(api)["statusCode"] == 200
    row = _table(api, api.store.ITEMS_TABLE).stored({"item_id": ITEM})
    assert row["rating_count"] == 1
    assert row["rating_sum"] == 5
    assert row["install_count"] == 1
    ratings = h.body_of(
        api.app.handler(h.event("GET", f"/v1/items/{ITEM}/ratings"))
    )
    assert ratings["count"] == 1
    assert "install_count" not in ratings




def test_no_endpoint_ever_returns_an_install_record(api):
    assert _report(api, bearer=h.token(api, "4242", "someperson"))["statusCode"] == 200
    for response in (_report(api, bearer=h.token(api, "4242", "someperson")),
                     _summary(api)):
        text = response["body"]
        assert "4242" not in text, text
        assert "someperson" not in text, text
        assert "reported_at" not in text, text
        assert "expires_at" not in text, text


def test_the_record_holds_four_fields_and_never_expires(api):
    assert _report(api)["statusCode"] == 200
    table = _table(api, api.store.INSTALLS_TABLE)
    row = table.stored({"user_id": h.OTHER_ID, "install_key": f"{ITEM}#1.0.0"})
    assert set(row) == {"user_id", "install_key", "reported_at", "acct_kind"}
    assert row["acct_kind"] == "account"



SECOND = "example-owner/second"


def _batch(api, ids, raw=None):
    payload = raw if raw is not None else json.dumps({"ids": ids})
    return api.app.handler(h.event("POST", "/v1/install-counts", payload))


def test_batch_counts_known_items_leaves_out_unknown_and_dedupes(api):
    fake.seed_index(api, {ITEM, SECOND})
    table = _table(api, api.store.ITEMS_TABLE)
    table.seed({"item_id": ITEM}, {"install_count": 3, "iv_1.0.0": 2, "iv_1.1.0": 1})
    api.log.clear()
    response = _batch(api, [ITEM, SECOND, UNKNOWN_ITEM, ITEM])
    assert response["statusCode"] == 200, h.body_of(response)
    assert h.body_of(response) == {"items": {
        ITEM: {"count": 3, "by_version": {"1.0.0": 2, "1.1.0": 1}},
        SECOND: {"count": 0, "by_version": {}},
    }}
    assert h.body_of(_summary(api))["count"] == 3
    assert [e for e in api.log if e[1] == "batch_get_item"] != []
    fake.seed_index(api, {ITEM})


@pytest.mark.parametrize("ids", [[], [f"example-owner/n{i}" for i in range(201)], ["Bad Id"], "a/b", None, [5]])
def test_batch_refuses_a_bad_list_with_400(api, ids):
    api.log.clear()
    assert _batch(api, ids)["statusCode"] == 400
    assert [e for e in api.log if e[1] == "batch_get_item"] == []


def test_batch_unprocessed_keys_are_left_out(api):
    api.dynamodb.hold_back(api.store.ITEMS_TABLE, 1, api.store.BATCH_READ_ATTEMPTS)
    response = _batch(api, [ITEM])
    assert response["statusCode"] == 200
    assert h.body_of(response) == {"items": {}}


def test_the_install_counts_gate_exemption_is_exactly_the_post_of_that_path(api):
    for gate in (api.registration_gate.is_allowed, api.guest_gate.allowed):
        assert gate("POST", "/v1/install-counts")
        assert not gate("POST", "/v1/install-counts/x")
        assert not gate("PUT", "/v1/install-counts")
        assert not gate("DELETE", "/v1/install-counts")
