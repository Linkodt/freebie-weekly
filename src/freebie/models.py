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
        """去重键：URL，没有 URL 时退回标题。

        为什么不用「URL + 标题」：实测同一个页面两次抓取会一次给正文、一次给空壳
        （btime 就是这样），标题和日期都会漂，键跟着漂就会同一场活动反复上报。
        URL 是这些页面里唯一稳定的字段。代价是「地址不变、内容原地更新」的专题页
        不会被重复推送——公众号文章每周是新链接，不受影响。
        """
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
