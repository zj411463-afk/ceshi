from io import BytesIO

import pytest

from xianyu_monitor import core


def test_resolve_pasted_seller_share(monkeypatch):
    html = b"var url = 'https://pages.goofish.com/sharexy?userid=2141274515&bft=personal';"
    monkeypatch.setattr(core, "urlopen", lambda *a, **k: BytesIO(html))
    assert core.resolve_seller("【闲鱼】https://m.tb.cn/h.example?tk=sample 卖家的闲鱼号") == "2141274515"


def test_item_share_not_accepted_as_seller(monkeypatch):
    html = b"var url = 'https://pages.goofish.com/sharexy?userid=123&bft=item';"
    monkeypatch.setattr(core, "urlopen", lambda *a, **k: BytesIO(html))
    with pytest.raises(ValueError):
        core.resolve_seller("https://m.tb.cn/h.example")
