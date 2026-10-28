"""发现层：找一个活动的真实链接。

任何单一搜索引擎都会限流——这是长期事实，不是 bug。所以这里做成多引擎适配器：
按顺序试，用第一个出结果的，并如实回报哪些引擎失败了。
失败信息会被渲染进报告的「本周没能覆盖」，不吞掉。
"""

import base64
import html
import re
import urllib.parse
from typing import List, Tuple

from .. import fetch


class SearchBlocked(Exception):
    pass


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


def _unwrap_bing(href: str) -> str:
    """Bing 会把外链包成 bing.com/ck/a?...&u=a1<base64url>。"""
    if "bing.com/ck/a" not in href:
        return href
    m = re.search(r"[?&]u=(a1[A-Za-z0-9_\-]+)", href)
    if not m:
        return href
    raw = m.group(1)[2:]
    pad = "=" * (-len(raw) % 4)
    try:
        return base64.urlsafe_b64decode(raw + pad).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return href


def bing(query: str, timeout: int = 12) -> List[dict]:
    url = "https://www.bing.com/search?q=" + urllib.parse.quote(query) + "&setlang=zh-CN&count=30"
    code, _, data = fetch.get(url, timeout=timeout, headers={"Accept-Language": "zh-CN,zh;q=0.9"})
    page = fetch.decode(data)
    if len(page) < 5000:
        raise SearchBlocked(f"bing 只返回 {len(page)} 字节（多半是验证页/重定向）")
    out = []
    for block in re.findall(r'<li class="b_algo".*?</li>', page, re.S):
        m = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        href = _unwrap_bing(html.unescape(m.group(1)))
        out.append({"url": href, "title": _clean(m.group(2)), "account": "", "ts": 0})
    return out


def duckduckgo(query: str, timeout: int = 12) -> List[dict]:
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    code, _, data = fetch.get(url, timeout=timeout)
    page = fetch.decode(data)
    if "result__a" not in page:
        raise SearchBlocked(f"duckduckgo 无结果块（{len(page)} 字节，可能被拦）")
    out = []
    for m in re.finditer(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        href = html.unescape(m.group(1))
        if "uddg=" in href:
            href = urllib.parse.unquote(re.search(r"uddg=([^&]+)", href).group(1))
        out.append({"url": href, "title": _clean(m.group(2)), "account": "", "ts": 0})
    return out


def sogou(query: str, timeout: int = 12) -> List[dict]:
    """搜狗微信文章搜索。返回的 url 是跳转链，取不到真实地址，只用于发现公众号名。"""
    url = "https://weixin.sogou.com/weixin?type=2&query=" + urllib.parse.quote(query)
    code, _, data = fetch.get(
        url, timeout=timeout, headers={"Referer": "https://weixin.sogou.com/"}
    )
    page = fetch.decode(data)
    if "antispider" in page or "txt-box" not in page:
        raise SearchBlocked(f"搜狗返回验证页（{len(page)} 字节）——连续请求过多会被封，间隔≥3 秒")
    out = []
    for block in page.split('<div class="txt-box">')[1:]:
        t = re.search(r"<h3[^>]*>(.*?)</h3>", block, re.S)
        if not t:
            continue
        title = _clean(html.unescape(t.group(1)))
        ts = re.search(r"timeConvert\('(\d+)'\)", block)
        sp = re.search(r'<div class="s-p"[^>]*>(.*?)</div>', block, re.S)
        parts = [p.strip() for p in re.split(r"<[^>]+>", sp.group(1)) if p.strip()] if sp else []
        parts = [p for p in parts if "timeConvert" not in p and "document.write" not in p]
        out.append(
            {
                "url": "",
                "title": title,
                "account": html.unescape(parts[-1]) if parts else "",
                "ts": int(ts.group(1)) if ts else 0,
            }
        )
    return out


ENGINES = {"bing": bing, "duckduckgo": duckduckgo, "sogou": sogou}
DEFAULT_ORDER = ("bing", "duckduckgo", "sogou")


def search(query: str, order=DEFAULT_ORDER) -> Tuple[List[dict], List[str]]:
    """按顺序试引擎，第一个有结果的直接用。返回 (hits, 失败说明)。"""
    errors = []
    for name in order:
        fn = ENGINES.get(name)
        if not fn:
            continue
        try:
            hits = fn(query)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
            continue
        if hits:
            return hits, errors
        errors.append(f"{name}: 0 条结果")
    return [], errors


def wechat_urls(query: str, order=DEFAULT_ORDER, limit: int = 8) -> Tuple[List[str], List[str]]:
    hits, errors = search(query, order)
    urls, seen = [], set()
    for h in hits:
        u = h.get("url") or ""
        if "mp.weixin.qq.com/s" not in u:
            continue
        if "chksm=" not in u:
            errors.append(f"跳过无 chksm 的链接（会落到验证页）: {u[:60]}")
            continue
        if u not in seen:
            seen.add(u)
            urls.append(u)
        if len(urls) >= limit:
            break
    return urls, errors


# 百科/问答/聚合导航这类页面的共同点：标题像活动，正文全是介绍和一串链接。
# 不是「坏网站」，是「没有本周的时间地点价格」，抽出来只会制造假条目。
JUNK_URL_RE = re.compile(
    r"baike\.baidu\.com|wikipedia\.org|zhihu\.com/question|/search\?|douban\.com/movie/subject"
    r"|weibo\.com/p/|baijiahao\.baidu\.com/(home|\?)|map\.|/login|/signup",
)
ACTIVITY_HINT_RE = re.compile(r"免费|免費|展览|展覽|音乐会|音樂會|活动|活動|周末|週末|演出|市集|讲座|讲座|开放")


def candidate_urls(query: str, order=DEFAULT_ORDER, limit: int = 8, backfill: int = 4) -> Tuple[List[str], List[str]]:
    """找一个活动的真实链接：优先公众号长链，其次官方站/活动平台页。

    为什么要有 backfill：实测 bing/搜狗都**索引不到** mp.weixin 的文章（site: 语法也无效），
    所以只收公众号链路会让周报恒定为 0 条。官方站和活动平台页 bing 是能搜到的，
    它们的字段（免费/时间/场馆）也够用——降级到这个比交白卷诚实。
    为什么限 backfill：非公众号页噪声大，全都收会把周报变成景点推荐。
    """
    hits, errors = search(query, order)
    urls, seen = [], set()
    fallback: List[str] = []
    for h in hits:
        u = (h.get("url") or "").strip()
        if not u.startswith("http") or JUNK_URL_RE.search(u):
            continue
        if "mp.weixin.qq.com/s" in u:
            if "chksm=" not in u:
                errors.append(f"跳过无 chksm 的链接（会落到验证页）: {u[:60]}")
                continue
            if u not in seen:
                seen.add(u)
                urls.append(u)
        elif ACTIVITY_HINT_RE.search(h.get("title") or "") and u not in seen:
            seen.add(u)
            fallback.append(u)
        if len(urls) >= limit:
            break
    if not urls and fallback:
        errors.append(f"没有公众号长链，改用官方站/活动页 {min(backfill, len(fallback))} 个（噪声更高）")
        urls = fallback[:backfill]
    return urls, errors
