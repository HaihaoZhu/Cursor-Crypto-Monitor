"""策略与条件判断逻辑。"""

from __future__ import annotations

from typing import Any

import pandas as pd

# 与 TrendScanner 约定：至少该根数再输出标签，避免 EMA/MA10 未稳定
TREND_SCAN_MIN_BARS = 30

# 邮件「EMA情况」列：均线间关系（8/12/21）与价格相对 EMA8，分两行展示
EMA_MA_RELATION_TAGS: frozenset[str] = frozenset(
    {"8>12", "8>21", "12>21", "12>8"},
)
EMA_PRICE_VS_TAGS: frozenset[str] = frozenset(
    {"价格高于8EMA", "价格低于8EMA"},
)
EMA_TABLE_TAGS: frozenset[str] = EMA_MA_RELATION_TAGS | EMA_PRICE_VS_TAGS


def format_ema_table_lines(tags: list[str]) -> tuple[str, str]:
    """
    返回 (8/12/21 均线关系文案, 价格与 EMA8 关系文案)。
    顺序与 ``TrendScanner.get_signals`` 返回列表一致（已排序）。
    """
    ma_parts = [t for t in tags if t in EMA_MA_RELATION_TAGS]
    price_parts = [t for t in tags if t in EMA_PRICE_VS_TAGS]
    line_ma = ", ".join(ma_parts) if ma_parts else "—"
    line_price = ", ".join(price_parts) if price_parts else "—"
    return line_ma, line_price


def format_volume_table_cell(tags: list[str]) -> str:
    """邮件表格「成交量情况」列：有「成交量激增」标签则为上升，否则正常。"""
    if "成交量激增" in tags:
        return "成交量上升"
    return "正常"


def evaluate(data: pd.DataFrame) -> dict[str, Any]:
    """
    根据 data 计算信号或状态。
    若含 ``symbol`` 列（``fetch_data`` 长表），按交易对分别扫描；否则整表视为单序列。
    返回包含 ``should_notify``、``message``、``signals_by_symbol``。
    """
    empty: dict[str, Any] = {
        "should_notify": False,
        "message": "",
        "signals_by_symbol": {},
    }
    if data is None or data.empty:
        return empty

    signals_by_symbol: dict[str, list[str]] = {}
    if "symbol" in data.columns:
        for sym, g in data.groupby("symbol", sort=True):
            sub = g.drop(columns=["symbol"])
            signals_by_symbol[str(sym)] = TrendScanner(sub).get_signals()
    else:
        missing = [c for c in TrendScanner._REQUIRED_COLS if c not in data.columns]
        if missing:
            return {
                **empty,
                "message": f"缺少列: {missing}",
            }
        signals_by_symbol["single"] = TrendScanner(data).get_signals()

    lines = [f"{s}: {', '.join(tags)}" for s, tags in signals_by_symbol.items() if tags]
    message = "\n".join(lines)
    return {
        "should_notify": bool(message),
        "message": message,
        "signals_by_symbol": signals_by_symbol,
    }


class TrendScanner:
    """
    基于单币种 OHLCV（与 ``OKXProvider.get_candles`` 返回列一致）扫描趋势相关标签。
    少于 ``TREND_SCAN_MIN_BARS`` 根 K 线时不输出标签。
    """

    _REQUIRED_COLS = ("timestamp", "open", "high", "low", "close", "volume")

    def __init__(self, df: pd.DataFrame) -> None:
        missing = [c for c in self._REQUIRED_COLS if c not in df.columns]
        if missing:
            raise ValueError(f"DataFrame 缺少列: {missing}")
        self._df = df.loc[:, list(self._REQUIRED_COLS)].copy()
        self._add_indicators()

    def _add_indicators(self) -> None:
        c = self._df["close"]
        v = self._df["volume"]
        self._df["ema8"] = c.ewm(span=8, adjust=False).mean()
        self._df["ema12"] = c.ewm(span=12, adjust=False).mean()
        self._df["ema21"] = c.ewm(span=21, adjust=False).mean()
        self._df["vol_ma10"] = v.rolling(window=10, min_periods=10).mean()

    @staticmethod
    def _left_gt_right_or_cross(
        df: pd.DataFrame,
        i: int,
        left: str,
        right: str,
    ) -> bool:
        """当前 bar 满足 left > right，或本 bar 刚完成由下/相等转为 left > right。"""
        l_now = df[left].iloc[i]
        r_now = df[right].iloc[i]
        if pd.isna(l_now) or pd.isna(r_now):
            return False
        if l_now > r_now:
            return True
        if i < 1:
            return False
        l_prev = df[left].iloc[i - 1]
        r_prev = df[right].iloc[i - 1]
        if pd.isna(l_prev) or pd.isna(r_prev):
            return False
        crossed_up = (l_prev <= r_prev) and (l_now > r_now)
        return crossed_up

    def get_signals(self) -> list[str]:
        """返回去重、按字符串排序后的信号标签列表（基于最后一根有效 K 线）。"""
        tags: set[str] = set()
        df = self._df
        n = len(df)
        if n == 0 or n < TREND_SCAN_MIN_BARS:
            return []

        i = n - 1
        row = df.iloc[i]

        vma = df["vol_ma10"]
        vol = df["volume"]
        if pd.notna(vma.iloc[i]) and vol.iloc[i] > vma.iloc[i] * 1.5:
            tags.add("成交量激增")
        if (
            i >= 1
            and pd.notna(vma.iloc[i - 1])
            and vol.iloc[i - 1] > vma.iloc[i - 1] * 1.5
        ):
            tags.add("成交量激增")

        ema8 = row["ema8"]
        close = row["close"]
        if pd.notna(ema8) and pd.notna(close):
            if close > ema8:
                tags.add("价格高于8EMA")
            elif close < ema8:
                tags.add("价格低于8EMA")

        if self._left_gt_right_or_cross(df, i, "ema8", "ema12"):
            tags.add("8>12")
        if self._left_gt_right_or_cross(df, i, "ema8", "ema21"):
            tags.add("8>21")
        if self._left_gt_right_or_cross(df, i, "ema12", "ema21"):
            tags.add("12>21")
        if self._left_gt_right_or_cross(df, i, "ema12", "ema8"):
            tags.add("12>8")

        return sorted(tags)
