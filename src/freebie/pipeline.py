"""主流程：拿候选 → 抓正文 → 抽字段 → 过滤 → 去重 → 排序。

每一步的丢弃都要能被说出来（进 notes / stats），否则报告里的「本周没能覆盖」
就没法写，用户也就没法判断这份清单能不能信。
"""

import os
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

from . import ranking, seeds, sources
from .config import Config
from .models import Item

TITLE_NOISE_RE = re.compile(r"[\s\u3000|｜、,，.。:：!！?？\"“”'‘’()（）\[\]【】\-—_~·]+")


@dataclass
class Result:
    items: List[Item] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _hint_offset(hint: str, now: time.struct_time) -> Optional[int]:
    """把 '10.31' / '本周末' 这类线索换成「距今几天」。解析不出返回 None。"""
    if any(k in hint for k in ("周末", "本周", "下周")):
        return 0 if "本" in hint else 7
    nums = re.findall(r"\d{1,2}", hint)
    if len(nums) < 2:
        return None
    month, day = int(nums[0]), int(nums[1])
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    year = now.tm_year + (1 if month < now.tm_mon - 6 else 0)
    try:
        target = time.mktime((year, month, day, 12, 0, 0, 0, 0, -1))
    except (ValueError, OverflowError):
        return None
    return int((target - time.mktime(now)) // 86400)


def in_window(item: Item, cfg: Config, now: time.struct_time) -> tuple:
    offsets = [_hint_offset(h, now) for h in item.date_hints]
    offsets = [o for o in offsets if o is not None]
    if not offsets:
        return True, "未标时间"
    if any(-1 <= o <= cfg.filters.lookahead_days for o in offsets):
        return True, ""
    if max(offsets) < -1:
        return False, "已过期"
    return False, "超出窗口"


def _future_hints(hints: List[str], now: time.struct_time) -> List[str]:
    """已经过去的日期别印在报告里——用户会以为还能去。"""
    out = []
    for h in hints:
        o = _hint_offset(h, now)
        if o is None or o >= -1:
            out.append(h)
    return out


def normalize_title(title: str) -> str:
    return TITLE_NOISE_RE.sub("", title or "")[:40]


def gather_urls(cfg: Config, urls=None, queries=None, backend=None, notes=None) -> List[str]:
    notes = notes if notes is not None else []
    if urls:
        return list(urls)

    backend = (backend or cfg.backend or "auto").lower()

    if backend in ("auto", "werss"):
        client = sources.werss.WeRSS(cfg.werss_url, cfg.werss_token)
        if client.ping():
            out = []
            for feed in client.feeds():
                mp_id = feed.get("id") or feed.get("mp_id")
                if not mp_id:
                    continue
                try:
                    out += [a.get("url", "") for a in client.articles(str(mp_id), limit=10)]
                except sources.werss.WeRSSError as e:
                    notes.append(f"WeRSS 取文失败: {e}")
            out = [u for u in out if u]
            if out:
                notes.append(f"后端: WeRSS（{len(out)} 篇候选）")
                return out
            notes.append("WeRSS 在线但没有返回文章，降级到直接抓取")
        elif backend == "werss":
            notes.append("指定了 werss 后端但服务不可达（先 docker 起 we-mp-rss 并扫码）")
            return []
        else:
            notes.append("WeRSS 未运行，走直接抓取（这是默认路径，不需要 docker）")

    found = list(cfg.sources or [])
    if found:
        notes.append(f"使用配置里的 {len(found)} 个固定信源（不跑搜索，结果可复现）")
        return found

    # 城市决定信源：seeds/ 里有同城文件就用它，没有就退回通用搜索词。
    # 这样新增城市只加一个 yaml，不动代码。
    seed = seeds.find(cfg.city, cfg.seeds_dir) if cfg.use_seeds else None
    if seed and seed.urls():
        notes.append(
            f"使用 seeds/{os.path.basename(seed.path)} 的 {len(seed.urls())} 个{seed.city}信源（不跑搜索）"
        )
        return seed.urls()

    qs = queries or (seed.queries if seed and seed.queries else cfg.query_list())
    for q in qs:
        try:
            urls_q, errors = sources.search.candidate_urls(q, limit=6)
        except Exception as e:  # noqa: BLE001
            notes.append(f"搜索「{q}」失败: {e}")
            continue
        notes.extend(errors[:2])
        if urls_q:
            found += urls_q
        else:
            notes.append(f"搜索「{q}」没找到可抓的链接")
        time.sleep(1.2)
    # 去重保序
    seen, uniq = set(), []
    for u in found:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def run(
    cfg: Config,
    urls=None,
    queries=None,
    backend=None,
    state=None,
    now: time.struct_time = None,
    verbose: bool = False,
) -> Result:
    now = now or time.localtime()
    res = Result()
    cand = gather_urls(cfg, urls=urls, queries=queries, backend=backend, notes=res.notes)
    res.stats["candidates"] = len(cand)
    if not cand:
        res.notes.append("没有任何候选链接")
        return res

    raw: List[Item] = []
    seen_keys = state.seen if state is not None else set()
    for i, url in enumerate(cand):
        item, err = sources.direct.try_fetch(url)
        # 移动站/资讯站会偶尔吐一个空壳页（实测 btime 同一链接一次 3483 字、一次 0 字）。
        # 空壳明显是瞬时故障，重试一次；130 字的「账号已迁移」是真内容，不重试。
        if not err and item.text_len < 200:
            if verbose:
                print(f"  [{i + 1}/{len(cand)}] 正文仅 {item.text_len} 字，重试一次")
            time.sleep(cfg.delay_s)
            again, err2 = sources.direct.try_fetch(url)
            if not err2 and again.text_len > item.text_len:
                item = again
        if err:
            res.notes.append(err)
            if verbose:
                print(f"  [{i + 1}/{len(cand)}] 失败 {err}")
            continue
        if verbose:
            print(f"  [{i + 1}/{len(cand)}] {item.title[:40]} 正文 {item.text_len} 字")
        raw.append(item)
        if i + 1 < len(cand):
            time.sleep(cfg.delay_s)

    res.stats["fetched"] = len(raw)

    kept, dropped = [], {}
    for it in raw:
        if it.text_len < cfg.filters.min_text_len:
            dropped["正文太短"] = dropped.get("正文太短", 0) + 1
            continue
        if it.key in seen_keys:
            dropped["上周已推过"] = dropped.get("上周已推过", 0) + 1
            continue
        if cfg.filters.free_only and not it.is_free:
            dropped["非免费"] = dropped.get("非免费", 0) + 1
            continue
        if not it.is_free:
            if it.min_price is None:
                dropped["低价但没标价格"] = dropped.get("低价但没标价格", 0) + 1
                continue
            if it.min_price > cfg.filters.max_price:
                dropped["超出价格上限"] = dropped.get("超出价格上限", 0) + 1
                continue
            if cfg.filters.require_original_price and not it.original_price:
                dropped["低价但缺原价锚点"] = dropped.get("低价但缺原价锚点", 0) + 1
                continue
        ok, why = in_window(it, cfg, now)
        if not ok:
            dropped[why] = dropped.get(why, 0) + 1
            continue
        if why:
            it.notes = (it.notes + "；" + why) if it.notes else why
        it.date_hints = _future_hints(it.date_hints, now)
        kept.append(it)

    # 同一活动被多个号转载：按归一化标题去重，留信息量最大的那条
    best = {}
    for it in kept:
        k = normalize_title(it.title)
        cur = best.get(k)
        if cur is None or it.text_len > cur.text_len:
            if cur is not None:
                dropped["重复转载"] = dropped.get("重复转载", 0) + 1
            best[k] = it
        else:
            dropped["重复转载"] = dropped.get("重复转载", 0) + 1

    ranked = ranking.rank(list(best.values()), now)
    res.items = ranked[: cfg.max_items]
    res.stats["dropped"] = dropped
    res.stats["kept"] = len(res.items)
    return res
