"""主程序入口：按币种拉取 K 线、扫描信号、与本地状态对比后发邮件。"""

from __future__ import annotations

import json
from pathlib import Path

from config_loader import load_config
from data_provider import DEFAULT_MARKET_SYMBOLS, OKXProvider
from notifier import send_email
from strategy import TREND_SCAN_MIN_BARS, TrendScanner

LAST_STATUS_PATH = Path(__file__).resolve().parent / "last_status.json"
_FETCH_LIMIT = max(TREND_SCAN_MIN_BARS, 100)
_MAIL_SUBJECT = "Crypto Monitor 信号变更"


def main() -> None:
    load_config()

    last_status: dict[str, list[str]] = {}
    if LAST_STATUS_PATH.is_file():
        try:
            raw = json.loads(LAST_STATUS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if not isinstance(k, str):
                        continue
                    if isinstance(v, list) and all(isinstance(x, str) for x in v):
                        last_status[k] = list(v)
                    else:
                        last_status[k] = []
        except (json.JSONDecodeError, OSError):
            last_status = {}

    provider = OKXProvider()
    current_status: dict[str, list[str]] = {}
    for sym in DEFAULT_MARKET_SYMBOLS:
        df = provider.get_candles(sym, limit=_FETCH_LIMIT)
        current_signals = TrendScanner(df).get_signals()
        current_status[sym] = current_signals

    alert_list: list[str] = []
    for sym in DEFAULT_MARKET_SYMBOLS:
        current_signals = current_status[sym]
        old_signals = last_status.get(sym, [])
        if current_signals != old_signals:
            alert_list.append(
                f"{sym}: {', '.join(current_signals) if current_signals else '(无标签)'}"
            )

    if not alert_list:
        return

    send_email(_MAIL_SUBJECT, "\n".join(alert_list))

    ordered = {sym: list(current_status[sym]) for sym in DEFAULT_MARKET_SYMBOLS}
    LAST_STATUS_PATH.write_text(
        json.dumps(ordered, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
