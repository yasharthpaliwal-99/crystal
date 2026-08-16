"""
movement_engine.py — per-timeframe market movement state.

On every closed candle (5m / 15m / 30m / 1h) produces:
  - trend              current trend (uptrend | downtrend | ranging | reversal_up | reversal_down)
  - market_level       the key price level (invalidation or broken level)
  - buy_volume         aggressive buy volume inside this candle
  - sell_volume        aggressive sell volume inside this candle
  - candlestick_pattern hammer, doji, engulfing, etc. from OHLC
  - last_hh / last_hl  most recent confirmed HH swing high and HL swing low levels
"""

from collections import deque

MOVEMENT_TIMEFRAMES = {
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
}

SWING_LOOKBACK = 2
MAX_CLOSED_CANDLES = 500


def create_movement_state():
    state = {}
    for label, minutes in MOVEMENT_TIMEFRAMES.items():
        state[label] = {
            "tf_ms": minutes * 60 * 1000,
            "bucket_start": None,
            "current_candle": None,
            "buy_volume": 0.0,
            "sell_volume": 0.0,
            "prev_closed": None,
            "closed_candles": deque(maxlen=MAX_CLOSED_CANDLES),
            "last_swing_high": None,
            "last_swing_high_label": None,
            "last_swing_low": None,
            "last_swing_low_label": None,
            "last_hh": None,
            "last_hl": None,
            "trend": "undefined",
            "market_level": None,
            "market_level_role": None,
            "last_record": None,
        }
    return state


def add_trade(state: dict, ts_sec: float, qty: float, is_buy: bool):
    """Attribute trade volume to every forming candle whose bucket contains ts."""
    ts_ms = int(ts_sec * 1000)
    for tf_state in state.values():
        bucket = tf_state["bucket_start"]
        if bucket is None:
            continue
        if bucket <= ts_ms < bucket + tf_state["tf_ms"]:
            if is_buy:
                tf_state["buy_volume"] += qty
            else:
                tf_state["sell_volume"] += qty


def _start_candle(one_min: dict, bucket_start: int) -> dict:
    return {
        "open_time": bucket_start,
        "open": one_min["open"],
        "high": one_min["high"],
        "low": one_min["low"],
        "close": one_min["close"],
        "volume": one_min["volume"],
    }


def _merge_candle(agg: dict, one_min: dict):
    agg["high"] = max(agg["high"], one_min["high"])
    agg["low"] = min(agg["low"], one_min["low"])
    agg["close"] = one_min["close"]
    agg["volume"] += one_min["volume"]


def _candlestick_pattern(candle: dict, prev: dict = None) -> str:
    """Classify candlestick pattern from OHLC (and previous candle for engulfing)."""
    o, h, l, c = candle["open"], candle["high"], candle["low"], candle["close"]
    total_range = h - l
    if total_range == 0:
        return "flat"

    body = abs(c - o)
    body_pct = body / total_range
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    bullish = c >= o

    # --- Doji family (tiny body) ---
    if body_pct < 0.1:
        if upper_wick > lower_wick * 2:
            return "gravestone_doji"
        if lower_wick > upper_wick * 2:
            return "dragonfly_doji"
        return "doji"

    # --- Hammer / hanging man (long lower wick) ---
    if body > 0 and lower_wick >= body * 2 and upper_wick <= body * 0.5:
        return "hammer" if bullish else "hanging_man"

    # --- Inverted hammer / shooting star (long upper wick) ---
    if body > 0 and upper_wick >= body * 2 and lower_wick <= body * 0.5:
        return "inverted_hammer" if bullish else "shooting_star"

    # --- Engulfing (needs previous candle) ---
    if prev is not None:
        po, pc = prev["open"], prev["close"]
        prev_bullish = pc >= po
        if bullish and not prev_bullish and c >= po and o <= pc:
            return "bullish_engulfing"
        if not bullish and prev_bullish and c <= po and o >= pc:
            return "bearish_engulfing"

    # --- Marubozu (full body, tiny wicks) ---
    if body_pct > 0.85:
        return "bullish_marubozu" if bullish else "bearish_marubozu"

    # --- Spinning top (small body, wicks both sides) ---
    if body_pct < 0.35 and upper_wick > body * 0.5 and lower_wick > body * 0.5:
        return "spinning_top"

    return "bullish" if bullish else "bearish"


