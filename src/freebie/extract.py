"""从 HTML 里抽字段。

原则：宁可抽不到字段、标成「待核实」，也不要猜。日报里一条错的价格，
用户白跑一趟，比少一条严重得多。
"""

import html
import re
from typing import List, Optional

# 命中这些标记说明拿到的是验证页而不是正文
BLOCK_MARKERS = (
    "wappoc_appmsgcaptcha",
    "环境异常",
    "请输入验证码",
    "未知错误，请稍后再试",
    "失效的验证页面",
    "antispider",
)

FREE_RE = re.compile(r"免费|免費|免票|(?<!\d)0\s*元|零元|公益|不收费|免预约|免費入場")
BOOKING_RE = re.compile(
    r"(?<!无)(?<!无需)(?<!不需)(?<!不必)(?<!免)(预约|預約)(?!方式)|抢票|搶票|报名|報名|名额|名額|扫码|掃碼|小程序|限量"
)
DEADLINE_RE = re.compile(r"(预约|报名|活動|活动)?\s*截止[^。\n]{0,24}|售完即止|额满即止|額滿即止|先到先得")
PRICE_RE = re.compile(r"[¥￥$]\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*元")
ORIG_PRICE_RE = re.compile(r"原价\s*[¥￥]?\s*(\d+(?:\.\d+)?)|原價\s*[¥￥]?\s*(\d+(?:\.\d+)?)")
MD_RANGE_RE = re.compile(
    r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?\s*[-–—~至到]\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?"
)
DATE_RANGE_RE = re.compile(
    r"(\d{1,2})\s*[月.\-/]\s*(\d{1,2})\s*[日号]?\s*[-–—~至到]\s*(\d{1,2})\s*[日号]?"
)
DATE_POINT_RE = re.compile(r"(\d{1,2})\s*[月.\-/]\s*(\d{1,2})\s*[日号]")
WEEK_RE = re.compile(r"本周[一二三四五六日天末]|下周末|本周末")
# 活动行/搜狐这类页把时间写成 2026-11-08 14:30，中文日期正则抓不到。
# 只在「时间：」这类标签后面认，避免把文章发布日当成活动日。
ISO_LABEL_RE = re.compile(
    r"(?<!发布)(?<!發布)(?<!编辑)(?<!更新)(?<!发表)(?:活动时间|活動時間|演出时间|举办时间|开始时间|时间|日期)[：:]\s*(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})"
)
# 「免门票免预约」这类明确否定要压过页面里的「预约入口」链接——否则会误报「需预约」
NO_BOOKING_RE = re.compile(r"免预约|免預約|无需预约|無需預約|不需预约|不用预约|不必预约|直接入场|直接入場|无需报名")
# 详情页标题常常就叫「活动详情」，这种标题进周报等于没标题
GENERIC_TITLE_RE = re.compile(r"^(活动详情|活動詳情|活动报名|活动介绍|活动页|详情|在线报名|立即报名|活动详情页|预约详情)$")
VENUE_NOISE_RE = re.compile(r"预约|報名|报名|入口|攻略|优惠|门票|門票|购票|購票|地址|交通|电话|電話|须知|須知|指南|怎么|怎麼|如何|附[：:]|（")
VENUES = (
    "音乐厅", "美术馆", "博物馆", "图书馆", "大剧院", "剧院", "艺术中心", "文化馆",
    "体育中心", "会展中心", "大学", "学院", "公园", "书城", "剧场", "展馆", "影城",
)
AD_WORDS = ("团购", "优惠券", "领券", "下单", "包邮", "加盟", "招商", "扫码进群", "点我")
TITLE_KEY_RE = re.compile(r"[\s\u3000|｜、,，.。:：!！?？\"“”'‘’()（）\[\]【】\-—_~·]+")
GOOD_KEYS = ("时间", "日期", "地点", "地址", "场地", "演出", "展览", "音乐会", "门票", "票券", "市集", "讲座", "开放")
BAD_KEYS = ("解决方案", "私有化", "阿里云", "腾讯云", "售前", "客服", "下载", "加盟", "招商", "会员卡", "发布活动")


