"""渲染成一条能直接看的消息。

不写文件——报告是给人看的，落在会话里就够。落盘的只有 state/ 里机器自己用的台账。

排版原则（都是被用户吐槽过才定下来的）：
1. 按「什么时候能去」分组，而不是按分数排一长条——用户要的是这周末能去哪；
2. 标题太长就剪，但摘要不半句截断（半截话比没有更难看）；
3. 链接给 markdown 而不是裸 URL，裸 URL 会把整段文字顶成条形码；
4. 每条给一句行动建议（直接去 / 要预约 / 截止日），否则看完还得自己判断；
5. 抓到了但没进本周窗口的，单列出来——只显示 3 条，用户会以为只有 3 条。
"""

import re
import time
from typing import List, Optional
from urllib.parse import urlparse

from .config import Config
from .models import Item
from .pipeline import _hint_offset

WEEK_DAYS = 7
TITLE_MAX = 32
SUMMARY_MAX = 90
MAX_DROPPED = 6

DOMAIN_NAMES = {
    "mp.weixin.qq.com": "公众号原文",
    "item.btime.com": "北京时间",
    "peking.bjd.com.cn": "北京日报",
    "www.beijing.gov.cn": "首都之窗",
    "beijing.gov.cn": "首都之窗",
    "www.chncpa.org": "国家大剧院",
    "www.bendibao.com": "本地宝",
    "m.bj.bendibao.com": "本地宝",
    "sh.bendibao.com": "本地宝",
}


def _title(it: Item) -> str:
    t = it.title.strip()
    # 「通州不远 周末首选 | 拍红叶、逛市集…」这种把栏目标题塞进标题的，只留前半句
    for sep in ("丨", "|", "｜"):
        if sep in t:
            head = t.split(sep)[0].strip()
            # 「通州不远 周末首选」这种前半句只有 8 字、什么也没说，就别剪，
            # 宁可整体截断到 32 字——「通州不远 周末首选 | 拍红叶、逛市集…」比前者有用
            if len(head) >= 12:
                t = head
            break
    t = re.sub(r"\s+", " ", t)
    return t if len(t) <= TITLE_MAX else t[: TITLE_MAX - 1] + "…"


def _price(it: Item) -> str:
    if it.is_free:
        return "免费"
    if it.min_price is not None:
        s = f"¥{_fmt(it.min_price)}"
        if it.original_price:
            s += f"（原价 ¥{_fmt(it.original_price)}）"
        return s
    return "价格未标"


def _action(it: Item) -> str:
    if it.deadline:
        return it.deadline
    if it.needs_booking:
        return "要预约，点原文找入口"
    return "不用预约，直接去"


def _link(url: str) -> str:
    """给域名当链接文字，读起来是「北京时间」而不是一长串百分号。"""
    if "#" in url:  # 汇总页拆出来的条目，链接回到原页
        url = url.split("#")[0]
    host = (urlparse(url).netloc or url).lower()
    label = DOMAIN_NAMES.get(host)
    if not label:
        label = host[4:] if host.startswith("www.") else host
        label = label.split(":")[0]
    return f"[{label}]({url})"


def _summary(it: Item) -> str:
    s = re.sub(r"\s+", " ", it.summary or "").strip()
    if not s or s in it.title or s[:10] in it.title:
        return ""
    return s if len(s) <= SUMMARY_MAX else s[: SUMMARY_MAX - 1] + "…"


def _group(it: Item, now: time.struct_time) -> str:
    """本周 / 之后 / 时间没写清——分组依据是最早一个能去的日期。"""
    offs = [o for o in (_hint_offset(h, now) for h in it.date_hints) if o is not None]
    if not offs:
        return "unknown"
    soon = min(offs)
    return "week" if soon <= WEEK_DAYS else "later"


def _card(it: Item, idx: int) -> List[str]:
    out = [f"{idx}. {_title(it)} ｜ {_price(it)}"]
    meta = []
    if it.date_hints:
        meta.append(" / ".join(it.date_hints[:2]))
    elif it.notes and "未标时间" in it.notes:
        meta.append("时间没写清")
    if it.venue:
        meta.append(it.venue if len(it.venue) <= 26 else it.venue[:25] + "…")
    if meta:
        out.append("   " + " · ".join(meta))
    body = _summary(it)
    if body:
        out.append(f"   {body}")
    out.append(f"   {_action(it)} · {_link(it.url)}")
    return out


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.1f}"


def render(res, cfg: Config, now: time.struct_time = None) -> str:
    now = now or time.localtime()
    stamp = f"{now.tm_mon}.{now.tm_mday:02d}"
    items: List[Item] = res.items
    lines = [f"【{cfg.city} · {stamp} 可薅清单 {len(items)} 条】", ""]

    if not items:
        lines.append("这周没捞到符合条件的新条目。原因见文末。")
        lines.append("")
    else:
        buckets = {"week": [], "later": [], "unknown": []}
        for it in items:
            buckets[_group(it, now)].append(it)
        groups = [
            ("week", "这周就能去"),
            ("later", "之后几天"),
            ("unknown", "时间没写清，要自己点进去看"),
        ]
        idx = 0
        for key, label in groups:
            if not buckets[key]:
                continue
            lines.append(f"▎{label}（{len(buckets[key])}）")
            for it in buckets[key]:
                idx += 1
                lines.extend(_card(it, idx))
                lines.append("")

    dropped = getattr(res, "dropped_items", None) or []
    if dropped:
        lines.append(f"▎也抓到了，但不在本周窗口（{len(dropped)}）")
        for title, why, hints in dropped[:MAX_DROPPED]:
            when = f"，{hints}" if hints else ""
            lines.append(f"- {_short(title)}（{why}{when}）")
        if len(dropped) > MAX_DROPPED:
            lines.append(f"- 还有 {len(dropped) - MAX_DROPPED} 条同类，略。")
        lines.append("")

    stats = res.stats or {}
    cov = [
        f"候选 {stats.get('candidates', 0)} 页 · 抓到 {stats.get('fetched', 0)} 篇正文"
        + (f"（其中汇总页拆出 {stats.get('split', 0)} 场）" if stats.get("split") else "")
        + f" · 留下 {len(items)} 条"
    ]
    dropped_stats = stats.get("dropped") or {}
    if dropped_stats:
        cov.append("过滤：" + " / ".join(f"{k} {v}" for k, v in dropped_stats.items()))
    lines.append("▎覆盖情况")
    for c in cov:
        lines.append("- " + c)
    if res.notes:
        for n in dict.fromkeys(res.notes):
            lines.append("- " + n)
    return "\n".join(lines).rstrip() + "\n"


def _short(title: str, limit: int = 26) -> str:
    t = re.sub(r"\s+", " ", title).strip()
    return t if len(t) <= limit else t[: limit - 1] + "…"
