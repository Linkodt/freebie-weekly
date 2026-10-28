"""命令行入口：freebie run / discover / doctor。"""

import argparse
import json
import os
import time
import sys

from . import __version__, config, pipeline, report, seeds
from .sources import search as search_mod
from .state import State


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="freebie",
        description="每周一次，把本地免费/低价活动整理成一份能照着去的清单。",
    )
    p.add_argument("--version", action="version", version=f"freebie-weekly {__version__}")
    sub = p.add_subparsers(dest="cmd")

    r = sub.add_parser("run", help="抓一轮并输出周报")
    r.add_argument("--city", help="城市名，覆盖配置")
    r.add_argument("--config", help="配置文件路径（可省，零配置也能跑）")
    r.add_argument("--urls", nargs="*", help="直接抓这些链接（跳过搜索）")
    r.add_argument("--queries", nargs="*", help="覆盖搜索词，如 \"深圳 免费活动\"")
    r.add_argument("--backend", choices=["auto", "direct", "werss"], help="采集后端")
    r.add_argument("--limit", type=int, help="最多输出几条")
    r.add_argument("--max-price", type=float, help="低价上限（元）")
    r.add_argument("--free-only", action="store_true", help="只要免费的")
    r.add_argument("--lookahead", type=int, help="往后看几天")
    r.add_argument("--dry-run", action="store_true", help="不写去重台账、不落盘")
    r.add_argument("--no-seeds", action="store_true", help="忽略 seeds/ 里的城市信源，强制走搜索")
    r.add_argument("--seeds-dir", help="额外的 seeds 目录（默认 ./seeds、./seed、$FREEBIE_SEEDS）")
    r.add_argument("--json", action="store_true", help="输出 JSON 而不是周报")
    r.add_argument("--verbose", "-v", action="store_true")

    d = sub.add_parser("discover", help="按城市搜一批候选公众号（建清单用）")
    d.add_argument("--city", required=True, help="城市名")
    d.add_argument("--queries", nargs="*")
    d.add_argument("--limit", type=int, default=20)

    c = sub.add_parser("cities", help="列出已备好信源的城市")
    c.add_argument("--seeds-dir", help="额外的 seeds 目录")

    s = sub.add_parser("seeds", help="城市信源文件")
    s.add_argument("action", choices=["init"], help="init = 生成一个待填的城市 yaml")
    s.add_argument("--city", required=True, help="城市名")
    s.add_argument("--dir", default="seeds", help="写到哪个目录（默认 seeds）")
    s.add_argument("--force", action="store_true", help="已存在时覆盖")

    doc = sub.add_parser("doctor", help="自检：网络、后端、配置")
    doc.add_argument("--config", help="配置文件路径")
    doc.add_argument("--werss-url", default="http://127.0.0.1:8001")

    return p


def _cfg(args) -> config.Config:
    cfg = config.load(getattr(args, "config", None))
    if getattr(args, "city", None):
        cfg.city = args.city
    if getattr(args, "no_seeds", False):
        cfg.use_seeds = False
    if getattr(args, "seeds_dir", None):
        cfg.seeds_dir = args.seeds_dir
    if getattr(args, "limit", None):
        cfg.max_items = args.limit
    if getattr(args, "max_price", None) is not None:
        cfg.filters.max_price = args.max_price
    if getattr(args, "free_only", False):
        cfg.filters.free_only = True
    if getattr(args, "lookahead", None):
        cfg.filters.lookahead_days = args.lookahead
    return cfg


def cmd_run(args) -> int:
    cfg = _cfg(args)
    if not cfg.city:
        print("需要指定城市：freebie run --city 北京\n"
              "（也可在 config.yaml 里写 city: 北京；用 freebie cities 看哪些城市已备好信源）",
              file=sys.stderr)
        return 2
    st = State(read_only=args.dry_run)
    res = pipeline.run(
        cfg,
        urls=args.urls,
        queries=args.queries,
        backend=args.backend or cfg.backend,
        state=st,
        verbose=args.verbose,
    )
    if args.json:
        print(json.dumps(
            {
                "city": cfg.city,
                "items": [it.to_dict() for it in res.items],
                "notes": res.notes,
                "stats": res.stats,
            },
            ensure_ascii=False,
            indent=2,
        ))
    else:
        print(report.render(res, cfg))
    if not args.dry_run and res.items:
        st.mark([it.key for it in res.items])
        st.save()
    return 0 if res.items else 2


