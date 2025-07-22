
import json
import os
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging
from bot_config import BotConfig

logger = logging.getLogger(__name__)

class PriceManager:
    """Manages cryptocurrency prices and history"""

    def __init__(self):
        self.config = BotConfig()
        self.prices_file = self.config.PRICES_FILE
        self.ensure_data_directory()
        self.load_prices()

    def ensure_data_directory(self):
        """Ensure the data directory exists"""
        if not os.path.exists(self.config.DATA_DIR):
            os.makedirs(self.config.DATA_DIR)
            logger.info(f"Created data directory: {self.config.DATA_DIR}")

    def load_prices(self):
        """Load prices from JSON file or initialize with default values"""
        try:
            if os.path.exists(self.prices_file):
                with open(self.prices_file, 'r') as f:
                    data = json.load(f)
                    self.current_prices = data.get('current_prices', {})
                    self.price_history = data.get('price_history', {})
                    self.last_update = data.get('last_update', None)

                    # Convert last_update string back to datetime if it exists
                    if self.last_update:
                        try:
                            self.last_update = datetime.fromisoformat(self.last_update)
                        except ValueError:
                            self.last_update = None

                    logger.info("Loaded prices from file")
            else:
                self.initialize_default_prices()
                logger.info("Initialized default prices")
        except Exception as e:
            logger.error(f"Error loading prices: {e}")
            self.initialize_default_prices()

    def initialize_default_prices(self):
        """Initialize with default starting prices"""
        self.current_prices = {
            'buxcoin': self.config.INITIAL_PRICE,
            'bitcoin': self.config.INITIAL_PRICE
        }
        self.price_history = {
            'buxcoin': [],
            'bitcoin': []
        }
        self.last_update = None

        # Add initial prices to history
        initial_timestamp = datetime.now().isoformat()
        for currency in self.config.CURRENCIES:
            self.price_history[currency].append({
                'price': self.config.INITIAL_PRICE,
                'timestamp': initial_timestamp,
                'change': 0.0
            })

        self.save_prices()

    def force_reset_to_initial_price(self):
        """Force reset all prices to initial value (3000€)"""
        logger.info(f"Force resetting all prices to €{self.config.INITIAL_PRICE}")

        for currency in self.config.CURRENCIES:
            self.current_prices[currency] = self.config.INITIAL_PRICE

            # Add reset entry to history
            timestamp = datetime.now().isoformat()
            self.price_history[currency].append({
                'price': self.config.INITIAL_PRICE,
                'timestamp': timestamp,
                'change': 0.0,
                'reset': True
            })

        self.last_update = datetime.now()
        self.save_prices()
        logger.info(f"All prices reset to €{self.config.INITIAL_PRICE}")

    def save_prices(self):
        """Save current prices and history to JSON file"""
        try:
            data = {
                'current_prices': self.current_prices,
                'price_history': self.price_history,
                'last_update': self.last_update.isoformat() if self.last_update else None
            }

            with open(self.prices_file, 'w') as f:
                json.dump(data, f, indent=2)

            logger.info("Saved prices to file")
        except Exception as e:
            logger.error(f"Error saving prices: {e}")

    def get_current_prices(self) -> Dict[str, float]:
        """Get current prices for all currencies"""
        return self.current_prices.copy()

    def get_price(self, currency: str) -> float:
        """Get current price for a specific currency"""
        return self.current_prices.get(currency.lower(), 0.0)

    def get_last_update(self) -> Optional[datetime]:
        """Get the timestamp of the last price update"""
        return self.last_update

    def get_price_history(self, currency: str, limit: int = 30) -> List[Dict]:
        """Get price history for a currency"""
        currency = currency.lower()
        if currency not in self.price_history:
            return []

        history = self.price_history[currency]
        return history[-limit:] if limit > 0 else history

    def update_prices(self):
        """Update prices with random fluctuations"""
        try:
            logger.info("Starting price update...")

            for currency in self.config.CURRENCIES:
                old_price = self.current_prices[currency]

                # Système de fluctuation personnalisé
                # 35% chance d'augmentation, 37% chance de diminution, 28% chance de changement minimal
                rand_choice = random.random()

                if rand_choice < 0.35:
                    # Prix augmente (35% de chance)
                    # Augmentations plus modérées : 0.1% à 10%
                    change_percent = random.uniform(self.config.INCREASE_MIN_PERCENT, 0.10)
                    change = old_price * change_percent
                    new_price = old_price + change
                elif rand_choice < 0.72:  # 0.35 + 0.37 = 0.72
                    # Prix diminue (37% de chance)
                    # Diminutions plus modérées : 0.1% à 10%
                    change_percent = random.uniform(self.config.DECREASE_MIN_PERCENT, 0.10)
                    change = -(old_price * change_percent)
                    new_price = old_price + change
                else:
                    # Changement très minimal (28% de chance) - stabilité
                    change_percent = random.uniform(0.001, 0.005)  # 0.1% à 0.5%
                    if random.choice([True, False]):
                        change = old_price * change_percent
                    else:
                        change = -(old_price * change_percent)
                    new_price = old_price + change

                # Ensure price doesn't go below minimum price
                new_price = max(self.config.MINIMUM_PRICE, new_price)

                # Ensure price doesn't go above a reasonable maximum (prevent overflow)
                new_price = min(1000000.0, new_price)

                # Update current price
                self.current_prices[currency] = new_price

                # Add to history
                timestamp = datetime.now().isoformat()
                self.price_history[currency].append({
                    'price': new_price,
                    'timestamp': timestamp,
                    'change': change
                })

                # Keep only last 100 entries in history to prevent file from growing too large
                if len(self.price_history[currency]) > 100:
                    self.price_history[currency] = self.price_history[currency][-100:]

                logger.info(f"Updated {currency}: €{old_price:.2f} → €{new_price:.2f} (change: €{change:+.2f})")

            # Update last update timestamp
            self.last_update = datetime.now()

            # Save to file
            self.save_prices()

            logger.info("Price update completed successfully")

        except Exception as e:
            logger.error(f"Error updating prices: {e}")
            raise

    def get_price_change_summary(self) -> Dict[str, Dict]:
        """Get summary of recent price changes"""
        summary = {}

        for currency in self.config.CURRENCIES:
            history = self.price_history[currency]
            if len(history) >= 2:
                latest = history[-1]
                previous = history[-2]

                summary[currency] = {
                    'current_price': latest['price'],
                    'previous_price': previous['price'],
                    'change': latest['change'],
                    'change_percentage': ((latest['price'] - previous['price']) / previous['price']) * 100,
                    'timestamp': latest['timestamp']
                }
            else:
                summary[currency] = {
                    'current_price': self.current_prices[currency],
                    'previous_price': self.current_prices[currency],
                    'change': 0.0,
                    'change_percentage': 0.0,
                    'timestamp': datetime.now().isoformat()
                }

        return summary

    def reset_prices(self):
        """Reset prices to initial values (for testing/admin purposes)"""
        logger.info("Resetting prices to initial values")
        self.initialize_default_prices()