class Blocked(Exception):
    """拿到的是验证页/风控页，不是文章。"""


def is_blocked(text: str) -> bool:
    if len(text) > 200_000:  # 正文页一般远大于验证页，先粗筛
        return False
    return any(m in text for m in BLOCK_MARKERS)


def html_to_text(page: str) -> str:
    page = re.sub(r"<script[^>]*>.*?</script>", " ", page, flags=re.S | re.I)
    page = re.sub(r"<style[^>]*>.*?</style>", " ", page, flags=re.S | re.I)
    page = re.sub(r"<br\s*/?>", "\n", page, flags=re.I)
    page = re.sub(r"</(p|div|li|h[1-6]|tr|section|article)>", "\n", page, flags=re.I)
    page = re.sub(r"<[^>]+>", " ", page)
    page = html.unescape(page)
    lines = []
    for ln in page.split("\n"):
        ln = re.sub(r"[ \t\u00a0\u2002-\u200b\u3000]+", " ", ln).strip()
        if ln:
            lines.append(ln)
    return "\n".join(lines)


def _meta_title(page: str) -> str:
    """政府站/活动平台的标题坑最多，按可靠性倒序试，不能只认 og:title。"""
    for pat in (
        r'<meta\s+name="ArticleTitle"\s+content="([^"]*)"',
        r'<meta\s+property="og:title"\s+content="([^"]*)"',
        r'<h1[^>]*class="rich_media_title"[^>]*>(.*?)</h1>',
    ):
        m = re.search(pat, page, re.S)
        if m:
            t = html_to_text(html.unescape(m.group(1))).strip()
            if t:
                return t
    m = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    if m:
        t = html_to_text(m.group(1)).strip()
        if t:
            return t
    m = re.search(r"<title>(.*?)</title>", page, re.S)
    if not m:
        return ""
    t = html_to_text(m.group(1)).strip()
    for sep in ("-", "_", "|", "｜"):
        if sep in t:
            head = t.split(sep)[0].strip()
            if len(head) >= 6:
                return head
    return t


def _account(page: str) -> str:
    for pat in (
        r'var nickname\s*=\s*htmlDecode\("([^"]*)"\)',
        r'var nickname\s*=\s*"([^"]*)"',
        r'<a[^>]*id="js_name"[^>]*>(.*?)</a>',
        r'<strong[^>]*class="profile_nickname"[^>]*>(.*?)</strong>',
    ):
        m = re.search(pat, page, re.S)
        if m:
            return html_to_text(html.unescape(m.group(1))).strip()
    return ""


def _body(page: str) -> str:
    """只取正文 div，避免把页脚、二维码、推荐位一起吃进来。"""
    i = page.find('id="js_content"')
    if i < 0:
        i = page.find("<body")
        if i < 0:
            return ""
    seg = page[i : i + 400_000]
    for cut in ('id="js_pc_qr_code"', "rich_media_area_extra", "class=\"rich_media_tool\"",
                "id=\"js_article_comment\""):
        j = seg.find(cut)
        if j > 0:
            seg = seg[:j]
            break
    return _filter_lines(html_to_text(seg))


JUNK_LINE_RE = re.compile(
    r"^(首页|当前位置|上一篇|下一篇|分享到|返回顶部|关于我们|联系我们|广告合作|版权|版权所有|免责声明|Copyright"
    r"|日期|来源|发布时间|编辑|作者|责任编辑)[：:]"
    r"|^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\s+\d{1,2}:\d{2}"
    r"|免费(创建|发布|注册|咨询|试听|兑换)|时间币|扫码下载|关注我们|-->|活动管理系统|活动发布平台|主办方入驻"
    r"|^[\s>·|—\-_]+$"
)


LABEL_RE = re.compile(r"^(预约方式|报名方式|活动时间|活动地点|活动地址|购票方式|参与方式)[：:]\s*")


