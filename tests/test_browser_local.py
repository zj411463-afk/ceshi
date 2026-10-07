"""Real browser, local fixture only: no external account or actual orders."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

from xianyu_monitor.browser import BrowserAdapter
from xianyu_monitor.core import CREATE_API, Item


def test_order_response_and_payment_guard_in_real_browser(tmp_path, monkeypatch):
    hits = []
    payload = urlencode({"data": json.dumps({"params": json.dumps([{"itemId": "123", "buyQuantity": 1}])})})

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(("""<!doctype html><meta charset='utf-8'><button id='submit'>确认购买</button>
                <script>document.querySelector('button').onclick=async()=>{
                    await fetch('/h5/mtop.taobao.idle.trade.order.create/5.0/',
                        {method:'POST',body:PAYLOAD});
                    await fetch('/h5/mtop.order.dopay/4.0/',{method:'POST'}).catch(()=>{});
                };</script>""").replace("PAYLOAD", json.dumps(payload)).encode())

        def do_POST(self):
            hits.append(self.path)
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ret": ["SUCCESS::ok"], "data": {"bizOrderIdStr": "987654321"}}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge" if os.name == "nt" else "chrome", headless=True)
            context = browser.new_context(service_workers="block")
            adapter = BrowserAdapter(tmp_path, "chrome", lambda *args: None)
            adapter.context = context
            adapter.canonical_seller = "456"
            context.route("**/*", adapter._guard)
            new_page = context.new_page

            def checkout_page():
                page = new_page()
                goto = page.goto
                def local_goto(url, **kwargs):
                    assert url == "https://www.goofish.com/create-order?itemId=123"
                    return goto(base, **kwargs)
                monkeypatch.setattr(page, "goto", local_goto)
                return page

            monkeypatch.setattr(context, "new_page", checkout_page)
            monkeypatch.setattr(adapter, "_request", lambda *args: {
                "sellerDO": {"sellerId": "456"}, "itemDO": {"pcSupportTrade": True}})
            assert adapter.order("456", Item("123", "fixture"), lambda: False) == "987654321"
            assert adapter.armed_item is None
            assert adapter.checkout is None
            assert hits == [f"/h5/{CREATE_API}/5.0/"]

            page = new_page()
            page.goto(base)
            # Explicitly issue payment requests independently of page closing timing.
            results = page.evaluate("""async () => Promise.all([
                '/h5/mtop.order.dopay/4.0/', '/h5/mtop.taobao.idle.trade.order.create/5.0/'
            ].map(url => fetch(url,{method:'POST'}).then(()=> 'allowed').catch(()=> 'blocked')))""")
            assert results == ["blocked", "blocked"]
            assert hits == [f"/h5/{CREATE_API}/5.0/"]
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
