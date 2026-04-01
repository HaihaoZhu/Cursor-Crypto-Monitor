"""主程序入口：按币种拉取 K 线、扫描信号、与本地状态对比后发邮件。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from config_loader import load_config
from data_provider import DEFAULT_MARKET_SYMBOLS, OKXProvider
from notifier import send_email
from strategy import (
    TREND_SCAN_MIN_BARS,
    TrendScanner,
    format_ema_table_cell,
    format_volume_table_cell,
)

LAST_STATUS_PATH = Path(__file__).resolve().parent / "last_status.json"
_FETCH_LIMIT = max(TREND_SCAN_MIN_BARS, 100)
_MAIL_SUBJECT = "Crypto Monitor 信号变更"


def _detection_time_parts(at_utc: datetime) -> tuple[str, str]:
    """返回 (纯文本段落, HTML 片段)。"""
    if at_utc.tzinfo is None:
        at_utc = at_utc.replace(tzinfo=timezone.utc)
    try:
        cn = at_utc.astimezone(ZoneInfo("Asia/Shanghai"))
        cn_note = "北京时间"
    except Exception:
        cn = at_utc.astimezone(timezone(timedelta(hours=8)))
        cn_note = "UTC+8（回退）"
    cn_s = cn.strftime("%Y-%m-%d %H:%M:%S")
    utc_s = at_utc.strftime("%Y-%m-%d %H:%M:%S")
    plain = (
        f"检测时间：{cn_s}（{cn_note}）\n"
        f"UTC：{utc_s}\n"
        "\n"
    )
    html = (
        f'<p style="margin:0 0 14px 0;font-size:14px;line-height:1.5">'
        f"检测时间：<strong>{escape(cn_s)}</strong>（{escape(cn_note)}）<br/>"
        f"UTC：<strong>{escape(utc_s)}</strong></p>"
    )
    return plain, html


def _fmt_price(last_close: float | None) -> str:
    if last_close is None:
        return "—"
    return f"{last_close:,.2f}"


def _build_email_bodies(
    at_utc: datetime,
    last_close: dict[str, float | None],
    current_status: dict[str, list[str]],
    changed_symbols: set[str],
) -> tuple[str, str]:
    plain_head, html_head = _detection_time_parts(at_utc)

    plain_lines = [
        plain_head.rstrip("\n"),
        "Crypto\t检测价格\tEMA情况\t成交量情况",
    ]
    rows_html: list[str] = []

    for sym in DEFAULT_MARKET_SYMBOLS:
        price_s = _fmt_price(last_close.get(sym))
        tags = current_status[sym]
        ema_text = format_ema_table_cell(tags)
        vol_text = format_volume_table_cell(tags)
        plain_lines.append(f"{sym}\t{price_s}\t{ema_text}\t{vol_text}")

        ema_html = escape(ema_text)
        vol_html = escape(vol_text)
        if vol_text == "成交量上升":
            vol_html = f'<span style="color:#c05621;font-weight:600">{vol_html}</span>'
        row_bg = "#fff8e6" if sym in changed_symbols else "#ffffff"
        rows_html.append(
            f'<tr style="background:{row_bg}">'
            f"<td style='padding:8px 12px;border:1px solid #ddd'>{escape(sym)}</td>"
            f"<td style='padding:8px 12px;border:1px solid #ddd;text-align:right'>{escape(price_s)}</td>"
            f"<td style='padding:8px 12px;border:1px solid #ddd'>{ema_html}</td>"
            f"<td style='padding:8px 12px;border:1px solid #ddd'>{vol_html}</td>"
            "</tr>"
        )

    changed_sorted = ", ".join(sorted(changed_symbols))
    plain_lines.append("")
    plain_lines.append(f"本次信号相对上次有变动的交易对：{changed_sorted}")
    plain_body = "\n".join(plain_lines)

    table = (
        '<table style="border-collapse:collapse;font-size:14px;min-width:640px">'
        "<thead><tr style='background:#f0f4f8'>"
        "<th style='padding:10px 12px;border:1px solid #ccc;text-align:left'>Crypto</th>"
        "<th style='padding:10px 12px;border:1px solid #ccc;text-align:right'>检测价格</th>"
        "<th style='padding:10px 12px;border:1px solid #ccc;text-align:left'>EMA情况</th>"
        "<th style='padding:10px 12px;border:1px solid #ccc;text-align:left'>成交量情况</th>"
        "</tr></thead><tbody>"
        + "".join(rows_html)
        + "</tbody></table>"
    )
    foot = (
        f'<p style="margin:14px 0 0 0;font-size:13px;color:#555">'
        f"本次推送触发原因：上述表格中 <strong>浅黄底色</strong> 行为信号相对上次有变动的交易对。"
        f"<br/>变动列表：{escape(changed_sorted)}</p>"
    )
    html_body = (
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
        '<body style="font-family:Segoe UI,PingFang SC,Microsoft YaHei,Arial,sans-serif">'
        f"{html_head}{table}{foot}</body></html>"
    )
    return plain_body, html_body


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
    last_close: dict[str, float | None] = {}
    for sym in DEFAULT_MARKET_SYMBOLS:
        df = provider.get_candles(sym, limit=_FETCH_LIMIT)
        if df.empty or "close" not in df.columns:
            last_close[sym] = None
        else:
            last_close[sym] = float(df["close"].iloc[-1])
        current_status[sym] = TrendScanner(df).get_signals()

    detected_at_utc = datetime.now(timezone.utc)

    changed_symbols: set[str] = set()
    for sym in DEFAULT_MARKET_SYMBOLS:
        if current_status[sym] != last_status.get(sym, []):
            changed_symbols.add(sym)

    if not changed_symbols:
        return

    text_body, html_body = _build_email_bodies(
        detected_at_utc,
        last_close,
        current_status,
        changed_symbols,
    )
    send_email(_MAIL_SUBJECT, text_body, html_body=html_body)

    ordered = {sym: list(current_status[sym]) for sym in DEFAULT_MARKET_SYMBOLS}
    LAST_STATUS_PATH.write_text(
        json.dumps(ordered, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
