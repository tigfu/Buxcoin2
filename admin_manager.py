
import json
import os
import logging
from bot_config import BotConfig

logger = logging.getLogger(__name__)

class AdminManager:
    """Manages bot administrators and admin-related functionality"""

    def __init__(self):
        self.config = BotConfig()
        self.admin_file = self.config.ADMIN_FILE
        self.ensure_data_directory()
        self.load_admins()

    def ensure_data_directory(self):
        """Ensure the data directory exists"""
        if not os.path.exists(self.config.DATA_DIR):
            os.makedirs(self.config.DATA_DIR)
            logger.info(f"Created data directory: {self.config.DATA_DIR}")

    def load_admins(self):
        """Load admin data from JSON file or initialize empty"""
        try:
            if os.path.exists(self.admin_file):
                with open(self.admin_file, 'r') as f:
                    data = json.load(f)
                    self.admins = set(data.get('admins', []))
                    self.log_channel_id = data.get('log_channel_id', None)
                logger.info(f"Loaded admin data from file: {len(self.admins)} admins")
            else:
                self.admins = set()
                self.log_channel_id = None
                self.save_admins()
                logger.info("Initialized empty admin data")
        except Exception as e:
            logger.error(f"Error loading admins: {e}")
            self.admins = set()
            self.log_channel_id = None

    def save_admins(self):
        """Save admin data to JSON file"""
        try:
            data = {
                'admins': list(self.admins),
                'log_channel_id': self.log_channel_id
            }
            with open(self.admin_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info("Saved admin data to file")
        except Exception as e:
            logger.error(f"Error saving admins: {e}")

    def is_admin(self, user_id: int) -> bool:
        """Check if a user is an admin"""
        return user_id in self.admins

    def add_admin(self, user_id: int):
        """Add a user as admin"""
        self.admins.add(user_id)
        self.save_admins()
        logger.info(f"Added admin: {user_id}")

    def remove_admin(self, user_id: int):
        """Remove admin permissions from a user"""
        if user_id in self.admins:
            self.admins.remove(user_id)
            self.save_admins()
            logger.info(f"Removed admin: {user_id}")
            return True
        return False

    def get_admins(self) -> list:
        """Get list of all admin user IDs"""
        return list(self.admins)

    def set_log_channel(self, channel_id: int):
        """Set the log channel for transactions"""
        self.log_channel_id = channel_id
        self.save_admins()
        logger.info(f"Set log channel: {channel_id}")

    def get_log_channel(self) -> int:
        """Get the log channel ID"""
        return self.log_channel_id
