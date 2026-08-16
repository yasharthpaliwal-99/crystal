"""
bot_config.py — five identical strategies, different confirmation thresholds.

Only aggression_ratio_min and withdrawal_ratio_min differ per bot.
Ratios are decimals: 0.05 = 5%, 1.25 = buy aggression 1.25× sell aggression.
"""

TIMEFRAMES = ("5m", "15m", "30m", "1h")
ENTRY_TIMEFRAME = "5m"
ENTRY_TOLERANCE_PCT = 0.003  # price within 0.3% of entry level

BOTS = {
    1: {"name": "bot_1", "aggression_ratio_min": 1.10, "withdrawal_ratio_min": 0.05},
    2: {"name": "bot_2", "aggression_ratio_min": 1.25, "withdrawal_ratio_min": 0.10},
    3: {"name": "bot_3", "aggression_ratio_min": 1.50, "withdrawal_ratio_min": 0.15},
    4: {"name": "bot_4", "aggression_ratio_min": 1.75, "withdrawal_ratio_min": 0.25},
    5: {"name": "bot_5", "aggression_ratio_min": 2.00, "withdrawal_ratio_min": 0.40},
}
