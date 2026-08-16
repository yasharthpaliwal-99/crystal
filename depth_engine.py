"""
depth_engine.py — in-memory order book built from depth diffs.
"""

def create_book():
    return {"bids": {}, "asks": {}}


def apply_diff(book: dict, bids: list, asks: list):
    for price, qty in bids:
        price, qty = float(price), float(qty)
        if qty == 0.0:
            book["bids"].pop(price, None)
        else:
            book["bids"][price] = qty
    for price, qty in asks:
        price, qty = float(price), float(qty)
        if qty == 0.0:
            book["asks"].pop(price, None)
        else:
            book["asks"][price] = qty
