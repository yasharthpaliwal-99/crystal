"""
zone_engine.py — $30 price-zone features for aggression, liquidity,
consumption, withdrawal, and replenishment.

Price range: zone_low = floor(price / 30) * 30, zone_high = zone_low + 30

Per zone:
  buy_aggression    Σ taker-buy qty  (isBuyerMaker=False)
  sell_aggression   Σ taker-sell qty (isBuyerMaker=True)
  bid_liquidity     Σ resting bid qty in range
  ask_liquidity     Σ resting ask qty in range
  bid_consumption   Σ taker-sell qty hitting bids
  ask_consumption   Σ taker-buy  qty lifting asks
  bid_withdrawal    Σ max(0, bid_decrease − sell_executed) per level
  ask_withdrawal    Σ max(0, ask_decrease  − buy_executed)  per level
  bid_replenishment Σ new bids after level had bid consumption
  ask_replenishment Σ new asks after level had ask consumption
"""

ZONE_SIZE = 30.0


def zone_bounds(price: float) -> tuple:
    zone_low = int(price // ZONE_SIZE) * int(ZONE_SIZE)
    return zone_low, zone_low + int(ZONE_SIZE)


def _empty_zone(zone_low: int) -> dict:
    return {
        "zone_low": zone_low,
        "zone_high": zone_low + int(ZONE_SIZE),
        "buy_aggression": 0.0,
        "sell_aggression": 0.0,
        "bid_liquidity": 0.0,
        "ask_liquidity": 0.0,
        "bid_consumption": 0.0,
        "ask_consumption": 0.0,
        "bid_withdrawal": 0.0,
        "ask_withdrawal": 0.0,
        "bid_replenishment": 0.0,
        "ask_replenishment": 0.0,
    }


def _empty_level() -> dict:
    return {
        "bid_qty": 0.0,
        "ask_qty": 0.0,
        "sell_executed": 0.0,
        "buy_executed": 0.0,
        "bid_consumed": False,
        "ask_consumed": False,
    }


def create_zone_state():
    return {
        "current_price": None,
        "active_zone_low": None,
        "zones": {},       # zone_low -> zone metrics
        "levels": {},      # price -> per-level book + execution tracking
    }


def _get_zone(state: dict, zone_low: int) -> dict:
    if zone_low not in state["zones"]:
        state["zones"][zone_low] = _empty_zone(zone_low)
    return state["zones"][zone_low]


def _get_level(state: dict, price: float) -> dict:
    key = round(price, 2)
    if key not in state["levels"]:
        state["levels"][key] = _empty_level()
    return state["levels"][key]


def _set_active_zone(state: dict, price: float):
    zone_low, zone_high = zone_bounds(price)
    state["current_price"] = price
    if state["active_zone_low"] != zone_low:
        state["active_zone_low"] = zone_low
    _get_zone(state, zone_low)
    return zone_low, zone_high


def _price_in_zone(price: float, zone_low: int) -> bool:
    return zone_low <= price < zone_low + ZONE_SIZE


def on_trade(state: dict, price: float, qty: float, is_buyer_maker: bool):
    """Process one trade. is_buyer_maker=True → taker sell, False → taker buy."""
    zone_low, _ = _set_active_zone(state, price)
    if not _price_in_zone(price, zone_low):
        zone_low, _ = zone_bounds(price)
        _get_zone(state, zone_low)

    zone = _get_zone(state, zone_low)
    level = _get_level(state, price)

    if is_buyer_maker:
        zone["sell_aggression"] += qty
        zone["bid_consumption"] += qty
        level["sell_executed"] += qty
        level["bid_consumed"] = True
    else:
        zone["buy_aggression"] += qty
        zone["ask_consumption"] += qty
        level["buy_executed"] += qty
        level["ask_consumed"] = True


def _update_bid_level(state: dict, price: float, new_qty: float):
    level = _get_level(state, price)
    old_qty = level["bid_qty"]
    zone_low, _ = zone_bounds(price)
    zone = _get_zone(state, zone_low)

    if new_qty < old_qty:
        decrease = old_qty - new_qty
        explained = min(level["sell_executed"], decrease)
        withdrawal = max(0.0, decrease - explained)
        zone["bid_withdrawal"] += withdrawal
        level["sell_executed"] = max(0.0, level["sell_executed"] - decrease)

    elif new_qty > old_qty:
        increase = new_qty - old_qty
        if level["bid_consumed"]:
            zone["bid_replenishment"] += increase

    level["bid_qty"] = new_qty


def _update_ask_level(state: dict, price: float, new_qty: float):
    level = _get_level(state, price)
    old_qty = level["ask_qty"]
    zone_low, _ = zone_bounds(price)
    zone = _get_zone(state, zone_low)

    if new_qty < old_qty:
        decrease = old_qty - new_qty
        explained = min(level["buy_executed"], decrease)
        withdrawal = max(0.0, decrease - explained)
        zone["ask_withdrawal"] += withdrawal
        level["buy_executed"] = max(0.0, level["buy_executed"] - decrease)

    elif new_qty > old_qty:
        increase = new_qty - old_qty
        if level["ask_consumed"]:
            zone["ask_replenishment"] += increase

    level["ask_qty"] = new_qty


def on_depth_diff(state: dict, bids: list, asks: list):
    """Apply depth diff and update withdrawal / replenishment per level."""
    for price_str, qty_str in bids:
        price, qty = float(price_str), float(qty_str)
        if qty == 0.0:
            _update_bid_level(state, price, 0.0)
        else:
            _update_bid_level(state, price, qty)

    for price_str, qty_str in asks:
        price, qty = float(price_str), float(qty_str)
        if qty == 0.0:
            _update_ask_level(state, price, 0.0)
        else:
            _update_ask_level(state, price, qty)


def refresh_liquidity(state: dict, book: dict):
    """Recompute bid/ask_liquidity for every tracked zone from the live book."""
    for zone_low, zone in state["zones"].items():
        zone_high = zone_low + ZONE_SIZE
        bid_liq = sum(q for p, q in book["bids"].items() if zone_low <= p < zone_high)
        ask_liq = sum(q for p, q in book["asks"].items() if zone_low <= p < zone_high)
        zone["bid_liquidity"] = round(bid_liq, 6)
        zone["ask_liquidity"] = round(ask_liq, 6)


def active_zone_snapshot(state: dict) -> dict:
    """Current $30 zone only — for Redis / live trade confirmation."""
    if state["active_zone_low"] is None:
        return None

    zone = state["zones"].get(state["active_zone_low"])
    if zone is None:
        return None

    return {
        "current_price": state["current_price"],
        "zone_low": zone["zone_low"],
        "zone_high": zone["zone_high"],
        "buy_aggression": round(zone["buy_aggression"], 6),
        "sell_aggression": round(zone["sell_aggression"], 6),
        "bid_liquidity": zone["bid_liquidity"],
        "ask_liquidity": zone["ask_liquidity"],
        "bid_consumption": round(zone["bid_consumption"], 6),
        "ask_consumption": round(zone["ask_consumption"], 6),
        "bid_withdrawal": round(zone["bid_withdrawal"], 6),
        "ask_withdrawal": round(zone["ask_withdrawal"], 6),
        "bid_replenishment": round(zone["bid_replenishment"], 6),
        "ask_replenishment": round(zone["ask_replenishment"], 6),
        "net_aggression": round(zone["buy_aggression"] - zone["sell_aggression"], 6),
        "liquidity_imbalance": round(
            (zone["bid_liquidity"] - zone["ask_liquidity"])
            / max(zone["bid_liquidity"] + zone["ask_liquidity"], 1e-9),
            4,
        ),
    }
