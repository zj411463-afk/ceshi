from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, time
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


class NeedsAttention(RuntimeError):
    """Pause until the user resolves an ambiguous or unsupported condition."""


def seller_id(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"[0-9]{1,30}", value):
        return value
    url = urlparse(value)
    if url.scheme != "https" or url.hostname not in {"www.goofish.com", "goofish.com"}:
        raise ValueError("请填写卖家数字 ID 或 https://www.goofish.com/personal?userId=… 主页链接")
    found = parse_qs(url.query).get("userId", [""])[0]
    if url.path.rstrip("/") != "/personal" or not re.fullmatch(r"[0-9]{1,30}", found):
        raise ValueError("链接必须是带 userId 的卖家主页，不能是商品链接或分享短链")
    return found


def resolve_seller(value: str) -> str:
    try:
        return seller_id(value)
    except ValueError:
        pass
    match = re.search(r"https://m\.tb\.cn/[A-Za-z0-9.?=&_%+-]+", value)
    if not match:
        raise ValueError("请粘贴闲鱼卖家分享文字、数字 ID 或网页版卖家主页链接")
    request = Request(match[0], headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=20) as response:
        html = response.read(512_000).decode("utf-8", errors="replace")
    target = re.search(r"https://pages\.goofish\.com/sharexy\?[^'\"\s<>]+", html)
    if not target:
        raise ValueError("分享链接已失效或无法解析，请在浏览器打开后复制卖家主页链接")
    query = parse_qs(urlparse(target[0]).query)
    if query.get("bft") != ["personal"]:
        raise ValueError("这是商品分享链接，请分享卖家的闲鱼号主页")
    return seller_id(query.get("userid", query.get("userId", [""]))[0])


@dataclass(frozen=True)
class Settings:
    seller: str = ""
    interval: float = 5.0
    auto_order: bool = False
    scheduled: bool = False
    start: str = "09:00"
    end: str = "23:00"
    browser: str = "msedge"

    def validate(self):
        seller_id(self.seller)
        if not math.isfinite(self.interval) or not 1 <= self.interval <= 86400:
            raise ValueError("监控间隔须在 1 秒到 86400 秒之间")
        if self.browser not in {"msedge", "chrome"}:
            raise ValueError("请选择 Edge 或 Chrome")
        for value in (self.start, self.end):
            time.fromisoformat(value)
        if self.scheduled and self.start == self.end:
            raise ValueError("开始与结束时间不能相同；全天监控请关闭时段限制")

    def active_at(self, now: datetime) -> bool:
        if not self.scheduled:
            return True
        start, end = time.fromisoformat(self.start), time.fromisoformat(self.end)
        current = now.time()
        return start <= current < end if start < end else current >= start or current < end

    def save(self, path: Path):
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


@dataclass(frozen=True)
class Item:
    id: str
    title: str
    price: str = "—"

    @property
    def url(self):
        return f"https://www.goofish.com/item?id={self.id}"


class Store:
    """One durable claim per item; an uncertain order is never retried."""

    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS items (
                seller TEXT NOT NULL, id TEXT NOT NULL, title TEXT NOT NULL,
                price TEXT NOT NULL, status TEXT NOT NULL, order_id TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '', updated TEXT NOT NULL,
                PRIMARY KEY(seller,id)
            );
        """)

    def remember(self, seller: str, item: Item, status: str) -> bool:
        with self.db:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO items(seller,id,title,price,status,updated) VALUES(?,?,?,?,?,?)",
                (seller, item.id, item.title, item.price, status, datetime.now().isoformat(timespec="seconds")),
            )
        return cur.rowcount == 1

    def baseline(self, seller: str, items: list[Item]):
        for item in items:
            self.remember(seller, item, "baseline")

    def finish(self, seller: str, item: Item, status: str, order_id="", note=""):
        with self.db:
            self.db.execute(
                "UPDATE items SET status=?,order_id=?,note=?,updated=? WHERE seller=? AND id=?",
                (status, order_id, note, datetime.now().isoformat(timespec="seconds"), seller, item.id),
            )

    def rows(self):
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM items WHERE status!='baseline' ORDER BY updated DESC, rowid DESC LIMIT 200"
        )]

    def close(self):
        self.db.close()


class Monitor:
    def __init__(self, settings, store, adapter, emit, stopped):
        self.settings, self.store, self.adapter = settings, store, adapter
        self.emit, self.stopped = emit, stopped
        self.seller = seller_id(settings.seller)
        self.ready = False
        self.cycles = 0

    def tick(self):
        items = self.adapter.snapshot(self.seller)
        if self.stopped():
            return
        self.cycles += 1
        if not self.ready:
            self.store.baseline(self.seller, items)
            self.ready = True
            self.emit("log", f"基线建立：{len(items)} 件已有商品不拍，只处理此后新出现的商品")
        else:
            for item in items:
                if self.stopped():
                    break
                status = "attempting" if self.settings.auto_order else "detected"
                if not self.store.remember(self.seller, item, status):
                    continue
                self.emit("log", f"发现新商品：{item.title} · ¥{item.price}")
                if self.settings.auto_order:
                    try:
                        order_id = self.adapter.order(self.seller, item, self.stopped)
                        if not order_id:
                            raise NeedsAttention("未获取到订单号，请在闲鱼核对订单")
                    except Exception:
                        self.store.finish(self.seller, item, "attention", note="未确认下单结果；请在闲鱼核对，不会自动重试")
                        self.emit("rows", self.store.rows())
                        raise
                    self.store.finish(self.seller, item, "ordered", order_id=str(order_id))
                    self.emit("log", f"已创建订单 {order_id}，未执行付款")
                self.emit("rows", self.store.rows())
        self.emit("cycle", {"cycles": self.cycles, "items": len(items)})


def api_name(url: str) -> str:
    parts = urlparse(url)
    query = parse_qs(parts.query)
    if "api" in query:
        return query["api"][0].lower()
    match = re.search(r"/h5/([^/]+)/", parts.path)
    return match[1].lower() if match else ""


CREATE_API = "mtop.taobao.idle.trade.order.create"
READ_CHECKOUT_APIS = {
    "mtop.taobao.idle.trade.order.render",
    "mtop.taobao.idle.logistic.address.list.query",
    "mtop.idle.web.user.page.nav",
    "mtop.taobao.idle.pc.detail",
    "mtop.taobao.idle.cat.configs",
}


def payment_request(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    api = api_name(url)
    return (host == "alipay.com" or host.endswith(".alipay.com")
            or host == "alipayobjects.com" or host.endswith(".alipayobjects.com")
            or bool(re.search(r"(?:^|\.)(?:dopay|pay|payment)(?:\.|$)", api)))


def request_item_matches(raw: str, item_id: str) -> bool:
    """Validate the site's create-order payload before allowing its single request."""
    try:
        data = json.loads(parse_qs(raw)["data"][0])
        params = json.loads(data["params"]) if isinstance(data["params"], str) else data["params"]
        return (isinstance(params, list) and len(params) == 1
                and str(params[0]["itemId"]) == item_id
                and str(params[0].get("buyQuantity", "1")) == "1")
    except (ValueError, KeyError, TypeError, IndexError):
        return False
