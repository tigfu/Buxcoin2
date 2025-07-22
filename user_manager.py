
import json
import os
import logging
from datetime import datetime
from typing import Dict, Optional, List
from bot_config import BotConfig

logger = logging.getLogger(__name__)

class UserManager:
    """Manages user wallets and transactions"""

    def __init__(self):
        self.config = BotConfig()
        self.users_file = 'data/users.json'
        self.ensure_data_directory()
        self.load_users()

    def ensure_data_directory(self):
        """Ensure the data directory exists"""
        if not os.path.exists(self.config.DATA_DIR):
            os.makedirs(self.config.DATA_DIR)
            logger.info(f"Created data directory: {self.config.DATA_DIR}")

    def load_users(self):
        """Load user data from JSON file or initialize empty"""
        try:
            if os.path.exists(self.users_file):
                with open(self.users_file, 'r') as f:
                    self.users = json.load(f)
                logger.info("Loaded user data from file")
            else:
                self.users = {}
                self.save_users()
                logger.info("Initialized empty user data")
        except Exception as e:
            logger.error(f"Error loading users: {e}")
            self.users = {}

    def save_users(self):
        """Save user data to JSON file"""
        try:
            with open(self.users_file, 'w') as f:
                json.dump(self.users, f, indent=2)
            logger.info("Saved user data to file")
        except Exception as e:
            logger.error(f"Error saving users: {e}")

    def get_user_wallet(self, user_id: str) -> Dict:
        """Get user's wallet, create if doesn't exist"""
        user_id = str(user_id)
        if user_id not in self.users:
            self.users[user_id] = {
                'balance': self.config.INITIAL_BALANCE,  # Starting balance
                'buxcoin': 0.0,
                'bitcoin': 0.0,
                'transactions': []
            }
            self.save_users()
        return self.users[user_id]

    def update_balance(self, user_id: str, amount: float) -> bool:
        """Update user's balance"""
        user_id = str(user_id)
        wallet = self.get_user_wallet(user_id)
        new_balance = wallet['balance'] + amount

        if new_balance < 0:
            return False

        wallet['balance'] = new_balance

        # Record admin transaction if it's a significant change
        if abs(amount) > 0:
            transaction = {
                'type': 'admin_balance_update',
                'amount': amount,
                'new_balance': new_balance,
                'timestamp': datetime.now().isoformat()
            }
            wallet['transactions'].append(transaction)

            # Keep only last 50 transactions
            if len(wallet['transactions']) > 50:
                wallet['transactions'] = wallet['transactions'][-50:]

        self.save_users()
        return True

    def update_currency(self, user_id: str, currency: str, amount: float) -> bool:
        """Update user's currency holdings"""
        user_id = str(user_id)
        currency = currency.lower()

        if currency not in ['buxcoin', 'bitcoin']:
            return False

        wallet = self.get_user_wallet(user_id)
        new_amount = wallet[currency] + amount

        if new_amount < 0:
            return False

        wallet[currency] = new_amount
        self.save_users()
        return True

    def buy_currency(self, user_id: str, currency: str, amount: float, price_per_unit: float) -> bool:
        """Buy currency for user"""
        user_id = str(user_id)
        currency = currency.lower()

        if currency not in ['buxcoin', 'bitcoin']:
            return False

        # Validate minimum amount (0.0001)
        if amount < 0.0001:
            return False

        total_cost = amount * price_per_unit
        wallet = self.get_user_wallet(user_id)

        if wallet['balance'] < total_cost:
            return False

        # Deduct money and add currency
        wallet['balance'] -= total_cost
        wallet[currency] += amount

        # Record transaction
        transaction = {
            'type': 'buy',
            'currency': currency,
            'amount': amount,
            'price_per_unit': price_per_unit,
            'total_cost': total_cost,
            'timestamp': datetime.now().isoformat()
        }
        wallet['transactions'].append(transaction)

        # Keep only last 50 transactions
        if len(wallet['transactions']) > 50:
            wallet['transactions'] = wallet['transactions'][-50:]

        self.save_users()
        return True

    def sell_currency(self, user_id: str, currency: str, amount: float, price_per_unit: float) -> bool:
        """Sell currency for user"""
        user_id = str(user_id)
        currency = currency.lower()

        if currency not in ['buxcoin', 'bitcoin']:
            return False

        # Validate minimum amount (0.0001)
        if amount < 0.0001:
            return False

        wallet = self.get_user_wallet(user_id)

        if wallet[currency] < amount:
            return False

        total_value = amount * price_per_unit

        # Add money and remove currency
        wallet['balance'] += total_value
        wallet[currency] -= amount

        # Record transaction
        transaction = {
            'type': 'sell',
            'currency': currency,
            'amount': amount,
            'price_per_unit': price_per_unit,
            'total_value': total_value,
            'timestamp': datetime.now().isoformat()
        }
        wallet['transactions'].append(transaction)

        # Keep only last 50 transactions
        if len(wallet['transactions']) > 50:
            wallet['transactions'] = wallet['transactions'][-50:]

        self.save_users()
        return True

    def get_all_users(self) -> Dict:
        """Get all users data (for admin purposes)"""
        return self.users.copy()

    def backup_users(self, prefix: str = "backup") -> str:
        """Create a backup of all user data"""
        try:
            backup_filename = f"{prefix}_users_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            backup_path = os.path.join(self.config.DATA_DIR, backup_filename)

            with open(backup_path, 'w') as f:
                json.dump(self.users, f, indent=2)

            logger.info(f"Created user backup: {backup_filename}")
            return backup_filename
        except Exception as e:
            logger.error(f"Error creating backup: {e}")
            return None
