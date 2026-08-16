"""
strategy_engine.py — frozen strategy logic for all 5 bots.

Step 1: Price action (direction, entry level, candle shape)
Step 2: Order flow (aggression ratio, withdrawal ratio, consumption vs liquidity)
"""

from bot_config import TIMEFRAMES, ENTRY_TIMEFRAME, ENTRY_TOLERANCE_PCT

BULLISH_TRENDS = frozenset({"uptrend", "reversal_up"})
BEARISH_TRENDS = frozenset({"downtrend", "reversal_down"})

BULLISH_PATTERNS = frozenset({
    "bullish", "hammer", "inverted_hammer",
    "bullish_engulfing", "bullish_marubozu", "dragonfly_doji",
})

BEARISH_PATTERNS = frozenset({
    "bearish", "hanging_man", "shooting_star",
    "bearish_engulfing", "bearish_marubozu", "gravestone_doji",
})


def _near_level(price: float, level: float) -> bool:
    if price is None or level is None or level == 0:
        return False
    return abs(price - level) / level <= ENTRY_TOLERANCE_PCT


def _tf_bullish(tf: dict) -> bool:
    return tf.get("trend") in BULLISH_TRENDS


def _tf_bearish(tf: dict) -> bool:
    return tf.get("trend") in BEARISH_TRENDS


def _candle_bullish(tf: dict) -> bool:
    shape = tf.get("lastCandleShape")
    return shape in BULLISH_PATTERNS if shape else False


def _candle_bearish(tf: dict) -> bool:
    shape = tf.get("lastCandleShape")
    return shape in BEARISH_PATTERNS if shape else False


def _buy_entry_level(tf: dict) -> float | None:
    """BUY entry reference: last HL support, else market_level if support role."""
    if tf.get("lastHL"):
        return tf["lastHL"]
    role = tf.get("market_level_role") or ""
    if "HL" in role or "support" in role:
        return tf.get("market_level")
    return tf.get("swing_low")


def _sell_entry_level(tf: dict) -> float | None:
    """SELL entry reference: last LH resistance, else market_level if resistance role."""
    if tf.get("swing_high_label") == "LH" and tf.get("swing_high"):
        return tf["swing_high"]
    role = tf.get("market_level_role") or ""
    if "LH" in role or "resistance" in role:
        return tf.get("market_level")
    return tf.get("swing_high")


def evaluate_price_action(movement: dict) -> dict:
    """
    Returns setup dict with side ('buy'|'sell'|None) and per-check breakdown.
    """
    if not movement:
        return {"side": None, "passed": False, "reason": "no_movement_data"}

    tfs = {tf: movement.get(tf) for tf in TIMEFRAMES}
    if any(tfs[tf] is None for tf in TIMEFRAMES):
        return {"side": None, "passed": False, "reason": "missing_timeframe"}

    all_bullish = all(_tf_bullish(tfs[tf]) for tf in TIMEFRAMES)
    all_bearish = all(_tf_bearish(tfs[tf]) for tf in TIMEFRAMES)

    if not all_bullish and not all_bearish:
        return {
            "side": None,
            "passed": False,
            "reason": "timeframes_not_aligned",
            "trends": {tf: tfs[tf].get("trend") for tf in TIMEFRAMES},
        }

    entry_tf = tfs[ENTRY_TIMEFRAME]
    price = entry_tf.get("lastCandleClose") or entry_tf.get("last_candle", {}).get("close")

    if all_bullish:
        if not _candle_bullish(entry_tf):
            return {
                "side": "buy",
                "passed": False,
                "reason": "candle_not_bullish",
                "shape": entry_tf.get("lastCandleShape"),
            }
        entry_level = _buy_entry_level(entry_tf)
        if not _near_level(price, entry_level):
            return {
                "side": "buy",
                "passed": False,
                "reason": "price_not_at_entry_level",
                "price": price,
                "entry_level": entry_level,
            }
        return {
            "side": "buy",
            "passed": True,
            "price": price,
            "entry_level": entry_level,
            "shape": entry_tf.get("lastCandleShape"),
            "trends": {tf: tfs[tf].get("trend") for tf in TIMEFRAMES},
        }

    # all bearish
    if not _candle_bearish(entry_tf):
        return {
            "side": "sell",
            "passed": False,
            "reason": "candle_not_bearish",
            "shape": entry_tf.get("lastCandleShape"),
        }
    entry_level = _sell_entry_level(entry_tf)
    if not _near_level(price, entry_level):
        return {
            "side": "sell",
            "passed": False,
            "reason": "price_not_at_entry_level",
            "price": price,
            "entry_level": entry_level,
        }
    return {
        "side": "sell",
        "passed": True,
        "price": price,
        "entry_level": entry_level,
        "shape": entry_tf.get("lastCandleShape"),
        "trends": {tf: tfs[tf].get("trend") for tf in TIMEFRAMES},
    }


