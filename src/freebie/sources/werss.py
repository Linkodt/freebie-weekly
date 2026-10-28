"""we-mp-rss（WeRSS）后端：可选，实验性。

WeRSS 是常驻服务，先扫码登录微信，再对外提供 REST/RSS。它比我们自己去抓更稳，
代价是要 docker 起一个服务和一次扫码。所以：装了就用，没装就降级到 direct。

注意：本模块的接口路径按 WeRSS 的 API 目录写，但**尚未对本机实例实测**（本机没起服务），
属 v0.3 目标。调用失败会被 pipeline 记成「后端不可用」并自动降级，不会让周报跑不出来。
"""

import json
import urllib.parse

from .. import fetch
from ..models import Item


class WeRSSError(Exception):
    pass


class WeRSS:
    def __init__(self, base_url: str = "http://127.0.0.1:8001", token: str = "", timeout: int = 20):
        self.base = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _get(self, path: str, **params) -> dict:
        url = f"{self.base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            code, _, data = fetch.get(url, timeout=self.timeout, headers=headers)
        except fetch.FetchError as e:
            raise WeRSSError(f"WeRSS 未启动或不可达: {e}")
        if code and code >= 400:
            raise WeRSSError(f"WeRSS 返回 HTTP {code}")
        try:
            return json.loads(fetch.decode(data))
        except json.JSONDecodeError:
            raise WeRSSError("WeRSS 返回的不是 JSON（可能版本不匹配）")

    def ping(self) -> bool:
        try:
            self._get("/api/v1/wx/mps", page=1, page_size=1)
            return True
        except WeRSSError:
            return False

    def feeds(self) -> list:
        d = self._get("/api/v1/wx/mps", page=1, page_size=200)
        data = d.get("data") or d.get("items") or d
        if isinstance(data, dict):
            data = data.get("list") or data.get("items") or []
        return data if isinstance(data, list) else []

    def articles(self, mp_id: str, limit: int = 20) -> list:
        d = self._get(f"/api/v1/wx/mps/{mp_id}/articles", page=1, page_size=limit)
        data = d.get("data") or d.get("items") or d
        if isinstance(data, dict):
            data = data.get("list") or data.get("items") or []
        return data if isinstance(data, list) else []

    def to_items(self, articles: list) -> list:
        """WeRSS 的文章对象字段名在不同版本里变过，这里做宽松映射。"""
        out = []
        for a in articles:
            url = a.get("url") or a.get("link") or a.get("content_url") or ""
            if not url:
                continue
            out.append(
                Item(
                    url=url,
                    title=a.get("title") or "",
                    account=(a.get("mp_name") or a.get("nickname") or ""),
                    published_at=int(a.get("publish_time") or a.get("publishTime") or 0),
                    summary=(a.get("description") or "")[:140],
                    source="werss",
                )
            )
        return out
