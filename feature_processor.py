"""
feature_processor.py — consumes trades, klines, and depth from Redis.
Publishes live state to Redis. Saves movement data to SQLite.

Install:
  pip install redis --break-system-packages
"""

import json
import time

import redis

from feature_engine import create_flow_state, add_trade, flow_snapshot
from liquidity_engine import create_liquidity_state, observe_liquidity, liquidity_zones
from depth_engine import create_book, apply_diff
from storage import create_db, save_liquidity_snapshot, save_movement, save_zone_features
from bootstrap_structure import load_structure
from movement_engine import (
    add_trade as movement_add_trade,
    add_1m_candle as movement_add_1m_candle, movement_snapshot,
)
from zone_engine import (
    create_zone_state, on_trade as zone_on_trade,
    on_depth_diff as zone_on_depth_diff, refresh_liquidity as zone_refresh_liquidity,
    active_zone_snapshot,
)

SYMBOL = "BTCUSDT"
r = redis.Redis(host="localhost", port=6379, decode_responses=True)

MIN_PUBLISH_INTERVAL = 0.5
LIQUIDITY_SNAPSHOT_INTERVAL = 5.0
ZONE_SNAPSHOT_INTERVAL = 5.0

STREAMS = ["raw:trades", "raw:klines", "raw:depth"]
GROUP = "feature_processor"
CONSUMER = "processor_1"


def ensure_groups():
    for s in STREAMS:
        try:
            r.xgroup_create(s, GROUP, id="$", mkstream=True)
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise


def publish_features(feat: dict):
    payload = json.dumps(feat)
    r.set(f"features:{SYMBOL}:latest", payload)
    r.publish(f"features:{SYMBOL}", payload)


def publish_movement(movement: dict):
    payload = json.dumps({"symbol": SYMBOL, "movement": movement})
    r.set(f"movement:{SYMBOL}:latest", payload)
    r.publish(f"movement:{SYMBOL}", payload)


def publish_zone(zone: dict):
    if zone is None:
        return
    payload = json.dumps({"symbol": SYMBOL, "zone": zone})
    r.set(f"zone:{SYMBOL}:latest", payload)
    r.publish(f"zone:{SYMBOL}", payload)


def _log_movement(timeframe: str, record: dict):
    sc_label = record.get("swing_confirmed_label")
    sc_price = record.get("swing_confirmed_price")
    sc_type = record.get("swing_confirmed_type")

    swing_part = ""
    if sc_label:
        swing_part = f" | SWING {sc_type} {sc_label} @ {sc_price}"

    print(
        f"[movement] {timeframe}"
        f" | o={record['open']} c={record['close']}"
        f" | pattern={record['candlestick_pattern']}"
        f"{swing_part}"
        f" | swing_high={record['swing_high_label']}@{record['swing_high']}"
        f" swing_low={record['swing_low_label']}@{record['swing_low']}"
        f" | trend={record['trend']}"
        f" | buy={record['buy_volume']} sell={record['sell_volume']}"
    )


def run():
    ensure_groups()
    conn = create_db()

    flow_state = create_flow_state()
    movement_state = load_structure()
    zone_state = create_zone_state()
    liq_state = create_liquidity_state()
    book = create_book()

    last_publish_ts = 0.0
    last_liquidity_save_ts = 0.0
    last_zone_save_ts = 0.0
    last_zone_low = None

    print("[processor] running — movement is the single source of truth")
    while True:
        resp = r.xreadgroup(GROUP, CONSUMER, {s: ">" for s in STREAMS}, count=200, block=1000)
        if not resp:
            continue

        for stream_name, messages in resp:
            for msg_id, fields in messages:

                if stream_name == "raw:trades":
                    ts = float(fields.get("ts", time.time()))
                    qty = float(fields["qty"])
                    price = float(fields["price"])
                    is_buyer_maker = fields["is_buyer_maker"] == "True"
                    is_buy = not is_buyer_maker
                    add_trade(flow_state, ts, qty, is_buyer_maker)
                    movement_add_trade(movement_state, ts, qty, is_buy)
                    zone_on_trade(zone_state, price, qty, is_buyer_maker)

                    if ts - last_publish_ts >= MIN_PUBLISH_INTERVAL:
                        movement = movement_snapshot(movement_state)
                        zone = active_zone_snapshot(zone_state)
                        feat = {"ts": ts, "symbol": SYMBOL}
                        feat.update(flow_snapshot(flow_state))
                        feat["movement"] = movement
                        feat["zone"] = zone
                        feat["liquidity_zones"] = liquidity_zones(liq_state)
                        publish_features(feat)
                        publish_movement(movement)
                        publish_zone(zone)
                        last_publish_ts = ts

                elif stream_name == "raw:klines":
                    if fields.get("closed") == "True":
                        candle = {
                            "open_time": int(fields["open_time"]),
                            "open": float(fields["open"]),
                            "high": float(fields["high"]),
                            "low": float(fields["low"]),
                            "close": float(fields["close"]),
                            "volume": float(fields["volume"]),
                        }
                        movement_records = movement_add_1m_candle(movement_state, candle)

                        for timeframe, record in movement_records:
                            save_movement(conn, SYMBOL, timeframe, record)
                            _log_movement(timeframe, record)

                        publish_movement(movement_snapshot(movement_state))

                elif stream_name == "raw:depth":
                    ts = float(fields.get("ts", time.time()))
                    bids = json.loads(fields["b"])
                    asks = json.loads(fields["a"])
                    apply_diff(book, bids, asks)
                    zone_on_depth_diff(zone_state, bids, asks)
                    zone_refresh_liquidity(zone_state, book)
                    observe_liquidity(liq_state, book["bids"], book["asks"], ts)

                    active_low = zone_state.get("active_zone_low")
                    if active_low is not None and active_low != last_zone_low:
                        rec = active_zone_snapshot(zone_state)
                        if rec and last_zone_low is not None:
                            save_zone_features(conn, SYMBOL, ts, rec)
                        last_zone_low = active_low

                    if ts - last_liquidity_save_ts >= LIQUIDITY_SNAPSHOT_INTERVAL:
                        zones = liquidity_zones(liq_state)
                        if zones:
                            save_liquidity_snapshot(conn, SYMBOL, ts, zones)
                        last_liquidity_save_ts = ts

                    if ts - last_zone_save_ts >= ZONE_SNAPSHOT_INTERVAL:
                        rec = active_zone_snapshot(zone_state)
                        if rec:
                            save_zone_features(conn, SYMBOL, ts, rec)
                        last_zone_save_ts = ts

                r.xack(stream_name, GROUP, msg_id)


if __name__ == "__main__":
    run()
