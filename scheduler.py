import asyncio
import logging
from datetime import datetime, timedelta
from bot_config import BotConfig

logger = logging.getLogger(__name__)

class PriceScheduler:
    """Handles automatic price updates for cryptocurrencies"""

    def __init__(self, price_manager):
        self.price_manager = price_manager
        self.config = BotConfig()
        self.is_running = False

    async def start_scheduler(self):
        """Start the price update scheduler"""
        if self.is_running:
            logger.warning("Scheduler is already running")
            return

        self.is_running = True
        logger.info(f"Starting price scheduler with {self.config.UPDATE_INTERVAL_MINUTES} minute intervals")

        while self.is_running:
            try:
                # Update prices
                await self.update_prices()

                # Wait for the next update
                await asyncio.sleep(self.config.UPDATE_INTERVAL_MINUTES * 60)

            except Exception as e:
                logger.error(f"Error in price scheduler: {e}")
                # Wait a bit before retrying
                await asyncio.sleep(60)

    async def update_prices(self):
        """Update cryptocurrency prices"""
        try:
            logger.info("Updating cryptocurrency prices...")

            # Update prices for all currencies
            old_prices = self.price_manager.get_current_prices().copy()
            self.price_manager.update_prices()
            new_prices = self.price_manager.get_current_prices()

            # Log changes
            for currency in self.config.CURRENCIES:
                old_price = old_prices[currency]
                new_price = new_prices[currency]
                change_percent = ((new_price - old_price) / old_price) * 100 if old_price > 0 else 0

                logger.info(f"Updated {currency}: €{old_price:.2f} -> €{new_price:.2f} ({change_percent:+.2f}%)")

            logger.info("Price update completed successfully")

        except Exception as e:
            logger.error(f"Error updating prices: {e}")

    def stop_scheduler(self):
        """Stop the price scheduler"""
        self.is_running = False
        logger.info("Price scheduler stopped")