def _swing_label(price: float, prev_price, swing_type: str):
    if prev_price is None:
        return None
    if swing_type == "high":
        if price > prev_price:
            return "HH"
        if price < prev_price:
            return "LH"
        return "EH"
    if price > prev_price:
        return "HL"
    if price < prev_price:
        return "LL"
    return "EL"


def _confirm_swings(tf_state: dict) -> list:
    """n+2 swing confirmation. Returns newly confirmed swings this candle."""
    confirmed = []
    candles = list(tf_state["closed_candles"])
    n = SWING_LOOKBACK
    if len(candles) < (2 * n + 1):
        return confirmed

    idx = len(candles) - 1 - n
    window = candles[idx - n: idx + n + 1]
    candidate = candles[idx]

    if all(candidate["high"] >= c["high"] for c in window):
        label = _swing_label(candidate["high"], tf_state["last_swing_high"], "high")
        tf_state["last_swing_high"] = candidate["high"]
        tf_state["last_swing_high_label"] = label
        if label == "HH":
            tf_state["last_hh"] = candidate["high"]
        confirmed.append({
            "type": "high",
            "label": label,
            "price": candidate["high"],
            "pivot_time": candidate["open_time"],
        })

    if all(candidate["low"] <= c["low"] for c in window):
        label = _swing_label(candidate["low"], tf_state["last_swing_low"], "low")
        tf_state["last_swing_low"] = candidate["low"]
        tf_state["last_swing_low_label"] = label
        if label == "HL":
            tf_state["last_hl"] = candidate["low"]
        confirmed.append({
            "type": "low",
            "label": label,
            "price": candidate["low"],
            "pivot_time": candidate["open_time"],
        })

    return confirmed


def _resolve_trend(tf_state: dict, closed: dict):
    """
    Determine trend, market_level, and any event on this candle close.

    Reversal takes priority — break of HL or LH is the market signal.
    """
    close = closed["close"]
    event = None
    trend = tf_state["trend"]
    level = tf_state["market_level"]
    role = tf_state["market_level_role"]

    swing_high = tf_state["last_swing_high"]
    swing_low = tf_state["last_swing_low"]
    high_label = tf_state["last_swing_high_label"]
    low_label = tf_state["last_swing_low_label"]

    # --- Reversal: break below HL (bearish) ---
    if swing_low is not None and low_label == "HL" and close < swing_low:
        event = "reversal_down"
        trend = "reversal_down"
        level = swing_low
        role = "broken_HL"

    # --- Reversal: break above LH (bullish) ---
    elif swing_high is not None and high_label == "LH" and close > swing_high:
        event = "reversal_up"
        trend = "reversal_up"
        level = swing_high
        role = "broken_LH"

    # --- Continuation structure ---
    elif high_label == "HH" and low_label == "HL":
        trend = "uptrend"
        level = swing_low
        role = "invalidation_HL"

    elif high_label == "LH" and low_label == "LL":
        trend = "downtrend"
        level = swing_high
        role = "invalidation_LH"

    else:
        if trend not in ("reversal_up", "reversal_down"):
            trend = "ranging"
        if swing_low is not None and low_label == "HL":
            level = swing_low
            role = "support_HL"
        elif swing_high is not None and high_label == "LH":
            level = swing_high
            role = "resistance_LH"
        else:
            level = swing_high or swing_low
            role = "key_level"

    tf_state["trend"] = trend
    tf_state["market_level"] = level
    tf_state["market_level_role"] = role

    return event


