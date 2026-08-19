"""Load OHLC from SQL + Binance REST, rebuild structure, write SQL and Redis."""

import json
import time
import urllib.parse
import urllib.request

import redis

from movement_engine import (
    MOVEMENT_TIMEFRAMES,
    _process_closed,
    create_movement_state,
    movement_snapshot,
)
from storage import create_db, save_movement

SYMBOL = "BTCUSDT"
KLINES_URL = "https://api.binance.com/api/v3/klines"
EMPTY_LIMIT = 500


def _parse_kline(row):
    return {
        "open_time": int(row[0]),
        "close_time": int(row[6]) + 1,
        "open": float(row[1]),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "volume": float(row[5]),
    }


def _fetch_klines(interval, start_ms, end_ms, limit=1000):
    out = []
    cursor = start_ms
    while cursor < end_ms:
        params = {
            "symbol": SYMBOL,
            "interval": interval,
            "startTime": cursor,
            "endTime": end_ms,
            "limit": limit,
        }
        url = KLINES_URL + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=15) as resp:
            rows = json.loads(resp.read().decode())
        if not rows:
            break
        out.extend(_parse_kline(row) for row in rows)
        nxt = int(rows[-1][0]) + 1
        if nxt <= cursor:
            break
        cursor = nxt
        if len(rows) < limit:
            break
    return out


def _max_open_time(conn, timeframe):
    row = conn.execute(
        "SELECT MAX(open_time) FROM movement WHERE symbol=? AND timeframe=?",
        (SYMBOL, timeframe),
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def _replay_sql(conn, tf_state, timeframe):
    rows = conn.execute(
        "SELECT open_time, open, high, low, close, volume, buy_volume, sell_volume "
        "FROM movement WHERE symbol=? AND timeframe=? ORDER BY open_time",
        (SYMBOL, timeframe),
    ).fetchall()
    for open_time, o, h, l, c, vol, buy, sell in rows:
        tf_state["buy_volume"] = buy or 0.0
        tf_state["sell_volume"] = sell or 0.0
        _process_closed(tf_state, {
            "open_time": open_time,
            "open": o, "high": h, "low": l, "close": c, "volume": vol or 0.0,
        })
    return len(rows)


def load_structure():
    conn = create_db()
    r = redis.Redis(host="localhost", port=6379, decode_responses=True)
    state = create_movement_state()
    now_ms = int(time.time() * 1000)

    for tf, tf_state in state.items():
        _replay_sql(conn, tf_state, tf)
        last = _max_open_time(conn, tf)
        start = (last + 1) if last is not None else now_ms - tf_state["tf_ms"] * EMPTY_LIMIT
        candles = _fetch_klines(tf, start, now_ms)
        for c in candles:
            if last is not None and c["open_time"] <= last:
                continue
            if c["close_time"] > now_ms:
                tf_state["bucket_start"] = c["open_time"]
                tf_state["current_candle"] = {
                    "open_time": c["open_time"],
                    "open": c["open"], "high": c["high"],
                    "low": c["low"], "close": c["close"], "volume": c["volume"],
                }
                continue
            tf_state["buy_volume"] = 0.0
            tf_state["sell_volume"] = 0.0
            rec = _process_closed(tf_state, c)
            save_movement(conn, SYMBOL, tf, rec)
        if tf_state["current_candle"] is None and tf_state["last_record"]:
            nxt = tf_state["last_record"]["open_time"] + tf_state["tf_ms"]
            last_c = tf_state["last_record"]["close"]
            tf_state["bucket_start"] = nxt
            tf_state["current_candle"] = {
                "open_time": nxt, "open": last_c, "high": last_c,
                "low": last_c, "close": last_c, "volume": 0.0,
            }
        rec = tf_state["last_record"]
        print(
            f"[ohlc] {tf} last={last} trend={rec['trend'] if rec else None} "
            f"HH={tf_state['last_hh']} HL={tf_state['last_hl']}"
        )

    snap = movement_snapshot(state)
    r.set(f"movement:{SYMBOL}:latest", json.dumps({"symbol": SYMBOL, "movement": snap}))
    print("[ohlc] wrote movement SQL + Redis")
    return state


if __name__ == "__main__":
    load_structure()
