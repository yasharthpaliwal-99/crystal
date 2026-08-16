import json
import time
import redis_bridge
from realtime.connection.ws_client import run_ws

URL = "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"


def _handle(message):
    print(message)
    data = json.loads(message)
    k = data["k"]
    redis_bridge.publish_raw("raw:klines", {
        "open": k["o"], "high": k["h"], "low": k["l"], "close": k["c"],
        "volume": k["v"], "open_time": k["t"], "closed": str(k["x"]),
        "ts": time.time(),
    })


def start():
    run_ws(URL, "kline", _handle)
