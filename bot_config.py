
import os

class BotConfig:
    """Configuration class for the crypto bot"""

    # Data directory
    DATA_DIR = "data"

    # Price settings
    INITIAL_PRICE = 3000.0
    MINIMUM_PRICE = 1000.0  # Prix minimum en dessous duquel les crypto ne peuvent pas descendre
    CURRENCIES = ['buxcoin', 'bitcoin']

    # Price fluctuation ranges (équilibré et plus réaliste)
    INCREASE_MIN_PERCENT = 0.001  # 0.1%
    INCREASE_MAX_PERCENT = 0.10   # 10% max (au lieu de 20%)
    DECREASE_MIN_PERCENT = 0.001  # 0.1%
    DECREASE_MAX_PERCENT = 0.10   # 10% max (au lieu de 20%)

    # Files
    PRICES_FILE = os.path.join(DATA_DIR, "prices.json")
    USERS_FILE = os.path.join(DATA_DIR, "users.json")
    ADMIN_FILE = os.path.join(DATA_DIR, "admin.json")

    # User settings
    INITIAL_BALANCE = 0.0

    # Scheduler settings - Update every 10 minutes
    UPDATE_INTERVAL_MINUTES = 10  # Every 10 minutes
