"""直接抓取：给一个 URL，拿到标题/号名/时间/正文，再抽字段。

这是最底层也最可靠的一条路——不依赖任何中间服务，只要 URL 能打开。
"""

from typing import Optional

from .. import extract, fetch
from ..models import Item


def fetch_item(url: str, timeout: int = 30) -> Item:
    headers = {}
    if "mp.weixin.qq.com" in url:
        headers["Referer"] = "https://mp.weixin.qq.com/"
    code, eff, data = fetch.get(url, timeout=timeout, headers=headers)
    if code and code >= 400:
        raise fetch.FetchError(f"HTTP {code}: {url[:80]}")
    page = fetch.decode(data)
    art = extract.parse_article(page)  # 风控页在这里抛 Blocked
    text = art["text"]
    fields = extract.extract_fields(text)
    note = ""
    pp = art["page_price"]
    if not fields["is_free"] and pp["free"] is True:
        fields["is_free"] = True
        fields["prices"] = []
        note = "价格取自页面内嵌数据"
    elif not fields["prices"] and pp["price"]:
        fields["prices"] = [pp["price"]]
    if fields["original_price"] is None and pp["original"]:
        fields["original_price"] = pp["original"]
    return Item(
        url=eff or url,
        title=art["title"],
        account=art["account"],
        published_at=art["published_at"],
        summary=extract.summarize(text, art["title"]),
        text_len=len(text),
        source="direct",
        notes=note,
        **fields,
    )


def try_fetch(url: str, timeout: int = 30) -> tuple:
    """返回 (item|None, 错误信息)。不抛异常，方便 pipeline 汇总失败原因。"""
    try:
        return fetch_item(url, timeout=timeout), None
    except extract.Blocked as e:
        return None, f"被风控拦下（{e}）: {url[:70]}"
    except fetch.FetchError as e:
        return None, f"取页失败: {e} | {url[:70]}"
    except Exception as e:  # noqa: BLE001
        return None, f"解析失败: {type(e).__name__}: {e} | {url[:70]}"
