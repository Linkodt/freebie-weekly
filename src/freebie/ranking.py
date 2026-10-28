"""打分：让人一眼看到「最该去的那几条」排在前面。

分数是人写的规则，不是模型猜的——因为排序错了用户会骂「这破清单」，而规则可以被改。
"""

import time
from typing import List

from .models import Item


def _soonest_day_offset(item: Item, now: time.struct_time) -> int:
    """把 date_hints 里的 10.31 这类线索换成「距今几天」。取最近的。"""
    best = 999
    for h in item.date_hints:
        parts = h.replace("月", ".").replace("日", "").replace("-", ".").split(".")
        try:
            month = int(parts[0])
            day = int(parts[1])
        except (IndexError, ValueError):
            continue
        # 粗略判断跨年：月份比当前小很多，按明年算
        year = now.tm_year + (1 if month < now.tm_mon - 6 else 0)
        try:
            target = time.mktime((year, month, day, 12, 0, 0, 0, 0, -1))
        except (ValueError, OverflowError):
            continue
        delta = int((target - time.mktime(now)) // 86400)
        if -1 <= delta < best:
            best = max(0, delta)
    return best


def score(item: Item, now: time.struct_time = None) -> float:
    now = now or time.localtime()
    s = 0.0
    if item.is_free:
        s += 40
    elif item.prices and item.min_price is not None and item.min_price <= 80:
        s += 15
        if item.original_price and item.original_price > item.min_price:
            drop = 1 - item.min_price / item.original_price
            s += min(25.0, drop * 40)  # 折得越狠分越高，最多 25
    if item.original_price and item.min_price and item.original_price > item.min_price:
        s += 8
    offset = _soonest_day_offset(item, now)
    if offset <= 2:
        s += 20
    elif offset <= 7:
        s += 14
    elif offset <= 14:
        s += 6
    if item.needs_booking:
        s += 6  # 要预约 = 有时限，不能拖
    if item.text_len > 1500:
        s += 5
    if item.deadline:
        s += 4
    return round(s, 1)


def rank(items: List[Item], now: time.struct_time = None) -> List[Item]:
    now = now or time.localtime()
    for it in items:
        it.score = score(it, now)
        if not it.tags:
            it.tags = _tags(it)
    return sorted(items, key=lambda x: (-x.score, -x.published_at))


def _tags(item: Item) -> List[str]:
    t = []
    if item.is_free:
        t.append("免费")
    elif item.min_price is not None:
        t.append(f"¥{_fmt(item.min_price)}")
    if item.original_price and item.min_price and item.original_price > item.min_price:
        t.append(f"原价¥{_fmt(item.original_price)}")
    if item.needs_booking:
        t.append("需预约")
    if item.deadline:
        t.append("有时限")
    return t


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.1f}"
