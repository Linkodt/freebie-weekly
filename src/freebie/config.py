"""配置加载：YAML 可选（装了 PyYAML 才解析），JSON 内置支持。

零配置必须能跑，所以所有字段都有默认值。
"""

import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

DEFAULT_QUERIES = [
    "{city} 免费活动",
    "{city} 本周末 免费 活动 汇总",
    "{city} 免费 展览 音乐会 市集",
    "site:mp.weixin.qq.com {city} 免费 音乐会",
]


@dataclass
class Filters:
    free_only: bool = False          # True = 只要免费的
    max_price: float = 80.0          # 低价上限（元）
    require_original_price: bool = False  # True = 低价条目必须带原价才留
    lookahead_days: int = 10         # 往后看几天
    min_text_len: int = 400          # 正文太短的多半是图片海报号，抽不出字段


@dataclass
class Config:
    city: str = ""                   # 必须指定（--city 或配置文件）。代码里不写死任何城市
    timezone: str = "Asia/Shanghai"
    backend: str = "auto"            # auto | direct | werss
    werss_url: str = "http://127.0.0.1:8001"
    werss_token: str = ""
    max_items: int = 15
    language: str = "zh"
    queries: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)  # 固定信源：给了就不跑搜索，结果稳定可复现
    use_seeds: bool = True           # 自动读 seeds/ 下 city 同名文件当固定信源
    seeds_dir: str = ""              # 额外的 seeds 目录（默认 ./seeds、./seed、$FREEBIE_SEEDS）
    filters: Filters = field(default_factory=Filters)
    delay_s: float = 1.5             # 每次抓取之间的礼貌间隔

    def query_list(self) -> List[str]:
        qs = self.queries or DEFAULT_QUERIES
        return [q.format(city=self.city) for q in qs]

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def load(path: str = None) -> Config:
    """path 为空时返回默认配置。"""
    if not path:
        return Config()
    if not os.path.exists(path):
        raise SystemExit(f"配置文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    if path.endswith(".json"):
        data = json.loads(raw)
    else:
        try:
            import yaml  # type: ignore
        except ImportError:
            raise SystemExit(
                "读取 YAML 配置需要 PyYAML：pip install freebie-weekly[yaml]\n"
                "（零配置运行时不需要配置文件）"
            )
        data = yaml.safe_load(raw) or {}
    return from_dict(data)


def from_dict(data: dict) -> Config:
    data = dict(data or {})
    flt = data.pop("filters", {}) or {}
    known = {f for f in Config.__dataclass_fields__}
    cfg = Config(**{k: v for k, v in data.items() if k in known})
    known_f = {f for f in Filters.__dataclass_fields__}
    cfg.filters = Filters(**{k: v for k, v in flt.items() if k in known_f})
    return cfg
