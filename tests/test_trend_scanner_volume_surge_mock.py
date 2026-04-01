"""
Mock 数据测试：构造一根成交量远大于 MA10*1.5 的 K 线，确认出现「成交量激增」标签。
"""

from __future__ import annotations

import unittest

import pandas as pd

from strategy import TREND_SCAN_MIN_BARS, TrendScanner


def make_mock_ohlcv_with_volume_spike(
    n: int = TREND_SCAN_MIN_BARS,
    *,
    base_volume: float = 10.0,
    spike_volume: float = 50_000.0,
) -> pd.DataFrame:
    """
    前 n-1 根成交量恒为 base_volume，最后一根为 spike_volume。
    价格近似横盘，满足 TrendScanner 最少 K 线数。
    """
    rows: list[dict[str, float]] = []
    price = 100.0
    ts0 = 1_700_000_000_000.0
    step_ms = 900_000.0  # 15m
    for i in range(n):
        vol = spike_volume if i == n - 1 else base_volume
        rows.append(
            {
                "timestamp": ts0 + i * step_ms,
                "open": price,
                "high": price + 0.5,
                "low": price - 0.5,
                "close": price,
                "volume": vol,
            }
        )
    return pd.DataFrame(rows)


class TestTrendScannerVolumeSurgeMock(unittest.TestCase):
    def test_huge_volume_last_candle_emits_volume_surge(self) -> None:
        df = make_mock_ohlcv_with_volume_spike()
        self.assertGreaterEqual(len(df), TREND_SCAN_MIN_BARS)

        tags = TrendScanner(df).get_signals()
        self.assertIn(
            "成交量激增",
            tags,
            msg=f"期望含「成交量激增」，实际标签: {tags}",
        )

    def test_baseline_no_spike_no_volume_surge(self) -> None:
        """对照：全程小成交量时不应因成交量规则打出「成交量激增」。"""
        df = make_mock_ohlcv_with_volume_spike(spike_volume=10.0)
        tags = TrendScanner(df).get_signals()
        self.assertNotIn("成交量激增", tags)


if __name__ == "__main__":
    unittest.main()