def _filter_lines(text: str) -> str:
    """去掉导航/页脚/引导语。它们会制造『免费』假阳性——这是这份清单最贵的错误。

    标签行只剥掉标签本身：「预约方式：关注公众号预约」的后半句是真信息，整行丢太可惜。
    """
    out = []
    for ln in text.split("\n"):
        if not ln or JUNK_LINE_RE.search(ln):
            continue
        rest = LABEL_RE.sub("", ln)
        if rest:
            out.append(rest)
    return "\n".join(out)


def page_price(page: str) -> dict:
    """活动平台的票价在页面内嵌 JSON 里（活动行/大麦都这么写），正文反而没有。

    只在正文里找不到价格时才用，且必须两个字段互证，避免抓到「参考价」之类的营销数字。
    """
    out = {"free": None, "price": None, "original": None}
    m = re.search(r'"PriceStr"\s*:\s*"([^"]{1,12})"', page)
    if m:
        s = m.group(1)
        if "免费" in s or "免費" in s or s.strip() in ("0", "0.0"):
            out["free"] = True
        else:
            d = re.search(r"\d+(?:\.\d+)?", s)
            if d:
                out["price"] = float(d.group(0))
    m = re.search(r'"DisPrice"\s*:\s*(\d+(?:\.\d+)?)', page)
    if m:
        v = float(m.group(1))
        if v == 0:
            out["free"] = True
        elif out["price"] is None:
            out["price"] = v
    m = re.search(r'"SrcPriceStr"\s*:\s*"([^"]{1,12})"', page)
    if m:
        d = re.search(r"\d+(?:\.\d+)?", m.group(1))
        if d:
            out["original"] = float(d.group(0))
    return out


def parse_article(page: str) -> dict:
    if is_blocked(page):
        raise Blocked("拿到的是验证页/风控页")
    m = re.search(r'var\s+ct\s*=\s*"(\d+)"', page)
    published_at = int(m.group(1)) if m else 0
    title = _meta_title(page)
    if not title:
        raise Blocked("没解析到标题，页面结构可能已变")
    text = _body(page)
    if GENERIC_TITLE_RE.match(title.strip()):
        better = _content_title(text)
        if better:
            title = better
    title = _strip_site_suffix(title)
    return {
        "title": title,
        "account": _account(page),
        "published_at": published_at,
        "text": text,
        "page_price": page_price(page),
    }


def _strip_site_suffix(title: str) -> str:
    """`…攻略来啦_北京时间`：og:title 常带站点名，剪掉；标题本身很短时不剪。"""
    m = re.search(r"[_|｜]\s*([^_|｜]{2,10})$", title)
    if m and m.start() >= 8 and not re.search(r"\d", m.group(1)):
        return title[: m.start()].strip()
    return title


def _content_title(text: str) -> str:
    """详情页标题是「活动详情」时，从正文里挑一行当标题（优先含活动类型的那行）。"""
    cands = [
        ln.strip()
        for ln in text.split("\n")
        if 8 <= len(ln.strip()) <= 60 and not JUNK_LINE_RE.search(ln)
    ]
    if not cands:
        return ""
    for k in ("音乐会", "展览", "讲座", "演出", "市集", "游园", "开放日", "嘉年华"):
        for ln in cands[:12]:
            if k in ln:
                return ln
    return cands[0]


