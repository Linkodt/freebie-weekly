"""数据结构：一条候选活动。字段刻意扁平，方便写进 state/ 和直接渲染成卡片。"""

from dataclasses import asdict, dataclass, field
from typing import List, Optional


@dataclass
class Item:
    url: str = ""
    title: str = ""
    account: str = ""
    published_at: int = 0  # unix 秒；0 表示没解析到
    summary: str = ""
    is_free: bool = False
    prices: List[float] = field(default_factory=list)
    original_price: Optional[float] = None
    needs_booking: bool = False
    deadline: str = ""
    date_hints: List[str] = field(default_factory=list)
    venue: str = ""
    tags: List[str] = field(default_factory=list)
    score: float = 0.0
    text_len: int = 0
    source: str = ""  # direct / werss / manual
    notes: str = ""

    @property
    def key(self) -> str:
        """去重键：优先 URL，其次标题。"""
        return self.url or self.title

    @property
    def min_price(self) -> Optional[float]:
        return min(self.prices) if self.prices else None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Item":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
