"""
ws_client.py — Binance WebSocket with auto-reconnect.

Reconnects when:
  - connection drops (on_close / on_error)
  - no message received for STALE_SECONDS (default 60s)
"""

import threading
import time

import websocket

STALE_SECONDS = 60
RECONNECT_DELAY = 5
WATCHDOG_INTERVAL = 10
PING_INTERVAL = 30
PING_TIMEOUT = 10


def run_ws(url: str, name: str, on_message_fn):
    """
    Block forever, maintaining a live WebSocket to url.
    on_message_fn(message: str) is called for each frame.
    """
    last_message_ts = [time.time()]
    ws_holder = [None]
    running = [True]

    def _touch():
        last_message_ts[0] = time.time()

    def _on_message(ws, message):
        _touch()
        on_message_fn(message)

    def _on_error(ws, error):
        print(f"[{name}] ERROR: {error}")

    def _on_close(ws, close_status_code, close_msg):
        print(f"[{name}] connection closed (code={close_status_code})")

    def _watchdog():
        while running[0]:
            time.sleep(WATCHDOG_INTERVAL)
            stale_for = time.time() - last_message_ts[0]
            if stale_for > STALE_SECONDS:
                print(f"[{name}] no data for {stale_for:.0f}s — forcing reconnect")
                ws = ws_holder[0]
                if ws:
                    ws.close()

    watchdog = threading.Thread(target=_watchdog, daemon=True, name=f"{name}-watchdog")
    watchdog.start()

    while running[0]:
        _touch()
        print(f"[{name}] connecting to {url}")
        ws = websocket.WebSocketApp(
            url,
            on_message=_on_message,
            on_error=_on_error,
            on_close=_on_close,
        )
        ws_holder[0] = ws
        ws.run_forever(ping_interval=PING_INTERVAL, ping_timeout=PING_TIMEOUT)
        ws_holder[0] = None
        print(f"[{name}] reconnecting in {RECONNECT_DELAY}s...")
        time.sleep(RECONNECT_DELAY)
