
import threading
from realtime.connection import trades
from realtime.connection import depth
from realtime.connection import kline

print("ALL IMPORTS DONE")


def run_trade():
    print("STARTING TRADE")
    trades.start()


def run_depth():
    print("STARTING DEPTH")
    depth.start()


def run_kline():
    print("STARTING KLINE")
    kline.start()


print("CREATING THREADS")

t1 = threading.Thread(target=run_trade)
t2 = threading.Thread(target=run_depth)
t3 = threading.Thread(target=run_kline)

print("STARTING THREADS")

t1.start()
t2.start()
t3.start()

print("ALL THREADS STARTED")

t1.join()
t2.join()
t3.join()
