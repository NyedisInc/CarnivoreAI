
from src.core.web_push.double_delivery import doubled_subscriptions

NATIVE = [{"device_id": "app1", "platform": "ios"}]


def test_marks_same_device_or_same_iphone_label_and_never_the_mac_or_a_generic_phone():
    subs = [
        {"id": "same", "device_id": "app1"},
        {"id": "pwa", "device_id": "pwa1"},
        {"id": "mac", "device_id": None},
        {"id": "other", "device_id": "andr1"},
        {"id": "generic", "device_id": "gen1"},
    ]
    labels = {"app1": "iphone", "pwa1": "iphone", "andr1": "android", "gen1": "phone"}
    assert doubled_subscriptions(subs, NATIVE, labels) == {"same", "pwa"}
    assert doubled_subscriptions(subs, [], labels) == set()
    assert doubled_subscriptions(subs, [{"device_id": "gen1", "platform": "ios"}], {"gen1": "phone"}) == {"generic"}
