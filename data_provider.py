"""从外部源拉取并整理数据。

扩展方式：实现 ``MarketDataPort`` 协议（``fetch_ohlcv``），在 ``fetch_data(..., port=你的实现)`` 中注入即可。
"""

from __future__ import annotations

import requests
import pandas as pd
from typing import Protocol, runtime_checkable

from config_loader import AppConfig

# 默认批量拉取顺序（与 SUPPORTED 集合一致，便于结果稳定可复现）
DEFAULT_MARKET_SYMBOLS: tuple[str, ...] = (
    "BTC-USDT",
    "ETH-USDT",
    "OKB-USDT",
    "SOL-USDT",
    "ADA-USDT",
    "DOGE-USDT",
    "XRP-USDT",
)

SUPPORTED_SYMBOLS: frozenset[str] = frozenset(DEFAULT_MARKET_SYMBOLS)

_DEFAULT_KLINE_LIMIT = 100

_OKX_REST_BASE = "https://www.okx.com"
_CANDLE_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
_MERGED_COLUMNS = ["symbol", *_CANDLE_COLUMNS]

# 多数据源约定：纵向合并后的标准列名（实现 MarketDataPort 时应尽量对齐）
OHLCV_LONG_COLUMNS: tuple[str, ...] = tuple(_MERGED_COLUMNS)


@runtime_checkable
class MarketDataPort(Protocol):
    """
    行情数据端口：后续接入 Binance、CoinGecko 等 API 时，实现本协议并传给 ``fetch_data``。
    """

    def fetch_ohlcv(
        self,
        config: AppConfig,
        *,
        symbols: tuple[str, ...],
        limit: int,
    ) -> pd.DataFrame:
        """
        返回长表，列建议与 ``OHLCV_LONG_COLUMNS`` 一致：
        symbol（字符串）, timestamp, open, high, low, close, volume（float64）。
        """


def _merge_candle_chunks(parts: list[pd.DataFrame]) -> pd.DataFrame:
    if not parts:
        return pd.DataFrame(columns=_MERGED_COLUMNS).astype(
            {c: "float64" for c in _CANDLE_COLUMNS} | {"symbol": "string"}
        )
    out = pd.concat(parts, ignore_index=True)
    out = out.sort_values(["timestamp", "symbol"], ascending=True).reset_index(drop=True)
    out["symbol"] = out["symbol"].astype("string")
    for c in _CANDLE_COLUMNS:
        out[c] = out[c].astype("float64")
    return out


class OKXProvider:
    """通过 OKX 公共 REST API 拉取 K 线（无需 API Key）。"""

    def __init__(self, timeout: float = 20.0) -> None:
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.setdefault(
            "User-Agent",
            "CryptoMonitor/1.0 (+https://www.okx.com)",
        )

    def get_candles(
        self,
        symbol: str,
        *,
        limit: int = 100,
    ) -> pd.DataFrame:
        """
        获取 15m K 线。返回列：timestamp, open, high, low, close, volume，均为 float64。
        """
        inst = symbol.strip().upper()
        if inst not in SUPPORTED_SYMBOLS:
            raise ValueError(
                f"不支持的交易对 {symbol!r}，允许: {sorted(SUPPORTED_SYMBOLS)}"
            )

        lim = max(1, min(int(limit), 300))
        url = f"{_OKX_REST_BASE}/api/v5/market/candles"
        params = {"instId": inst, "bar": "15m", "limit": lim}
        resp = self._session.get(url, params=params, timeout=self._timeout)
        resp.raise_for_status()
        body = resp.json()
        if str(body.get("code", "")) != "0":
            raise RuntimeError(body.get("msg") or str(body))

        raw = body.get("data") or []
        if not raw:
            return pd.DataFrame(columns=_CANDLE_COLUMNS).astype("float64")

        rows: list[dict[str, float]] = []
        for item in raw:
            # [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
            ts, o, h, low, c, vol = item[0], item[1], item[2], item[3], item[4], item[5]
            rows.append(
                {
                    "timestamp": float(ts),
                    "open": float(o),
                    "high": float(h),
                    "low": float(low),
                    "close": float(c),
                    "volume": float(vol),
                }
            )

        df = pd.DataFrame(rows, columns=_CANDLE_COLUMNS)
        df = df.sort_values("timestamp", ascending=True).reset_index(drop=True)
        return df.astype("float64")


class OKXMarketDataPort:
    """OKX 实现的 ``MarketDataPort``（公共 K 线；需要密钥的私有接口可在此类中扩展）。"""

    def __init__(self, client: OKXProvider | None = None) -> None:
        self._client = client if client is not None else OKXProvider()

    def fetch_ohlcv(
        self,
        config: AppConfig,
        *,
        symbols: tuple[str, ...],
        limit: int,
    ) -> pd.DataFrame:
        parts: list[pd.DataFrame] = []
        for sym in symbols:
            chunk = self._client.get_candles(sym, limit=limit)
            chunk.insert(0, "symbol", sym)
            parts.append(chunk)
        return _merge_candle_chunks(parts)


def fetch_data(
    config: AppConfig,
    *,
    port: MarketDataPort | None = None,
    symbols: tuple[str, ...] = DEFAULT_MARKET_SYMBOLS,
    limit: int = _DEFAULT_KLINE_LIMIT,
) -> pd.DataFrame:
    """
    通过 ``port`` 拉取多币种 K 线并合并为长表；未指定时使用 ``OKXMarketDataPort``。

    接入其它数据源：实现 ``MarketDataPort``，例如
    ``fetch_data(config, port=YourApiPort())``。
    """
    adapter: MarketDataPort = port if port is not None else OKXMarketDataPort()
    return adapter.fetch_ohlcv(config, symbols=symbols, limit=limit)


if __name__ == "__main__":
    import sys

    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    # 本地快速验证：公共行情无需真实密钥，占位即可
    _dummy = AppConfig(
        okx_api_key="-",
        okx_api_secret="-",
        okx_passphrase="-",
        qq_mail_account="-",
        qq_mail_auth_code="-",
        qq_mail_to="-",
    )
    _btc_only: tuple[str, ...] = ("BTC-USDT",)
    _n = 5
    _df = fetch_data(_dummy, symbols=_btc_only, limit=_n)
    print("列名:", list(_df.columns))
    print("期望列名:", list(OHLCV_LONG_COLUMNS))
    print(f"\nBTC-USDT 最近 {_n} 根 15m K 线：")
    print(_df.tail(_n).to_string(index=False))
