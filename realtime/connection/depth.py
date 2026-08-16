import json
import time
import redis_bridge
from realtime.connection.ws_client import run_ws

URL = "wss://stream.binance.com:9443/ws/btcusdt@depth@100ms"


def _handle(message):
    print(message)
    data = json.loads(message)
    redis_bridge.publish_raw("raw:depth", {
        "U": data["U"],
        "u": data["u"],
        "b": json.dumps(data["b"]),
        "a": json.dumps(data["a"]),
        "ts": time.time(),
    })


def start():
    run_ws(URL, "depth", _handle)
