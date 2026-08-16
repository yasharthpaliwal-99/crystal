import json
import time
import redis_bridge
from realtime.connection.ws_client import run_ws

URL = "wss://stream.binance.com:9443/ws/btcusdt@trade"


def _handle(message):
    print(message)
    data = json.loads(message)
    redis_bridge.publish_raw("raw:trades", {
        "price": data["p"],
        "qty": data["q"],
        "is_buyer_maker": str(data["m"]),
        "ts": time.time(),
    })


def start():
    run_ws(URL, "trades", _handle)