def _uniq(seq) -> List[str]:
    out, seen = [], set()
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def extract_fields(text: str) -> dict:
    prices: List[float] = []
    for a, b in PRICE_RE.findall(text):
        v = a or b
        try:
            prices.append(float(v))
        except ValueError:
            continue
    prices = sorted({p for p in prices if 0 < p <= 99999})
    m = ORIG_PRICE_RE.search(text)
    orig: Optional[float] = None
    if m:
        try:
            orig = float(m.group(1) or m.group(2))
        except (TypeError, ValueError):
            orig = None
    dates = []
    # 「10月31日至11月1日」必须先按双月匹配，否则会被 DATE_RANGE_RE 截成「10.31-11」
    for mo1, d1, mo2, d2 in MD_RANGE_RE.findall(text):
        dates.append(f"{int(mo1)}.{int(d1)}-{int(mo2)}.{int(d2)}")
    rest = MD_RANGE_RE.sub(" ", text)
    for mo, d1, d2 in DATE_RANGE_RE.findall(rest):
        dates.append(f"{int(mo)}.{int(d1)}-{int(mo)}.{int(d2)}")
    for mo, d in DATE_POINT_RE.findall(rest):
        dates.append(f"{int(mo)}.{int(d)}")
    for _y, mo, d in ISO_LABEL_RE.findall(text):
        dates.append(f"{int(mo)}.{int(d)}")
    dates = _valid_hints(dates)
    dates += WEEK_RE.findall(text)
    venue = _venue(text)
    dl = DEADLINE_RE.search(text)
    return {
        "is_free": bool(FREE_RE.search(text)),
        "prices": prices,
        "original_price": orig,
        "needs_booking": bool(BOOKING_RE.search(text)) and not NO_BOOKING_RE.search(text),
        "deadline": dl.group(0).strip() if dl else "",
        "date_hints": _uniq(dates)[:6],
        "venue": venue,
    }


def _valid_hints(dates: List[str]) -> List[str]:
    """'26.10-11' 是年份碎片误匹配，不是日期：丢掉，不猜。"""
    out = []
    for h in dates:
        nums = re.findall(r"\d{1,4}", h)
        if len(nums) >= 2:
            mo, day = int(nums[0]), int(nums[1])
            if not (1 <= mo <= 12 and 1 <= day <= 31):
                continue
        out.append(h)
    return out


def _venue(text: str) -> str:
    """整行当场地，但「在城市绿心森林公园举行中」这类要剥掉动词，否则读起来是半句话。"""
    for v in VENUES:
        for m in re.finditer(v, text):
            k = m.start()
            start = text.rfind("\n", 0, k) + 1
            end = text.find("\n", k)
            line = text[start : end if end > 0 else len(text)].strip()
            if not (0 < len(line) <= 30) or "-->" in line or "首页" in line:
                continue
            # 「XX剧院入场参观预约方式2026（预约入口+优惠政策）」是相关推荐链接，不是场地
            if VENUE_NOISE_RE.search(line):
                continue
            line = re.sub(r"^[在于]\s*", "", line)
            line = re.sub(r"(举行|举办|开展|开放)?中?[，,。！!]?$", "", line)
            if line:
                return line
    return ""


def summarize(text: str, title: str = "", limit: int = 110) -> str:
    """挑一行最能代表这场活动的话。

    不能只取「第一行含活动」——平台页的导航和页脚广告都含这些词。
    这里按「像不像活动事实」打分：时间/地点/演出加分，企业方案/客服/下载减分。
    """
    head = TITLE_KEY_RE.sub("", title or "")[:16]
    lines = [
        ln
        for ln in text.split("\n")
        if len(ln) >= 12
        and ln.count(">") < 2
        and not JUNK_LINE_RE.search(ln)  # 元数据行（日期：/来源：）曾被选成摘要
        and not any(w in ln for w in AD_WORDS[:2])
        and "{{" not in ln  # Vue/Handlebars 模板残留，不是给人看的字
        and "}}" not in ln
    ]
    if head:
        trimmed = [ln for ln in lines if head not in ln]
        lines = trimmed or lines
    best, best_score = "", -99.0
    for idx, ln in enumerate(lines):
        s = 0.0
        if any(k in ln for k in GOOD_KEYS):
            s += 3
        if any(k in ln for k in ("免费", "预约", "抢票", "报名", "入场")):
            s += 2
        if any(k in ln for k in BAD_KEYS):
            s -= 5
        s -= idx * 0.01  # 同分取靠前的：正文开头的段落更接近事实
        if s > best_score:
            best, best_score = ln, s
    # 分数不为正说明这页只有导航和广告：宁可不写摘要，也不印一行垃圾
    return _clip(best, limit) if best and best_score > 0 else ""


def _clip(s: str, limit: int) -> str:
    s = re.sub(r"\s+", " ", s).strip(" 　:：-—*|")
    return s if len(s) <= limit else s[: limit - 1] + "…"
