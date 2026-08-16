"""
feature_engine.py — trades only, for now. Plain functions + dicts, no classes.

Gives you, per time window:
  - buy_volume, sell_volume, total_volume
  - buy_sell_ratio
  - imbalance (normalized, -1 to +1)
  - large trade count + the current large-trade threshold
"""

from collections import deque

# Add or remove windows here — label: seconds. Everything below (buy/sell
# tracking, imbalance, large trade counting) automatically works for
# whatever you put in this dict, no other code needs to change.
WINDOWS = {
    "5s": 5,
    "1m": 60,
    "5m": 300,
    "30m": 1800,
    "1h": 3600,
}

LARGE_TRADE_PERCENTILE = 99
LARGE_TRADE_SAMPLE_SIZE = 2000
LARGE_TRADE_RECOMPUTE_SEC = 2.0


def create_flow_state():
    windows = {}
    for label, seconds in WINDOWS.items():
        windows[label] = {
            "seconds": seconds,
            "trades": deque(),   # (ts, qty, is_buy, is_large)
            "buy_vol": 0.0,
            "sell_vol": 0.0,
            "large_count": 0,
        }
    return {
        "windows": windows,
        "size_samples": deque(maxlen=LARGE_TRADE_SAMPLE_SIZE),
        "large_threshold": None,
        "last_threshold_calc": 0.0,
    }


def _evict(window: dict, now_ts: float):
    cutoff = now_ts - window["seconds"]
    trades = window["trades"]
    while trades and trades[0][0] < cutoff:
        _, qty, is_buy, is_large = trades.popleft()
        if is_buy:
            window["buy_vol"] -= qty
        else:
            window["sell_vol"] -= qty
        if is_large:
            window["large_count"] -= 1


def _update_large_trade_threshold(state: dict, qty: float, ts: float):
    state["size_samples"].append(qty)
    samples = state["size_samples"]

    if len(samples) < 50:
        return
    if state["large_threshold"] is None or (ts - state["last_threshold_calc"]) > LARGE_TRADE_RECOMPUTE_SEC:
        sorted_samples = sorted(samples)
        idx = min(int(len(sorted_samples) * LARGE_TRADE_PERCENTILE / 100), len(sorted_samples) - 1)
        state["large_threshold"] = sorted_samples[idx]
        state["last_threshold_calc"] = ts


def add_trade(state: dict, ts: float, qty: float, is_buyer_maker: bool):
    # isBuyerMaker True -> resting order was a buy -> aggressor was the SELLER
    is_buy = not is_buyer_maker

    _update_large_trade_threshold(state, qty, ts)
    is_large = state["large_threshold"] is not None and qty > state["large_threshold"]

    for window in state["windows"].values():
        window["trades"].append((ts, qty, is_buy, is_large))
        if is_buy:
            window["buy_vol"] += qty
        else:
            window["sell_vol"] += qty
        if is_large:
            window["large_count"] += 1
        _evict(window, ts)


def flow_snapshot(state: dict):
    out = {"large_trade_threshold": state["large_threshold"]}

    for label, window in state["windows"].items():
        buy_vol = window["buy_vol"]
        sell_vol = window["sell_vol"]
        total = buy_vol + sell_vol

        out[f"buy_volume_{label}"] = round(buy_vol, 6)
        out[f"sell_volume_{label}"] = round(sell_vol, 6)
        out[f"total_volume_{label}"] = round(total, 6)
        out[f"buy_sell_ratio_{label}"] = round(buy_vol / sell_vol, 4) if sell_vol > 0 else None
        out[f"imbalance_{label}"] = round((buy_vol - sell_vol) / total, 4) if total > 0 else 0.0
        out[f"large_trade_count_{label}"] = window["large_count"]

    return out