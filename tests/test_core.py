import json
from datetime import datetime
from urllib.parse import urlencode

import pytest

from xianyu_monitor.browser import BrowserAdapter, parse_cards, response_data
from xianyu_monitor.core import (CREATE_API, Item, Monitor, NeedsAttention, Settings, Store,
                                 api_name, payment_request, request_item_matches, seller_id)


@pytest.mark.parametrize("interval", [0, 0.99, -1, float("nan"), float("inf"), 86401])
def test_interval_rejects_invalid(interval):
    with pytest.raises(ValueError):
        Settings(seller="123", interval=interval).validate()


def test_one_second_and_cross_midnight():
    settings = Settings(seller="123", interval=1, scheduled=True, start="23:00", end="02:00")
    settings.validate()
    assert settings.active_at(datetime(2026, 10, 7, 23, 0))
    assert settings.active_at(datetime(2026, 10, 8, 1, 59))
    assert not settings.active_at(datetime(2026, 10, 8, 2, 0))
    assert not settings.active_at(datetime(2026, 10, 7, 22, 59))


def test_seller_url_is_not_arbitrary_navigation():
    assert seller_id("https://www.goofish.com/personal?userId=2141274515") == "2141274515"
    for value in ["https://evil.test/personal?userId=123", "https://www.goofish.com/item?userId=123", "https://www.goofish.com.evil.test/personal?userId=123"]:
        with pytest.raises(ValueError):
            seller_id(value)


class Adapter:
    def __init__(self):
        self.items = [Item("1", "existing")]
        self.calls = []
        self.fail = False

    def snapshot(self, seller):
        return self.items

    def order(self, seller, item, stopped):
        self.calls.append(item.id)
        if self.fail:
            raise TimeoutError("uncertain server result")
        return "123456"


def monitor(store, adapter, auto=True, stopped=lambda: False):
    return Monitor(Settings(seller="123", auto_order=auto), store, adapter, lambda *args: None, stopped)


def test_baseline_new_once_and_restart(tmp_path):
    path = tmp_path / "store.db"
    store, adapter = Store(path), Adapter()
    task = monitor(store, adapter)
    task.tick()
    assert adapter.calls == []
    adapter.items.append(Item("2", "new"))
    task.tick()
    task.tick()
    assert adapter.calls == ["2"]
    assert store.rows()[0]["order_id"] == "123456"
    store.close()
    store = Store(path)
    task = monitor(store, adapter)
    task.tick()
    task.tick()
    assert adapter.calls == ["2"]
    store.close()


def test_uncertain_order_never_retried(tmp_path):
    store, adapter = Store(tmp_path / "store.db"), Adapter()
    task = monitor(store, adapter)
    task.tick()
    adapter.items.append(Item("2", "new"))
    adapter.fail = True
    with pytest.raises(TimeoutError):
        task.tick()
    assert store.rows()[0]["status"] == "attention"
    adapter.fail = False
    task.tick()
    assert adapter.calls == ["2"]
    store.close()


def test_stop_and_monitor_only_never_create(tmp_path):
    store, adapter = Store(tmp_path / "store.db"), Adapter()
    task = monitor(store, adapter, auto=False)
    task.tick()
    adapter.items.append(Item("2", "new"))
    task.tick()
    assert store.rows()[0]["status"] == "detected"
    assert adapter.calls == []
    task = monitor(store, adapter, stopped=lambda: True)
    task.tick()
    assert adapter.calls == []
    store.close()


def test_durable_claim_survives_crash(tmp_path):
    path = tmp_path / "store.db"
    a, b = Store(path), Store(path)
    item = Item("1", "new")
    assert a.remember("123", item, "attempting")
    assert not b.remember("123", item, "attempting")
    a.close()
    assert b.rows()[0]["status"] == "attempting"
    b.close()


def test_incomplete_snapshot_does_not_arm_monitor(tmp_path):
    store, adapter = Store(tmp_path / "store.db"), Adapter()
    def broken(seller):
        raise NeedsAttention("missing second page")
    adapter.snapshot = broken
    task = monitor(store, adapter)
    with pytest.raises(NeedsAttention):
        task.tick()
    assert not task.ready
    assert store.rows() == []
    store.close()


def test_cutoff_during_snapshot_prevents_order(tmp_path):
    store, adapter = Store(tmp_path / "store.db"), Adapter()
    cutoff = [False]
    task = monitor(store, adapter, stopped=lambda: cutoff[0])
    task.tick()
    def slow_snapshot(seller):
        cutoff[0] = True
        return [Item("1", "existing"), Item("2", "new")]
    adapter.snapshot = slow_snapshot
    task.tick()
    assert not adapter.calls
    assert not store.rows()
    store.close()


def test_strict_response_schema():
    with pytest.raises(NeedsAttention):
        response_data({"ret": ["FAIL_SYS_USER_VALIDATE::login"]})
    for payload in [{}, {"cardList": []}, {"cardList": [{"cardData": {}}], "nextPage": False}]:
        with pytest.raises(NeedsAttention):
            parse_cards(payload)
    assert parse_cards({"cardList": [], "nextPage": False}) == []


@pytest.mark.parametrize("url", [
    "https://m.goofish.com/h5/mtop.order.doPay/4.0/",
    "https://m.goofish.com/?api=mtop.order.dopay",
    "https://m.goofish.com/h5/mtop.idle.trade.pay.info.query/1.0/",
    "https://cashier.alipay.com/checkout",
])
def test_payment_requests_blocked(url):
    assert payment_request(url)


def test_create_payload_requires_correct_item_and_quantity():
    def payload(items):
        return urlencode({"data": json.dumps({"params": json.dumps(items)})})
    assert request_item_matches(payload([{"itemId": "123", "buyQuantity": 1}]), "123")
    for items in [[{"itemId": "456"}], [{"itemId": "123", "buyQuantity": 2}], [{"itemId": "123"}, {"itemId": "123"}]]:
        assert not request_item_matches(payload(items), "123")
    assert not request_item_matches("bad-data", "123")


def test_unknown_checkout_api_and_duplicate_create_are_blocked(tmp_path):
    adapter = BrowserAdapter(tmp_path, "chrome", lambda *args: None)
    class Request:
        url = "https://m.goofish.com/h5/mtop.unknown.payment/1.0/"
        post_data = ""
    class Route:
        request = Request()
        result = None
        def abort(self): self.result = "abort"
        def continue_(self): self.result = "continue"
    route = Route()
    adapter.checkout = object()
    adapter._guard(route)
    assert route.result == "abort"
    route.request.url = f"https://m.goofish.com/h5/{CREATE_API}/5.0/"
    route.request.post_data = urlencode({"data": json.dumps({"params": json.dumps([{"itemId": "123"}])})})
    adapter._guard(route)
    assert route.result == "abort"
    adapter.armed_item = "123"
    adapter._guard(route)
    assert route.result == "continue"
    adapter._guard(route)
    assert route.result == "abort"
