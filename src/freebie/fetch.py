"""HTTP 取页：优先 curl，失败回落 urllib。

为什么默认 curl：微信公众号文章的短链用 urllib 经常直接连不上，而 curl 跟着重定向走
能拿到正文。两者都失败才算失败，且失败要能被上层看见。
"""

import os
import subprocess
import time
import tempfile
import urllib.error
import urllib.request

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class FetchError(Exception):
    pass


def _curl(url: str, timeout: int, ua: str, headers: dict):
    fd, path = tempfile.mkstemp(prefix="freebie-")
    os.close(fd)
    cmd = [
        "curl", "-sL", "--max-time", str(timeout), "-A", ua,
        "-o", path, "-w", "%{http_code} %{url_effective}", url,
    ]
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        meta = (p.stdout or "").strip()
        with open(path, "rb") as f:
            data = f.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    code_str, _, eff = meta.partition(" ")
    try:
        code = int(code_str)
    except ValueError:
        code = 0
    return code, eff or url, data


def _urllib(url: str, timeout: int, ua: str, headers: dict):
    h = {"User-Agent": ua, "Accept-Language": "zh-CN,zh;q=0.9", "Accept": "text/html,*/*"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.geturl(), r.read()
    except urllib.error.HTTPError as e:  # 4xx/5xx 也算拿到响应
        return e.code, url, e.read()


def get(url: str, timeout: int = 25, headers: dict = None, ua: str = UA):
    """返回 (status, final_url, bytes)。curl 失败时换 urllib 再试一次。

    timeout 是**整个函数**的预算，不是每次尝试的预算：curl 已经耗掉大半就直接放弃，
    否则一次被墙的请求会拖成 timeout×2，一轮周报下来慢到没法定时跑。
    """
    started = time.time()
    errors = []
    try:
        code, eff, data = _curl(url, timeout, ua, headers or {})
        if data:
            return code, eff, data
        errors.append(f"curl 空响应(status={code})")
    except Exception as e:  # noqa: BLE001
        errors.append(f"curl 异常: {e}")
    left = timeout - (time.time() - started)
    if left < 2:
        raise FetchError("; ".join(errors) + f"（预算已用尽，不再重试）")
    try:
        code, eff, data = _urllib(url, int(left), ua, headers or {})
        if data:
            return code, eff, data
        errors.append(f"urllib 空响应(status={code})")
    except Exception as e:  # noqa: BLE001
        errors.append(f"urllib 异常: {e}")
    raise FetchError("; ".join(errors))


def decode(data: bytes) -> str:
    for enc in ("utf-8", "gb18030", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "ignore")
