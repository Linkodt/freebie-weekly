"""渲染成一条能直接看的消息。

不写文件——报告是给人看的，落在会话里就够。落盘的只有 state/ 里机器自己用的台账。
"""

import time
from typing import List

from .config import Config
from .models import Item

TOP_N = 3


def _line(it: Item, idx: int) -> List[str]:
    head = f"{idx}. {it.title}"
    meta = [t for t in it.tags if t]
    bits = []
    if it.is_free:
        bits.append("免费")
    elif it.min_price is not None:
        price = f"¥{_fmt(it.min_price)}"
        if it.original_price:
            price += f"（原价 ¥{_fmt(it.original_price)}）"
        bits.append(price)
    if it.needs_booking:
        bits.append("需预约")
    if it.date_hints:
        bits.append("/".join(it.date_hints[:3]))
    if it.deadline:
        bits.append(it.deadline)
    if it.venue:
        bits.append(it.venue)
    out = [head, "   " + " · ".join(dict.fromkeys(bits)) if bits else ""]
    body = it.summary or ""
    if body and body[:12] in it.title:
        body = ""
    if body:
        out.append(f"   {body}")
    tail = f"   → {it.url}"
    if it.notes:
        tail += f"  ⚠️ {it.notes}"
    out.append(tail)
    return [x for x in out if x]


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.1f}"


def render(res, cfg: Config, now: time.struct_time = None) -> str:
    now = now or time.localtime()
    stamp = f"{now.tm_mon}.{now.tm_mday:02d}"
    items: List[Item] = res.items
    lines = [f"【{cfg.city} · {stamp} 本地羊毛 {len(items)} 条】", ""]
    if not items:
        lines.append("这周没捞到符合条件的条目。原因见文末。")
        lines.append("")
    else:
        top, rest = items[:TOP_N], items[TOP_N:]
        lines.append("★ 本周最值")
        for i, it in enumerate(top, 1):
            lines.extend(_line(it, i))
        if rest:
            lines.append("")
            lines.append("【列表】")
            for i, it in enumerate(rest, len(top) + 1):
                lines.extend(_line(it, i))

    stats = res.stats or {}
    cov = [
        f"候选 {stats.get('candidates', 0)} 个链接，抓到 {stats.get('fetched', 0)} 篇正文，"
        f"最后留下 {stats.get('kept', 0)} 条。"
    ]
    dropped = stats.get("dropped") or {}
    if dropped:
        cov.append("过滤原因：" + "，".join(f"{k} {v}" for k, v in dropped.items()) + "。")
    if res.notes:
        lines.append("")
        lines.append("【本周没能覆盖 / 需要你确认】")
        for n in dict.fromkeys(res.notes):
            lines.append(f"- {n}")
    lines.append("")
    lines.append("—— " + cov[0])
    if len(cov) > 1:
        lines.append("—— " + cov[1])
    return "\n".join(lines)
