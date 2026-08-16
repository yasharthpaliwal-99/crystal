"""
mt5_connector.py — Windows MT5 executor for Crystal trading bots.

Prerequisites (Windows only):
  1. MetaTrader 5 installed and logged into your paper/live account
  2. pip install -r requirements-mt5.txt
  3. Redis reachable (trading_bot running on Mac/cloud)
  4. Algo trading enabled in MT5: Tools → Options → Expert Advisors

Usage:
  python mt5_connector.py

On each ENTER event from signals:BTCUSDT:events:
  - Risk = 0.75% of account balance
  - SL at entry_level (HL for buy, LH for sell) with small buffer
  - TP = entry + (risk distance × RISK_REWARD) for buys, mirrored for sells
  - Lot size sized so SL hit = exactly the risk amount
"""

import json
import sys
import time

import redis

import mt5_config as cfg

try:
    import MetaTrader5 as mt5
except ImportError:
    print("MetaTrader5 package is Windows-only. Run this script on your Windows laptop.")
    sys.exit(1)


def _redis():
    return redis.Redis(host=cfg.REDIS_HOST, port=cfg.REDIS_PORT, decode_responses=True)


def _account_balance() -> float:
    info = mt5.account_info()
    if info is None:
        return cfg.ACCOUNT_BALANCE_FALLBACK
    return float(info.balance)


def _init_mt5() -> bool:
    kwargs = {}
    if cfg.MT5_PATH:
        kwargs["path"] = cfg.MT5_PATH
    if not mt5.initialize(**kwargs):
        print(f"MT5 initialize failed: {mt5.last_error()}")
        return False

    if not mt5.symbol_select(cfg.MT5_SYMBOL, True):
        print(f"Symbol {cfg.MT5_SYMBOL} not available: {mt5.last_error()}")
        return False

    info = mt5.account_info()
    if info:
        print(f"Connected: {info.login} | {info.server} | balance={info.balance:.2f}")
    return True


def _has_open_position(magic: int) -> bool:
    positions = mt5.positions_get(symbol=cfg.MT5_SYMBOL)
    if not positions:
        return False
    return any(p.magic == magic for p in positions)


def _stop_loss(side: str, entry: float, entry_level: float | None) -> float:
    if entry_level:
        buffer = entry_level * cfg.SL_BUFFER_PCT
        if side == "buy":
            return entry_level - buffer
        return entry_level + buffer

    fallback = entry * cfg.MIN_SL_DISTANCE_PCT
    if side == "buy":
        return entry - fallback
    return entry + fallback


def _take_profit(side: str, entry: float, sl: float) -> float:
    risk = abs(entry - sl)
    if side == "buy":
        return entry + risk * cfg.RISK_REWARD
    return entry - risk * cfg.RISK_REWARD


def _normalize_volume(volume: float, symbol: str) -> float | None:
    info = mt5.symbol_info(symbol)
    if info is None:
        return None
    volume = max(info.volume_min, min(info.volume_max, volume))
    step = info.volume_step
    if step > 0:
        volume = round(volume / step) * step
    return round(volume, 2)


def _calc_volume(side: str, entry: float, sl: float, risk_money: float) -> float | None:
    order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
    loss_per_lot = mt5.order_calc_profit(order_type, cfg.MT5_SYMBOL, 1.0, entry, sl)
    if loss_per_lot is None or loss_per_lot == 0:
        return None
    volume = risk_money / abs(loss_per_lot)
    return _normalize_volume(volume, cfg.MT5_SYMBOL)


def _place_order(trade: dict) -> bool:
    bot_name = trade["bot"]
    side = trade["side"]
    magic = cfg.BOT_MAGIC.get(bot_name)
    if magic is None:
        print(f"Unknown bot: {bot_name}")
        return False

    if _has_open_position(magic):
        print(f"[{bot_name}] skip — position already open")
        return False

    tick = mt5.symbol_info_tick(cfg.MT5_SYMBOL)
    if tick is None:
        print(f"No tick for {cfg.MT5_SYMBOL}: {mt5.last_error()}")
        return False

    entry = float(trade.get("price") or tick.ask if side == "buy" else tick.bid)
    entry_level = trade.get("entry_level")
    if entry_level is not None:
        entry_level = float(entry_level)

    sl = _stop_loss(side, entry, entry_level)
    tp = _take_profit(side, entry, sl)

    balance = _account_balance()
    risk_money = balance * cfg.RISK_PCT
    volume = _calc_volume(side, entry, sl, risk_money)
    if not volume:
        print(f"[{bot_name}] could not calculate volume")
        return False

    order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
    price = tick.ask if side == "buy" else tick.bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": cfg.MT5_SYMBOL,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "deviation": cfg.MT5_DEVIATION,
        "magic": magic,
        "comment": f"crystal_{bot_name}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None:
        print(f"[{bot_name}] order_send failed: {mt5.last_error()}")
        return False
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"[{bot_name}] order rejected: {result.retcode} {result.comment}")
        return False

    risk_dist = abs(entry - sl)
    reward_dist = abs(tp - entry)
    print(
        f"[{bot_name}] FILLED {side.upper()} {volume} lots @ {price}"
        f" | SL={sl:.2f} TP={tp:.2f}"
        f" | risk=${risk_money:.2f} ({cfg.RISK_PCT:.2%})"
        f" | R:R=1:{cfg.RISK_REWARD} ({risk_dist:.2f} → {reward_dist:.2f})"
    )
    return True


def _listen():
    r = _redis()
    last_id = "$"
    print(f"Listening on {cfg.EVENTS_STREAM} (Redis {cfg.REDIS_HOST})...")

    while True:
        try:
            resp = r.xread({cfg.EVENTS_STREAM: last_id}, block=5000, count=10)
        except redis.ConnectionError as e:
            print(f"Redis connection error: {e} — retrying in 5s")
            time.sleep(5)
            continue

        if not resp:
            continue

        for _stream, messages in resp:
            for msg_id, fields in messages:
                last_id = msg_id
                payload = fields.get("payload")
                if not payload:
                    continue
                trade = json.loads(payload)
                if trade.get("action") != "ENTER":
                    continue
                _place_order(trade)


def main():
    if not _init_mt5():
        sys.exit(1)
    try:
        _listen()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
