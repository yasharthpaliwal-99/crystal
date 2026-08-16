"""
trading_bot.py — runs 5 paper-trading bots against live Redis data.

Reads:
  movement:BTCUSDT:latest  — price action
  zone:BTCUSDT:latest      — order flow confirmation

Publishes:
  signals:BTCUSDT:latest   — live state for all 5 bots (every 0.5s)
  signals:BTCUSDT:events   — Redis stream, one entry per trade taken

Writes SQL:
  paper_trades             — only when a bot actually ENTERs
"""

import json
import time

import redis

from bot_config import BOTS
from strategy_engine import evaluate_bot
from storage import create_db, save_paper_trade, close_paper_trade

SYMBOL = "BTCUSDT"
POLL_INTERVAL = 0.5
COOLDOWN_SEC = 300

r = redis.Redis(host="localhost", port=6379, decode_responses=True)


def _load_movement() -> dict:
    raw = r.get(f"movement:{SYMBOL}:latest")
    if not raw:
        return {}
    return json.loads(raw).get("movement", {})


def _load_zone() -> dict:
    raw = r.get(f"zone:{SYMBOL}:latest")
    if not raw:
        return None
    return json.loads(raw).get("zone")


def to_redis_bot(signal: dict) -> dict:
    out = {
        "bot": signal["bot"],
        "action": signal["action"],
        "reason": signal.get("reason"),
    }
    if signal.get("side"):
        out["side"] = signal["side"]
    if signal.get("price") is not None:
        out["price"] = signal["price"]
    if signal.get("metrics"):
        out["metrics"] = {
            "aggression_ratio": signal["metrics"].get("aggression_ratio"),
            "withdrawal_ratio": signal["metrics"].get("withdrawal_ratio"),
        }
    return out


def to_redis_trade(signal: dict) -> dict:
    """Trade event payload for MT5 connector — includes entry_level for stop loss."""
    trade = to_redis_bot(signal)
    if signal.get("entry_level") is not None:
        trade["entry_level"] = signal["entry_level"]
    trade["symbol"] = SYMBOL
    return trade


def _publish_latest(signals: list):
    bots = [to_redis_bot(s) for s in signals]
    payload = json.dumps({"symbol": SYMBOL, "bots": bots})
    r.set(f"signals:{SYMBOL}:latest", payload)
    r.publish(f"signals:{SYMBOL}", payload)


def _publish_trade(signal: dict, ts: float):
    """Redis stream — one event per trade taken."""
    trade = to_redis_trade(signal)
    r.xadd(f"signals:{SYMBOL}:events", {
        "ts": str(ts),
        "payload": json.dumps(trade),
    })
    r.set(f"trade:{SYMBOL}:{signal['bot']}:latest", json.dumps(trade))


class BotState:
    def __init__(self, bot_id: int, config: dict):
        self.bot_id = bot_id
        self.config = config
        self.open_trade_id = None
        self.open_side = None
        self.open_price = None
        self.last_entry_ts = 0.0


def _check_exit(bot: BotState, movement: dict, price: float) -> str | None:
    if bot.open_trade_id is None:
        return None

    tf = movement.get("5m", {})
    trend = tf.get("trend")

    if bot.open_side == "buy" and trend in ("downtrend", "reversal_down"):
        return "trend_flip_bearish"
    if bot.open_side == "sell" and trend in ("uptrend", "reversal_up"):
        return "trend_flip_bullish"

    level = tf.get("market_level")
    if bot.open_side == "buy" and level and price < level:
        return "invalidation_below_HL"
    if bot.open_side == "sell" and level and price > level:
        return "invalidation_above_LH"

    return None


def run():
    conn = create_db()
    bots = {i: BotState(i, cfg) for i, cfg in BOTS.items()}

    print(f"[trading_bot] running 5 bots on {SYMBOL}")
    for i, cfg in BOTS.items():
        print(f"  {cfg['name']}: aggression>{cfg['aggression_ratio_min']} "
              f"withdrawal>{cfg['withdrawal_ratio_min']:.0%}")

    while True:
        movement = _load_movement()
        zone = _load_zone()
        now = time.time()
        signals = []

        for bot_id, bot in bots.items():
            signal = evaluate_bot(movement, zone, bot.config)
            price = signal.get("price") or (zone or {}).get("current_price")

            exit_reason = _check_exit(bot, movement, price) if price else None
            if exit_reason and bot.open_trade_id:
                close_paper_trade(conn, bot.open_trade_id, price, exit_reason, now)
                print(f"[{bot.config['name']}] EXIT {bot.open_side} @ {price} — {exit_reason}")
                bot.open_trade_id = None
                bot.open_side = None
                bot.open_price = None

            if signal["action"] == "ENTER" and bot.open_trade_id is None:
                if now - bot.last_entry_ts < COOLDOWN_SEC:
                    signal["action"] = "WAIT"
                    signal["reason"] = "cooldown"

            if signal["action"] == "ENTER" and bot.open_trade_id is None:
                trade_id = save_paper_trade(conn, SYMBOL, bot.config["name"], signal, now)
                bot.open_trade_id = trade_id
                bot.open_side = signal["side"]
                bot.open_price = price
                bot.last_entry_ts = now
                _publish_trade(signal, now)
                m = signal["metrics"]
                print(
                    f"[{bot.config['name']}] ENTER {signal['side'].upper()} @ {price}"
                    f" | agg={m['aggression_ratio']} wdr={m['withdrawal_ratio']:.1%}"
                )

            signals.append(signal)

        _publish_latest(signals)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