def cmd_discover(args) -> int:
    cfg = _make_cfg(args)
    queries = args.queries or [f"{args.city} 免费活动", f"{args.city} 本周末 活动 汇总",
                               f"{args.city} 免费 展览 音乐会"]
    accounts, errors, used = {}, [], []
    for q in queries:
        hits, errs = search_mod.search(q)
        errors += errs
        for h in hits:
            name = h.get("account")
            if name:
                accounts.setdefault(name, {"name": name, "hits": 0, "sample": h.get("title", "")})
                accounts[name]["hits"] += 1
        used.append(q)
    print(f"城市: {args.city}  查询: {len(used)}  发现账号: {len(accounts)}")
    for name, info in sorted(accounts.items(), key=lambda kv: -kv[1]["hits"])[: args.limit]:
        print(f"  {name}\t命中{info['hits']}\t{info['sample'][:50]}")
    if errors:
        print("\n失败的渠道（这决定了下周还漏着什么）:")
        for e in dict.fromkeys(errors):
            print(f"  - {e}")
    return 0 if accounts else 2


def _make_cfg(args):
    cfg = config.Config()
    if getattr(args, "city", None):
        cfg.city = args.city
    return cfg


def cmd_cities(args) -> int:
    found = seeds.all_seeds(getattr(args, "seeds_dir", None))
    if not found:
        print("还没有任何城市信源文件。生成一个：freebie seeds init --city 成都")
        return 2
    print(f"已备好信源的城市 {len(found)} 个（其它城市也能跑，会退回通用搜索）:")
    for s in found:
        print(f"  {s.city:<6} {len(s.urls()):>2} 个信源  {s.path}")
        for c in s.channels:
            print(f"        · {c.get('name', '')} {c.get('url', '')}")
    return 0


def cmd_seeds(args) -> int:
    d = args.dir
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{args.city}.yaml")
    if os.path.exists(path) and not args.force:
        print(f"已存在：{path}（要覆盖加 --force）")
        return 2
    with open(path, "w", encoding="utf-8") as f:
        f.write(seeds.scaffold(args.city))
    print(f"已写入 {path}\n填好 channels 里的 url，然后：freebie run --city {args.city}")
    return 0


def cmd_doctor(args) -> int:
    cfg = config.load(getattr(args, "config", None))
    print(f"freebie-weekly {__version__}")
    print(f"配置: 城市={cfg.city} 后端={cfg.backend} 价格上限=¥{cfg.filters.max_price:g}")
    print("\n搜索引擎可达性（单个引擎超时 8s，三个都挂时整轮最多 ~30s）:")
    for name in search_mod.DEFAULT_ORDER:
        t0 = time.time()
        try:
            hits = search_mod.ENGINES[name](f"{cfg.city} 免费活动", timeout=8)
            print(f"  {name}: OK，{len(hits)} 条，{time.time() - t0:.1f}s")
        except Exception as e:  # noqa: BLE001
            print(f"  {name}: 不可用 —— {e}（{time.time() - t0:.1f}s）")
    from .sources.werss import WeRSS

    print("\nWeRSS 后端:")
    print("  可达" if WeRSS(args.werss_url).ping() else "  未运行（可选，不影响 direct 路径）")
    return 0


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "discover":
        return cmd_discover(args)
    if args.cmd == "doctor":
        return cmd_doctor(args)
    if args.cmd == "cities":
        return cmd_cities(args)
    if args.cmd == "seeds":
        return cmd_seeds(args)
    _build_parser().print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
