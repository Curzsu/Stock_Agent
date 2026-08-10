"""Structured individual-stock market data for the analysis workbench."""

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional


DAILY_FIELDS = "date,open,high,low,close,volume,turn,pctChg,peTTM,pbMRQ"
PERIOD_FIELDS = "date,open,high,low,close,volume,turn,pctChg"
ALLOWED_FREQUENCIES = {"d", "w", "m"}


def normalize_stock_code(code: str) -> str:
    value = (code or "").strip().lower()
    if len(value) == 9 and value[:3] in {"sh.", "sz."} and value[3:].isdigit():
        digits = value[3:]
        expected_market = "sh." if digits.startswith("6") else "sz."
        if digits[0] in "036" and value[:3] == expected_market:
            return value
    if len(value) == 6 and value.isdigit() and value[0] in "036":
        return f"{'sh' if value[0] == '6' else 'sz'}.{value}"
    raise ValueError("股票代码格式无效")


def moving_average(values: List[float], window: int) -> List[Optional[float]]:
    result: List[Optional[float]] = []
    for index in range(len(values)):
        if index + 1 < window:
            result.append(None)
        else:
            chunk = values[index + 1 - window:index + 1]
            result.append(round(sum(chunk) / window, 4))
    return result


def _to_float(value: Any) -> Optional[float]:
    if value is None or str(value).strip() in {"", "--", "None"}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_market_payload(code: str, rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    normalized = normalize_stock_code(code)
    usable = []
    for row in sorted((dict(item) for item in rows), key=lambda item: item.get("date", "")):
        candle = {
            "time": row.get("date", ""),
            "open": _to_float(row.get("open")),
            "high": _to_float(row.get("high")),
            "low": _to_float(row.get("low")),
            "close": _to_float(row.get("close")),
            "volume": _to_float(row.get("volume")) or 0.0,
            "turnover": _to_float(row.get("turn")),
            "pct_change": _to_float(row.get("pctChg")),
            "pe_ttm": _to_float(row.get("peTTM")),
            "pb_mrq": _to_float(row.get("pbMRQ")),
        }
        if candle["time"] and all(candle[key] is not None for key in ("open", "high", "low", "close")):
            usable.append(candle)

    if not usable:
        return {"ok": False, "code": normalized, "error": "未获取到个股行情数据"}

    closes = [row["close"] for row in usable]
    ma5 = moving_average(closes, 5)
    ma20 = moving_average(closes, 20)
    candles = []
    for index, row in enumerate(usable):
        candles.append({
            "time": row["time"],
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": row["volume"],
            "ma5": ma5[index],
            "ma20": ma20[index],
        })

    latest = usable[-1]
    return {
        "ok": True,
        "code": normalized,
        "latest_trade_date": latest["time"],
        "quote": {
            "open": latest["open"],
            "high": latest["high"],
            "low": latest["low"],
            "close": latest["close"],
            "volume": latest["volume"],
            "turnover": latest["turnover"],
            "pct_change": latest["pct_change"],
            "pe_ttm": latest["pe_ttm"],
            "pb_mrq": latest["pb_mrq"],
        },
        "candles": candles,
    }


def fetch_stock_market(
    code: str,
    days: int,
    frequency: str,
    ensure_logged_in,
    safe_query,
    bs_module,
) -> Dict[str, Any]:
    """Fetch BaoStock history and return a frontend-ready payload."""
    normalized = normalize_stock_code(code)
    if frequency not in ALLOWED_FREQUENCIES:
        raise ValueError("frequency must be d, w, or m")

    ensure_logged_in()
    lookback_factor = {"d": 2, "w": 9, "m": 40}[frequency]
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days * lookback_factor)).strftime("%Y-%m-%d")
    fields = DAILY_FIELDS if frequency == "d" else PERIOD_FIELDS
    result = safe_query(
        lambda: bs_module.query_history_k_data_plus(
            normalized,
            fields,
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
            adjustflag="3",
        )
    )
    if result.error_code != "0":
        raise RuntimeError(f"baostock 查询失败: {result.error_msg}")

    rows = []
    while result.next():
        rows.append(dict(zip(result.fields, result.get_row_data())))
    return build_market_payload(normalized, rows[-days:])
