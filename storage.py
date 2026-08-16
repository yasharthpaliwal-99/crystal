"""
storage.py — SQLite persistence for movement, zone, and liquidity data.
"""

import json
import sqlite3
from datetime import datetime, timezone

DB_PATH = "market_data.db"


def _readable_sec(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def create_db(path: str = DB_PATH):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS liquidity_snapshots (
            symbol TEXT, ts REAL, ts_readable TEXT,
            price_zone REAL, liquidity_score REAL
        )
    """)
    _ensure_movement_table(conn)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS zone_features (
            symbol TEXT NOT NULL,
            ts REAL NOT NULL,
            current_price REAL,
            zone_low REAL NOT NULL,
            zone_high REAL,
            buy_aggression REAL,
            sell_aggression REAL,
            bid_liquidity REAL,
            ask_liquidity REAL,
            bid_consumption REAL,
            ask_consumption REAL,
            bid_withdrawal REAL,
            ask_withdrawal REAL,
            bid_replenishment REAL,
            ask_replenishment REAL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_zone_features_lookup "
        "ON zone_features (symbol, zone_low, ts)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            bot_name TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL,
            entry_level REAL,
            exit_price REAL,
            zone_low REAL,
            zone_high REAL,
            aggression_ratio REAL,
            withdrawal_ratio REAL,
            buy_aggression REAL,
            sell_aggression REAL,
            bid_liquidity REAL,
            ask_liquidity REAL,
            bid_consumption REAL,
            ask_consumption REAL,
            bid_withdrawal REAL,
            ask_withdrawal REAL,
            candle_shape TEXT,
            trends TEXT,
            entry_reason TEXT,
            exit_reason TEXT,
            status TEXT NOT NULL,
            signal_json TEXT,
            opened_at REAL,
            closed_at REAL
        )
    """)
    for col in (
        "buy_aggression REAL", "sell_aggression REAL",
        "bid_liquidity REAL", "ask_liquidity REAL",
        "bid_consumption REAL", "ask_consumption REAL",
        "bid_withdrawal REAL", "ask_withdrawal REAL",
        "signal_json TEXT",
    ):
        try:
            conn.execute(f"ALTER TABLE paper_trades ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    return conn


def _ensure_movement_table(conn):
    cols = [row[1] for row in conn.execute("PRAGMA table_info(movement)").fetchall()]
    if cols and ("candle_shape" in cols or "structure_high" in cols):
        conn.execute("DROP TABLE movement")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS movement (
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            open_time INTEGER NOT NULL,
            open REAL, high REAL, low REAL, close REAL,
            volume REAL,
            buy_volume REAL,
            sell_volume REAL,
            candlestick_pattern TEXT,
            swing_high REAL,
            swing_high_label TEXT,
            swing_low REAL,
            swing_low_label TEXT,
            last_hh REAL,
            last_hl REAL,
            trend TEXT,
            market_level REAL,
            market_level_role TEXT,
            swing_confirmed_type TEXT,
            swing_confirmed_label TEXT,
            swing_confirmed_price REAL,
            event TEXT,
            PRIMARY KEY (symbol, timeframe, open_time)
        )
    """)


def save_liquidity_snapshot(conn, symbol: str, ts: float, zones: list):
    for z in zones:
        conn.execute(
            "INSERT INTO liquidity_snapshots VALUES (?, ?, ?, ?, ?)",
            (symbol, ts, _readable_sec(ts), z["price_zone"], z["liquidity_score"])
        )
    conn.commit()


def save_movement(conn, symbol: str, timeframe: str, record: dict):
    conn.execute(
        "INSERT OR REPLACE INTO movement "
        "(symbol, timeframe, open_time, open, high, low, close, volume, "
        "buy_volume, sell_volume, candlestick_pattern, "
        "swing_high, swing_high_label, swing_low, swing_low_label, "
        "last_hh, last_hl, trend, market_level, market_level_role, "
        "swing_confirmed_type, swing_confirmed_label, swing_confirmed_price, event) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            symbol, timeframe, record["open_time"],
            record["open"], record["high"], record["low"], record["close"], record["volume"],
            record["buy_volume"], record["sell_volume"],
            record["candlestick_pattern"],
            record["swing_high"], record["swing_high_label"],
            record["swing_low"], record["swing_low_label"],
            record["last_hh"], record["last_hl"],
            record["trend"], record["market_level"], record["market_level_role"],
            record["swing_confirmed_type"], record["swing_confirmed_label"],
            record["swing_confirmed_price"], record["event"],
        ),
    )
    conn.commit()


def save_zone_features(conn, symbol: str, ts: float, record: dict):
    conn.execute(
        "INSERT INTO zone_features "
        "(symbol, ts, current_price, zone_low, zone_high, "
        "buy_aggression, sell_aggression, bid_liquidity, ask_liquidity, "
        "bid_consumption, ask_consumption, bid_withdrawal, ask_withdrawal, "
        "bid_replenishment, ask_replenishment) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            symbol, ts, record.get("current_price"),
            record["zone_low"], record["zone_high"],
            record["buy_aggression"], record["sell_aggression"],
            record["bid_liquidity"], record["ask_liquidity"],
            record["bid_consumption"], record["ask_consumption"],
            record["bid_withdrawal"], record["ask_withdrawal"],
            record["bid_replenishment"], record["ask_replenishment"],
        ),
    )
    conn.commit()


def save_paper_trade(conn, symbol: str, bot_name: str, signal: dict, ts: float) -> int:
    m = signal.get("metrics") or {}
    pa = signal.get("price_action") or {}
    trends = pa.get("trends")
    cursor = conn.execute(
        "INSERT INTO paper_trades "
        "(symbol, bot_name, side, entry_price, entry_level, zone_low, zone_high, "
        "aggression_ratio, withdrawal_ratio, "
        "buy_aggression, sell_aggression, bid_liquidity, ask_liquidity, "
        "bid_consumption, ask_consumption, bid_withdrawal, ask_withdrawal, "
        "candle_shape, trends, entry_reason, status, signal_json, opened_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            symbol, bot_name, signal["side"],
            signal.get("price"), signal.get("entry_level"),
            signal.get("zone_low"), signal.get("zone_high"),
            m.get("aggression_ratio"), m.get("withdrawal_ratio"),
            m.get("buy_aggression"), m.get("sell_aggression"),
            m.get("bid_liquidity"), m.get("ask_liquidity"),
            m.get("bid_consumption"), m.get("ask_consumption"),
            m.get("bid_withdrawal"), m.get("ask_withdrawal"),
            pa.get("shape"),
            json.dumps(trends) if trends else None,
            signal.get("reason"), "open",
            json.dumps(signal),
            ts,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def close_paper_trade(conn, trade_id: int, exit_price: float, reason: str, ts: float):
    conn.execute(
        "UPDATE paper_trades SET exit_price=?, exit_reason=?, status='closed', closed_at=? "
        "WHERE id=?",
        (exit_price, reason, ts, trade_id),
    )
    conn.commit()
