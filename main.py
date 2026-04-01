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
    format_ema_table_lines,
    format_volume_table_cell,
)

LAST_STATUS_PATH = Path(__file__).resolve().parent / "last_status.json"
_FETCH_LIMIT = max(TREND_SCAN_MIN_BARS, 100)
_MAIL_SUBJECT = "Crypto Monitor 15分钟快照"


def _load_last_snapshots(raw: dict) -> dict[str, dict[str, object]]:
    """解析 last_status.json：支持新格式 {sym: {tags, price}} 与旧格式 {sym: [tags...]}。"""
    out: dict[str, dict[str, object]] = {}
    for k, v in raw.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, list) and all(isinstance(x, str) for x in v):
            out[k] = {"tags": list(v), "price": ""}
        elif isinstance(v, dict):
            tags = v.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            tags = [x for x in tags if isinstance(x, str)]
            p = v.get("price", "")
            out[k] = {"tags": tags, "price": p if isinstance(p, str) else ""}
        else:
            out[k] = {"tags": [], "price": ""}
    return out


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
        f'<p style="margin:0 0 14px 0;font-size:14px;line-height:1.5;text-align:center">'
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
    *,
    any_changed: bool,
) -> tuple[str, str]:
    plain_head, html_head = _detection_time_parts(at_utc)

    plain_lines = [
        plain_head.rstrip("\n"),
        "Crypto\t检测价格\tEMA情况\t成交量情况",
    ]
    rows_html: list[str] = []

    td = "padding:8px 12px;border:1px solid #ddd;text-align:center;vertical-align:middle"
    th = "padding:10px 12px;border:1px solid #ccc;text-align:center"

    for sym in DEFAULT_MARKET_SYMBOLS:
        price_s = _fmt_price(last_close.get(sym))
        tags = current_status[sym]
        ema_ma, ema_price = format_ema_table_lines(tags)
        vol_text = format_volume_table_cell(tags)
        plain_lines.append(
            f"{sym}\t{price_s}\t[8/12/21]{ema_ma}；[价/EMA]{ema_price}\t{vol_text}"
        )

        ema_html = (
            f'<div style="line-height:1.5;text-align:center">'
            f"<div>{escape(ema_ma)}</div>"
            f'<div style="margin-top:6px">{escape(ema_price)}</div>'
            "</div>"
        )
        vol_html = escape(vol_text)
        if vol_text == "成交量上升":
            vol_html = f'<span style="color:#c05621;font-weight:600">{vol_html}</span>'
        row_bg = "#fff8e6" if sym in changed_symbols else "#ffffff"
        rows_html.append(
            f'<tr style="background:{row_bg}">'
            f"<td style='{td}'>{escape(sym)}</td>"
            f"<td style='{td}'>{escape(price_s)}</td>"
            f"<td style='{td}'>{ema_html}</td>"
            f"<td style='{td}'>{vol_html}</td>"
            "</tr>"
        )

    changed_sorted = ", ".join(sorted(changed_symbols))
    plain_lines.append("")
    if any_changed:
        plain_lines.append("说明：浅黄底行为相对上次扫描有变动（价格展示或 EMA/成交量信号）；白底为与上次一致。")
        plain_lines.append(f"有变动的交易对：{changed_sorted}")
    else:
        plain_lines.append("说明：本次相对上次扫描无变动，表格均为白底。")
    plain_body = "\n".join(plain_lines)

    table = (
        '<table style="border-collapse:collapse;font-size:14px;min-width:640px;margin:0 auto">'
        "<thead><tr style='background:#f0f4f8'>"
        f"<th style='{th}'>Crypto</th>"
        f"<th style='{th}'>检测价格</th>"
        f"<th style='{th}'>EMA情况</th>"
        f"<th style='{th}'>成交量情况</th>"
        "</tr></thead><tbody>"
        + "".join(rows_html)
        + "</tbody></table>"
    )
    if any_changed:
        foot_note = (
            "说明：浅黄底行为相对上次扫描有变动（价格展示或 EMA/成交量信号）；白底为与上次一致。<br/>"
            f"<span style='font-size:12px;color:#666'>有变动：{escape(changed_sorted)}</span>"
        )
    else:
        foot_note = "说明：本次相对上次扫描无变动，表格均为白底。"
    foot = (
        f'<p style="margin:14px 0 0 0;font-size:13px;color:#555;text-align:center;line-height:1.6">'
        f"{foot_note}</p>"
    )
    html_body = (
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
        '<body style="font-family:Segoe UI,PingFang SC,Microsoft YaHei,Arial,sans-serif;text-align:center">'
        f"{html_head}{table}{foot}</body></html>"
    )
    return plain_body, html_body


def main() -> None:
    load_config()

    last_snapshots: dict[str, dict[str, object]] = {}
    if LAST_STATUS_PATH.is_file():
        try:
            raw = json.loads(LAST_STATUS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                last_snapshots = _load_last_snapshots(raw)
        except (json.JSONDecodeError, OSError):
            last_snapshots = {}

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
        prev = last_snapshots.get(sym, {"tags": [], "price": ""})
        prev_tags = prev.get("tags", []) if isinstance(prev.get("tags"), list) else []
        prev_tags = [x for x in prev_tags if isinstance(x, str)]
        prev_price = prev.get("price", "")
        if not isinstance(prev_price, str):
            prev_price = ""
        price_s = _fmt_price(last_close.get(sym))
        if current_status[sym] != prev_tags or price_s != prev_price:
            changed_symbols.add(sym)

    any_changed = bool(changed_symbols)
    text_body, html_body = _build_email_bodies(
        detected_at_utc,
        last_close,
        current_status,
        changed_symbols,
        any_changed=any_changed,
    )
    send_email(_MAIL_SUBJECT, text_body, html_body=html_body)

    ordered = {
        sym: {
            "tags": list(current_status[sym]),
            "price": _fmt_price(last_close.get(sym)),
        }
        for sym in DEFAULT_MARKET_SYMBOLS
    }
    LAST_STATUS_PATH.write_text(
        json.dumps(ordered, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
