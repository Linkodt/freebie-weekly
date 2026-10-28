"""本地状态：去重台账 + 账号健康度。

报告是给人看的，不落盘；这里的东西是给机器看的，所以落盘。混在一起两边都做不好。
state/ 已加进 .gitignore。
"""

import json
import os
import time
from typing import Dict, Iterable, Set

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "state", "seen.json")


class State:
    def __init__(self, path: str = None, read_only: bool = False):
        self.path = path or os.path.abspath(DEFAULT_PATH)
        self.read_only = read_only
        self.data = {"seen": {}, "accounts": {}, "last_run": 0}
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except (OSError, json.JSONDecodeError):
                pass  # 台账坏了就当空的，不能因为台账让周报跑不起来

    @property
    def seen(self) -> Set[str]:
        return set(self.data.get("seen", {}))

    def mark(self, keys: Iterable[str], now: int = None) -> None:
        now = int(now or time.time())
        for k in keys:
            if k:
                self.data.setdefault("seen", {})[k] = now

    def prune(self, keep_seconds: int = 60 * 60 * 24 * 120) -> None:
        cut = int(time.time()) - keep_seconds
        self.data["seen"] = {k: v for k, v in self.data.get("seen", {}).items() if v >= cut}

    def touch(self, account: str, ok: bool, note: str = "") -> None:
        if not account:
            return
        rec = self.data.setdefault("accounts", {}).setdefault(
            account, {"ok": 0, "fail": 0, "last_ok": 0, "last_note": ""}
        )
        now = int(time.time())
        if ok:
            rec["ok"] += 1
            rec["last_ok"] = now
            rec["fail"] = 0
        else:
            rec["fail"] += 1
            rec["last_note"] = note[:120]
        rec["last_seen"] = now

    def health_report(self, threshold: int = 3) -> Dict[str, dict]:
        return {k: v for k, v in self.data.get("accounts", {}).items() if v.get("fail", 0) >= threshold}

    def save(self) -> None:
        if self.read_only:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.data["last_run"] = int(time.time())
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
