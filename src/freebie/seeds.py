"""城市种子：把「哪个城市有哪些信源」从代码里挪到数据文件。

设计目标只有一个：**加城市不改代码**。
用户 `--city 成都`，这里就去找 seeds/ 下 `city:` 相同的那个文件；
找不到也不报错，退回通用搜索词。所以「支持哪些城市」是数据决定的，不是写死的。

刻意只解析 seeds 文件里用到的那几种 YAML 形状（标量、一层列表、列表项下的标量），
不引 PyYAML——种子文件是给人手写的，形状受我们控制。
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

SEED_DIRS = ("seeds", "seed")
_TOP_RE = re.compile(r"^([A-Za-z_]+):\s*(.*)$")
_ITEM_RE = re.compile(r"^\s*-\s*(.*)$")
_KV_RE = re.compile(r"^\s+([A-Za-z_]+):\s*(.*)$")


@dataclass
class Seed:
    city: str = ""
    path: str = ""
    channels: List[dict] = field(default_factory=list)  # {name, url, note}
    accounts: List[dict] = field(default_factory=list)
    queries: List[str] = field(default_factory=list)

    def urls(self) -> List[str]:
        return [c["url"] for c in self.channels if c.get("url")]


def _scalar(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v


def parse(text: str, path: str = "") -> Seed:
    seed = Seed(path=path)
    section: Optional[str] = None
    cur: Optional[dict] = None
    for raw in text.splitlines():
        if raw.lstrip().startswith("#") or not raw.strip():
            continue
        line = raw.split("  #")[0] if "  #" in raw else raw
        if not line.startswith((" ", "\t")):
            m = _TOP_RE.match(line)
            if not m:
                continue
            key, val = m.group(1), _scalar(m.group(2))
            cur = None
            if key == "city":
                seed.city = val
                section = None
            elif key in ("channels", "accounts", "queries"):
                section = key
            else:
                section = None
            continue
        if section == "queries":
            m = _ITEM_RE.match(line)
            if m:
                q = _scalar(m.group(1))
                if q:
                    seed.queries.append(q)
            continue
        m = _ITEM_RE.match(line)
        if m and section in ("channels", "accounts"):
            cur = {}
            (seed.channels if section == "channels" else seed.accounts).append(cur)
            kv = _TOP_RE.match(m.group(1).strip())
            if kv:
                cur[kv.group(1)] = _scalar(kv.group(2))
            continue
        m = _KV_RE.match(line)
        if m and cur is not None:
            cur[m.group(1)] = _scalar(m.group(2))
    return seed


def _dirs(extra: Optional[str] = None) -> List[str]:
    out = []
    env = os.environ.get("FREEBIE_SEEDS")
    for d in (extra, env, *SEED_DIRS):
        if d and d not in out and os.path.isdir(d):
            out.append(d)
    return out


def all_seeds(extra: Optional[str] = None) -> List[Seed]:
    out = []
    for d in _dirs(extra):
        for name in sorted(os.listdir(d)):
            if not name.endswith((".yaml", ".yml")):
                continue
            p = os.path.join(d, name)
            try:
                with open(p, "r", encoding="utf-8") as f:
                    s = parse(f.read(), p)
            except OSError:
                continue
            if s.city:
                out.append(s)
    return out


def find(city: str, extra: Optional[str] = None) -> Optional[Seed]:
    city = (city or "").strip()
    if not city:
        return None
    for s in all_seeds(extra):
        if s.city.strip() == city:
            return s
    return None


TEMPLATE = """# {city} 本地活动信源清单
#
# 用法：`freebie run --city {city}` 会自动读这个文件里的 channels 当固定信源。
# channels 里填「具体活动页/专题页」而不是栏目首页——栏目页只有列表，抽不出时间。
# 账号清单（accounts）只是给人看的备忘，代码不读。

city: {city}
city_id: {slug}

# 直接抓这些链接（每周覆盖一次，改这里就行）
channels:
  - name: 待填（官方网站名）
    url: https://
    note: 这条今天有什么活动、大概什么时候更新

# 可选：这个城市的搜索词，{city} 会被替换
# queries:
#   - "{city} 本周末 免费 活动 汇总"
#   - "site:mp.weixin.qq.com {city} 免费 音乐会"

# 可选：当地爱发免费活动的公众号（代码暂不读取）
# accounts:
#   - name: 某号
#     note: 每周出周末免费活动汇总
"""


def scaffold(city: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", city.lower()).strip("-")
    return TEMPLATE.format(city=city, slug=slug or "city")
