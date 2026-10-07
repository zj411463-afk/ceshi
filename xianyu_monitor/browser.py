"""Adapter for the site's own browser SDK and visible order form.

Verified against public xy-site/0.0.176 bundles on 2026-10-07.
Authenticated transactions still require real-account acceptance testing.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from .core import (CREATE_API, READ_CHECKOUT_APIS, Item, NeedsAttention,
                   api_name, payment_request, request_item_matches)


def response_data(payload):
    ret = payload.get("ret", []) if isinstance(payload, dict) else []
    if not ret or not str(ret[0]).startswith("SUCCESS::"):
        code = str(ret[0]).split("::")[0] if ret else "INVALID_RESPONSE"
        raise NeedsAttention(f"闲鱼返回 {code}；请检查浏览器中的登录或验证提示")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise NeedsAttention("闲鱼响应结构变化，已暂停")
    return data


def parse_cards(data):
    cards = data.get("cardList")
    if not isinstance(cards, list) or "nextPage" not in data:
        raise NeedsAttention("卖家商品列表结构不匹配，未建立基线，也不会下单")
    items = []
    for entry in cards:
        card = entry.get("cardData", {}) if isinstance(entry, dict) else {}
        item_id, title = str(card.get("id", "")), card.get("title")
        if not item_id.isdigit() or not isinstance(title, str) or not title:
            raise NeedsAttention("列表中存在无法识别的商品，已暂停以避免误判上新")
        info = card.get("priceInfo", {})
        price = "—"
        if isinstance(info, dict):
            price = str(info.get("price", info.get("priceText", "—")))
        items.append(Item(item_id, title, price))
    return items


class BrowserAdapter:
    def __init__(self, profile: Path, channel: str, emit, stopped=lambda: False):
        self.profile, self.channel, self.emit = profile, channel, emit
        self.pw = self.context = self.page = None
        self.checkout = None
        self.armed_item = None
        self.create_sent = False
        self.canonical_seller = None
        self.stopped = stopped

    def open(self):
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        try:
            self.context = self.pw.chromium.launch_persistent_context(
                str(self.profile), channel=self.channel, headless=False,
                viewport={"width": 1280, "height": 900}, locale="zh-CN",
                service_workers="block",
            )
            self.context.set_default_timeout(15_000)
            self.context.route("**/*", self._guard)
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            self.page.goto("https://www.goofish.com/", wait_until="domcontentloaded")
        except Exception:
            self.close()
            raise

    def _guard(self, route):
        request = route.request
        api = api_name(request.url)
        # The guard exists before any page is loaded and also covers popup requests.
        if payment_request(request.url):
            route.abort()
            return
        if api == CREATE_API:
            raw = request.post_data or urlparse(request.url).query
            if (not self.armed_item or self.create_sent
                    or not request_item_matches(raw, self.armed_item)):
                route.abort()
                return
            self.create_sent = True
        elif self.checkout is not None and api and api not in READ_CHECKOUT_APIS:
            # Unknown order/payment APIs are denied, including future renamed ones.
            route.abort()
            return
        route.continue_()

    def _request(self, api, data, page=None):
        page = page or self.page
        body = page.locator("body").inner_text(timeout=5000)
        if "非法访问" in body or "请使用正常浏览器" in body:
            raise NeedsAttention("闲鱼拦截了当前浏览器访问。请停止任务，在普通浏览器或闲鱼 App 中确认账号状态；不会绕过验证")
        page.wait_for_function("() => !!window.lib?.mtop?.request", timeout=20_000)
        payload = page.evaluate("""async ({api, data}) => {
            try {
                return await window.lib.mtop.request({api, v:'1.0',
                    data, type:'GET', dataType:'json', timeout:15000,
                    H5Request:true});
            } catch (error) { return {ret: error.ret || ['REQUEST_FAILED::']}; }
        }""", {"api": api, "data": data})
        return response_data(payload)

    def snapshot(self, seller):
        if self.canonical_seller is None:
            self.page.goto(f"https://www.goofish.com/personal?userId={seller}", wait_until="domcontentloaded")
            head = self._request("mtop.idle.web.user.page.head", {"self": False, "userId": seller})
            canonical = str(head.get("baseInfo", {}).get("kcUserId", ""))
            if not canonical or not canonical.isdigit():
                raise NeedsAttention("卖家身份响应不匹配，请检查主页或重新登录")
            self.canonical_seller = canonical
            self.emit("log", f"卖家主页已连接 · ID {seller}")
        collected, seen, pagination = [], set(), {}
        for number in range(1, 101):
            if self.stopped():
                raise NeedsAttention("监控已停止，未提交订单")
            data = self._request("mtop.idle.web.xyh.item.list", {
                "userId": self.canonical_seller, "pageNumber": number,
                "pageSize": 20, "needGroupInfo": number == 1, **pagination,
            })
            batch = parse_cards(data)
            fresh = [item for item in batch if item.id not in seen]
            collected.extend(fresh)
            seen.update(item.id for item in batch)
            more = data["nextPage"]
            if more in (False, "false", 0):
                return collected
            if more not in (True, "true", 1) or not fresh:
                raise NeedsAttention("商品分页不完整，已暂停；不把不完整列表当作上新基线")
            pagination = {key: data[key] for key in ("nextPageModel", "nextPageNum") if key in data}
        raise NeedsAttention("商品列表超过 100 页，未完整读取，已暂停")

    def order(self, seller, item, stopped):
        if stopped():
            raise NeedsAttention("任务已停止，未提交订单")
        detail = self._request("mtop.taobao.idle.pc.detail", {"itemId": item.id})
        actual = str(detail.get("sellerDO", {}).get("sellerId", ""))
        if actual not in {seller, self.canonical_seller}:
            raise NeedsAttention("商品卖家身份与监控目标不一致，已阻止下单")
        if detail.get("itemDO", {}).get("pcSupportTrade") not in (True, "true"):
            raise NeedsAttention("该商品不支持网页版交易，需要在闲鱼 App 中处理")
        self.checkout = self.context.new_page()
        try:
            self.checkout.goto(f"https://www.goofish.com/create-order?itemId={item.id}", wait_until="domcontentloaded")
            # Only explicit order-submission labels; payment labels are never clicked.
            submit = self.checkout.get_by_text(re.compile(r"^(确认购买|提交订单|确认下单)$"), exact=True)
            submit.first.wait_for(state="visible", timeout=20_000)
            visible = [submit.nth(i) for i in range(submit.count()) if submit.nth(i).is_visible()]
            if len(visible) != 1:
                raise NeedsAttention("未找到唯一的订单提交按钮，请在浏览器核对地址、规格和订单")
            if stopped():
                raise NeedsAttention("任务已停止，未提交订单")
            self.armed_item, self.create_sent = item.id, False
            try:
                with self.checkout.expect_response(lambda response: api_name(response.url) == CREATE_API, timeout=20_000) as pending:
                    visible[0].click(timeout=5000)
                data = response_data(pending.value.json())
            finally:
                self.armed_item = None
            order_id = str(data.get("bizOrderIdStr", ""))
            if not order_id.isdigit():
                raise NeedsAttention("订单接口未返回可识别订单号；请在闲鱼核对，软件不会重复提交")
            return order_id
        finally:
            self.armed_item = None
            # No live order page is left running scripts after the result is read.
            if self.checkout is not None:
                self.checkout.close()
                self.checkout = None

    def pump(self, milliseconds=200):
        self.page.wait_for_timeout(milliseconds)

    def close(self):
        try:
            if self.context:
                self.context.close()
        finally:
            if self.pw:
                self.pw.stop()
            self.context = self.pw = None


class DemoAdapter:
    def __init__(self):
        self.round = 0

    def snapshot(self, seller):
        self.round += 1
        items = [Item("900000001", "演示 · 已有商品（不会拍下）", "128")]
        if self.round >= 3:
            items.append(Item("900000002", "演示 · 新上架的手作木雕", "68"))
        return items

    def order(self, seller, item, stopped):
        return "DEMO-ORDER-0001"
