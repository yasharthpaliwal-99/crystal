"""
liquidity_engine.py — tracks where resting liquidity is concentrated,
bucketed by price, over a rolling time window. This is what answers
"where is liquidity building up right now."
"""

from collections import deque


def create_liquidity_state(bucket_size: float = 10.0, window_seconds: float = 300, sample_interval: float = 1.0):
    return {
        "bucket_size": bucket_size,
        "window_seconds": window_seconds,
        "sample_interval": sample_interval,
        "samples": deque(),  # (ts, {bucket_price: liquidity})
        "last_sample_ts": 0.0,
    }


def _bucket_price(price: float, bucket_size: float) -> float:
    return round(price / bucket_size) * bucket_size


def observe_liquidity(state: dict, bids: dict, asks: dict, ts: float):
    if ts - state["last_sample_ts"] < state["sample_interval"]:
        return
    state["last_sample_ts"] = ts

    bucket_size = state["bucket_size"]
    buckets = {}
    for price, qty in bids.items():
        b = _bucket_price(price, bucket_size)
        buckets[b] = buckets.get(b, 0.0) + qty
    for price, qty in asks.items():
        b = _bucket_price(price, bucket_size)
        buckets[b] = buckets.get(b, 0.0) + qty

    state["samples"].append((ts, buckets))

    cutoff = ts - state["window_seconds"]
    samples = state["samples"]
    while samples and samples[0][0] < cutoff:
        samples.popleft()


def liquidity_zones(state: dict, top_n: int = 5):
    """Ranked price buckets by accumulated liquidity across the whole
    window — where size has been sitting, not just a one-off snapshot."""
    totals = {}
    for _, buckets in state["samples"]:
        for price, qty in buckets.items():
            totals[price] = totals.get(price, 0.0) + qty
    if not totals:
        return []
    ranked = sorted(totals.items(), key=lambda x: -x[1])[:top_n]
    return [{"price_zone": p, "liquidity_score": round(q, 2)} for p, q in ranked]


# ---------------------------------------------------------------------------
# Order book state — depth messages are DIFFS, not the full book. This
# maintains the accumulated state so liquidity_zones() reads real resting
# liquidity, not just whatever changed in the last message.
# ---------------------------------------------------------------------------

def create_book():
    return {"bids": {}, "asks": {}}


def apply_diff(book: dict, bids: list, asks: list):
    for price, qty in bids:
        price, qty = float(price), float(qty)
        if qty == 0.0:
            book["bids"].pop(price, None)
        else:
            book["bids"][price] = qty
    for price, qty in asks:
        price, qty = float(price), float(qty)
        if qty == 0.0:
            book["asks"].pop(price, None)
        else:
            book["asks"][price] = qty