def _process_closed(tf_state: dict, closed: dict) -> dict:
    """Build the movement record for one closed candle."""
    buy_vol = tf_state["buy_volume"]
    sell_vol = tf_state["sell_volume"]
    prev = tf_state["prev_closed"]

    pattern = _candlestick_pattern(closed, prev)

    tf_state["closed_candles"].append(closed)
    swing_confirmed = _confirm_swings(tf_state)
    event = _resolve_trend(tf_state, closed)

    # Pick the most recent swing confirmation on this candle (if any)
    sc = swing_confirmed[-1] if swing_confirmed else None

    record = {
        "open_time": closed["open_time"],
        "close_time": closed.get("close_time"),
        "open": closed["open"],
        "high": closed["high"],
        "low": closed["low"],
        "close": closed["close"],
        "volume": closed["volume"],
        "buy_volume": round(buy_vol, 6),
        "sell_volume": round(sell_vol, 6),
        "candlestick_pattern": pattern,
        "swing_high": tf_state["last_swing_high"],
        "swing_high_label": tf_state["last_swing_high_label"],
        "swing_low": tf_state["last_swing_low"],
        "swing_low_label": tf_state["last_swing_low_label"],
        "last_hh": tf_state["last_hh"],
        "last_hl": tf_state["last_hl"],
        "trend": tf_state["trend"],
        "market_level": tf_state["market_level"],
        "market_level_role": tf_state["market_level_role"],
        "swing_confirmed_type": sc["type"] if sc else None,
        "swing_confirmed_label": sc["label"] if sc else None,
        "swing_confirmed_price": sc["price"] if sc else None,
        "swing_confirmed": swing_confirmed,
        "event": event,
    }

    tf_state["prev_closed"] = closed
    tf_state["last_record"] = record
    tf_state["buy_volume"] = 0.0
    tf_state["sell_volume"] = 0.0
    return record


def add_1m_candle(state: dict, one_min: dict) -> list:
    """
    Feed one closed 1-min candle. Returns list of (timeframe, movement_record)
    for every higher-TF candle that closed.
    """
    results = []

    for label, tf_state in state.items():
        tf_ms = tf_state["tf_ms"]
        bucket_start = one_min["open_time"] - (one_min["open_time"] % tf_ms)

        if tf_state["bucket_start"] is None:
            tf_state["bucket_start"] = bucket_start
            tf_state["current_candle"] = _start_candle(one_min, bucket_start)

        elif bucket_start == tf_state["bucket_start"]:
            _merge_candle(tf_state["current_candle"], one_min)

        else:
            closed = tf_state["current_candle"]
            closed["close_time"] = tf_state["bucket_start"] + tf_ms
            results.append((label, _process_closed(tf_state, closed)))

            tf_state["bucket_start"] = bucket_start
            tf_state["current_candle"] = _start_candle(one_min, bucket_start)

    return results


def movement_snapshot(state: dict) -> dict:
    """Current movement state per timeframe — for Redis live payload."""
    out = {}
    for label, tf_state in state.items():
        rec = tf_state["last_record"]
        cur = tf_state["current_candle"]

        out[label] = {
            "trend": tf_state["trend"],
            "market_level": tf_state["market_level"],
            "market_level_role": tf_state["market_level_role"],
            "lastHH": tf_state["last_hh"],
            "lastHL": tf_state["last_hl"],
            "swing_high": tf_state["last_swing_high"],
            "swing_high_label": tf_state["last_swing_high_label"],
            "swing_low": tf_state["last_swing_low"],
            "swing_low_label": tf_state["last_swing_low_label"],
            "lastCandleOpen": rec["open"] if rec else None,
            "lastCandleClose": rec["close"] if rec else None,
            "lastCandleBuyVolume": rec["buy_volume"] if rec else None,
            "lastCandleSellVolume": rec["sell_volume"] if rec else None,
            "lastCandleShape": rec["candlestick_pattern"] if rec else None,
            "last_candle": {
                "open_time": rec["open_time"],
                "open": rec["open"],
                "high": rec["high"],
                "low": rec["low"],
                "close": rec["close"],
                "buy_volume": rec["buy_volume"],
                "sell_volume": rec["sell_volume"],
                "candlestick_pattern": rec["candlestick_pattern"],
                "swing_confirmed_label": rec["swing_confirmed_label"],
                "swing_confirmed_price": rec["swing_confirmed_price"],
                "event": rec["event"],
            } if rec else None,
            "forming_candle": {
                "open_time": cur["open_time"] if cur else None,
                "buy_volume": round(tf_state["buy_volume"], 6),
                "sell_volume": round(tf_state["sell_volume"], 6),
            } if cur else None,
        }
    return out
