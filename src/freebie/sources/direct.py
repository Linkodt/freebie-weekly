"""直接抓取：给一个 URL，拿到标题/号名/时间/正文，再抽字段。

这是最底层也最可靠的一条路——不依赖任何中间服务，只要 URL 能打开。
"""

from typing import List, Optional

from .. import extract, fetch
from ..models import Item

# 汇总页拆出来的单场活动，正文只有一两百字；页面本身已过长文校验，
# 所以这里不拿块长度去卡 min_text_len（否则一页十几场会被全部按「正文太短」丢掉）。
SPLIT_TEXT_FLOOR = 400


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
        raw_text=text,
        **fields,
    )


def _from_event(page: Item, ev: dict, idx: int) -> Item:
    block_len = len(ev["when"]) + len(ev["venue"]) + len(ev["summary"]) + 12
    return Item(
        url=f"{page.url}#{idx}",  # 去重键靠 URL，加序号才不会和整页那条撞
        title=ev["title"],
        account=page.account,
        published_at=page.published_at,
        summary=ev["summary"],
        is_free=ev["is_free"],
        prices=ev["prices"],
        original_price=None,
        needs_booking=ev["fields"]["needs_booking"],
        deadline=ev["fields"]["deadline"],
        date_hints=ev["fields"]["date_hints"],
        venue=ev["venue"],
        text_len=max(block_len, SPLIT_TEXT_FLOOR),
        source=page.source,
        notes="汇总页拆分",
    )


def expand(item: Item) -> List[Item]:
    """一页多场就拆成多条；拆不出来原样返回一条。"""
    evs = extract.roundup_events(item.raw_text)
    if len(evs) < 2:
        return [item]
    return [_from_event(item, ev, i + 1) for i, ev in enumerate(evs)]


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


def try_fetch_all(url: str, timeout: int = 30) -> tuple:
    """同 try_fetch，但会把汇总页展开成多条。返回 (items, 错误信息)。"""
    item, err = try_fetch(url, timeout=timeout)
    if err or item is None:
        return [], err
    try:
        return expand(item), None
    except Exception as e:  # noqa: BLE001
        return [item], f"汇总页拆分失败（已按整页收录）: {type(e).__name__}: {e}"
