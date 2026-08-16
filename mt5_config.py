"""
mt5_config.py — Windows MT5 executor settings.

Run mt5_connector.py on Windows with MT5 terminal open and logged in.
Point REDIS_HOST at your Mac IP or cloud VM where trading_bot runs.
"""

# --- Redis (signal source) ---
REDIS_HOST = "127.0.0.1"       # Mac IP or cloud VM IP when remote
REDIS_PORT = 6379
SIGNAL_SYMBOL = "BTCUSDT"       # matches trading_bot SYMBOL
EVENTS_STREAM = f"signals:{SIGNAL_SYMBOL}:events"

# --- MT5 broker symbol (change to match your broker) ---
MT5_SYMBOL = "BTCUSD"           # e.g. BTCUSD, Bitcoin, BTCUSD.a

# --- Account risk ---
RISK_PCT = 0.0075               # 0.75% per trade
RISK_REWARD = 2.0               # TP distance = SL distance × this ratio
ACCOUNT_BALANCE_FALLBACK = 100_000.0  # used if MT5 balance read fails

# --- Stop placement ---
SL_BUFFER_PCT = 0.0003          # place SL slightly beyond entry_level (0.03%)
MIN_SL_DISTANCE_PCT = 0.001     # fallback if entry_level missing (0.1% of price)

# --- Bot → MT5 magic number (one open position per bot) ---
BOT_MAGIC = {
    "bot_1": 1001,
    "bot_2": 1002,
    "bot_3": 1003,
    "bot_4": 1004,
    "bot_5": 1005,
}

# --- MT5 terminal ---
MT5_PATH = None                 # None = default install; or r"C:\Program Files\MetaTrader 5\terminal64.exe"
MT5_DEVIATION = 20              # max slippage in points