def _zone_metrics(zone: dict, side: str) -> dict:
    buy = zone.get("buy_aggression") or 0.0
    sell = zone.get("sell_aggression") or 0.0
    bid_liq = zone.get("bid_liquidity") or 0.0
    ask_liq = zone.get("ask_liquidity") or 0.0
    bid_cons = zone.get("bid_consumption") or 0.0
    ask_cons = zone.get("ask_consumption") or 0.0
    bid_with = zone.get("bid_withdrawal") or 0.0
    ask_with = zone.get("ask_withdrawal") or 0.0

    if side == "buy":
        agg_ratio = buy / sell if sell > 0 else (float("inf") if buy > 0 else 0.0)
        withdraw_ratio = ask_with / ask_liq if ask_liq > 0 else 0.0
    else:
        agg_ratio = sell / buy if buy > 0 else (float("inf") if sell > 0 else 0.0)
        withdraw_ratio = bid_with / bid_liq if bid_liq > 0 else 0.0

    return {
        "aggression_ratio": round(agg_ratio, 4) if agg_ratio != float("inf") else None,
        "withdrawal_ratio": round(withdraw_ratio, 4),
        "buy_aggression": buy,
        "sell_aggression": sell,
        "bid_liquidity": bid_liq,
        "ask_liquidity": ask_liq,
        "bid_consumption": bid_cons,
        "ask_consumption": ask_cons,
        "bid_withdrawal": bid_with,
        "ask_withdrawal": ask_with,
    }


def _order_flow_passes(metrics: dict, side: str, bot: dict) -> tuple[bool, str]:
    agg = metrics.get("aggression_ratio")
    wdr = metrics.get("withdrawal_ratio")

    if agg is None or agg < bot["aggression_ratio_min"]:
        return False, f"aggression_ratio {agg} < {bot['aggression_ratio_min']}"

    if wdr < bot["withdrawal_ratio_min"]:
        return False, f"withdrawal_ratio {wdr:.2%} < {bot['withdrawal_ratio_min']:.0%}"

    buy = metrics["buy_aggression"]
    sell = metrics["sell_aggression"]
    bid_cons = metrics["bid_consumption"]
    ask_cons = metrics["ask_consumption"]
    bid_with = metrics["bid_withdrawal"]
    ask_with = metrics["ask_withdrawal"]

    if side == "buy":
        if buy <= sell:
            return False, "buy_aggression not > sell_aggression"
        if ask_cons <= bid_cons:
            return False, "ask_consumption not > bid_consumption"
        if ask_with <= 0:
            return False, "no ask_withdrawal"
        if ask_cons <= 0:
            return False, "no ask_consumption"
    else:
        if sell <= buy:
            return False, "sell_aggression not > buy_aggression"
        if bid_cons <= ask_cons:
            return False, "bid_consumption not > ask_consumption"
        if bid_with <= 0:
            return False, "no bid_withdrawal"
        if bid_cons <= 0:
            return False, "no bid_consumption"

    return True, "ok"


def evaluate_bot(movement: dict, zone: dict, bot: dict) -> dict:
    """Full evaluation for one bot. Returns signal with enter/wait and full audit trail."""
    pa = evaluate_price_action(movement)
    result = {
        "bot": bot["name"],
        "action": "WAIT",
        "side": pa.get("side"),
        "price_action": pa,
        "order_flow": None,
        "metrics": None,
        "reason": pa.get("reason"),
    }

    if not pa.get("passed"):
        return result

    if not zone:
        result["reason"] = "no_zone_data"
        return result

    metrics = _zone_metrics(zone, pa["side"])
    flow_ok, flow_reason = _order_flow_passes(metrics, pa["side"], bot)

    result["order_flow"] = {"passed": flow_ok, "reason": flow_reason}
    result["metrics"] = metrics

    if flow_ok:
        result["action"] = "ENTER"
        result["side"] = pa["side"]
        result["price"] = zone.get("current_price") or pa.get("price")
        result["entry_level"] = pa.get("entry_level")
        result["zone_low"] = zone.get("zone_low")
        result["zone_high"] = zone.get("zone_high")
        result["reason"] = "all_conditions_met"
    else:
        result["reason"] = flow_reason

    return result
