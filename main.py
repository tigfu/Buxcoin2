import discord
from discord.ext import commands
import asyncio
import os
import logging
import json
import signal
from datetime import datetime, timedelta
from bot_config import BotConfig
from price_manager import PriceManager
from scheduler import PriceScheduler
from user_manager import UserManager
from admin_manager import AdminManager
from aiohttp import web
import aiohttp_cors

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CryptoBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        super().__init__(command_prefix='!', intents=intents, help_command=None, case_insensitive=True)

        # Initialize managers
        self.price_manager = PriceManager()
        self.scheduler = PriceScheduler(self.price_manager)
        self.user_manager = UserManager()
        self.admin_manager = AdminManager()

        # Restore from latest backup if available
        self.restore_latest_backup()

        # Add the bot owner as admin by default
        if os.getenv('BOT_OWNER_ID'):
            owner_id = int(os.getenv('BOT_OWNER_ID'))
            self.admin_manager.add_admin(owner_id)

    async def setup_hook(self):
        """Called when the bot is starting up"""
        logger.info("Bot is starting up...")
        # Sync slash commands
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} command(s)")
            # Wait a bit to ensure commands are fully synced
            await asyncio.sleep(2)
            logger.info("Commands fully synchronized")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
        # Start the price scheduler
        asyncio.create_task(self.scheduler.start_scheduler())
        # Start auto-save task
        asyncio.create_task(self.auto_save_task())
        # Start web server
        asyncio.create_task(self.start_web_server())

    async def on_ready(self):
        """Called when the bot has successfully connected to Discord"""
        logger.info(f'{self.user} has connected to Discord!')
        print(f'Bot is ready! Logged in as {self.user}')
        print(f'Bot is connected to {len(self.guilds)} server(s)')
        print(f'Bot latency: {self.latency * 1000:.2f}ms')

        # Log all registered commands for debugging
        logger.info(f"Registered commands: {[cmd.name for cmd in self.commands]}")
        print(f"Available commands: {[cmd.name for cmd in self.commands]}")
        print("Bot is fully ready to receive commands!")

    async def on_message(self, message):
        """Called when a message is sent"""
        # Don't respond to bot messages
        if message.author == self.user:
            return

        # Log message for debugging
        if message.content.startswith('!'):
            logger.info(f"Command received: {message.content} from {message.author}")

        # Process commands
        await self.process_commands(message)

    async def on_thread_create(self, thread):
        """Called when a new thread (ticket) is created"""
        try:
            # Check if this is a ticket (usually contains "ticket" in the name or has specific category)
            if "ticket" in thread.name.lower() or thread.parent and "ticket" in thread.parent.name.lower():
                logger.info(f"New ticket detected: {thread.name}")

                # Wait a moment for the ticket to be fully created
                await asyncio.sleep(1)

                # Send help command in the ticket
                await thread.send("/help")
                logger.info(f"Auto-sent /help in ticket: {thread.name}")

        except Exception as e:
            logger.error(f"Error handling ticket creation: {e}")

    async def on_channel_create(self, channel):
        """Called when a new channel is created"""
        try:
            # Check if this is a ticket channel
            if "ticket" in channel.name.lower():
                logger.info(f"New ticket channel detected: {channel.name}")

                # Wait a moment for the channel to be fully created
                await asyncio.sleep(1)

                # Send help command in the ticket
                await channel.send("/help")
                logger.info(f"Auto-sent /help in ticket channel: {channel.name}")

        except Exception as e:
            logger.error(f"Error handling ticket channel creation: {e}")

    async def close(self):
        """Called when the bot is shutting down"""
        logger.info("Bot is shutting down, creating automatic backup...")
        await self.create_shutdown_backup()
        await super().close()

    def restore_latest_backup(self):
        """Restore from backup only if main data files are missing or corrupted"""
        try:
            data_dir = self.price_manager.config.DATA_DIR
            if not os.path.exists(data_dir):
                logger.info("No data directory found, skipping backup restoration")
                return

            # Check if main data files exist and are valid (not corrupted)
            users_file_ok = False
            prices_file_ok = False

            # Check users.json - only check if file is valid JSON, don't check content
            try:
                if os.path.exists(self.user_manager.users_file):
                    with open(self.user_manager.users_file, 'r') as f:
                        users_data = json.load(f)  # Just check if it's valid JSON
                    users_file_ok = True
                    logger.info(f"Main users.json file is valid JSON with {len(users_data)} entries, using it")
                else:
                    logger.info("Main users.json file does not exist")
            except Exception as e:
                logger.warning(f"Main users.json file is corrupted: {e}")

            # Check prices.json - only check if file is valid JSON, don't check content
            try:
                if os.path.exists(self.price_manager.prices_file):
                    with open(self.price_manager.prices_file, 'r') as f:
                        prices_data = json.load(f)  # Just check if it's valid JSON
                    prices_file_ok = True
                    logger.info("Main prices.json file is valid JSON, using it")
                else:
                    logger.info("Main prices.json file does not exist")
            except Exception as e:
                logger.warning(f"Main prices.json file is corrupted: {e}")

            # Only restore from backup if main files are missing or corrupted (not based on content)
            if not users_file_ok:
                user_backups = [f for f in os.listdir(data_dir) if f.startswith('shutdown_backup_users_') and f.endswith('.json')]
                if user_backups:
                    latest_user_backup = max(user_backups, key=lambda x: os.path.getctime(os.path.join(data_dir, x)))
                    user_backup_path = os.path.join(data_dir, latest_user_backup)

                    try:
                        with open(user_backup_path, 'r') as f:
                            backup_users = json.load(f)

                        self.user_manager.users = backup_users
                        self.user_manager.save_users()
                        logger.info(f"Restored {len(backup_users)} users from backup: {latest_user_backup}")
                    except Exception as e:
                        logger.error(f"Error reading user backup file: {e}")
                        logger.info("Will use empty user data")
                else:
                    logger.info("No user backup found, will use empty user data")

            if not prices_file_ok:
                price_backups = [f for f in os.listdir(data_dir) if f.startswith('shutdown_backup_prices_') and f.endswith('.json')]
                if price_backups:
                    latest_price_backup = max(price_backups, key=lambda x: os.path.getctime(os.path.join(data_dir, x)))
                    price_backup_path = os.path.join(data_dir, latest_price_backup)

                    try:
                        with open(price_backup_path, 'r') as f:
                            backup_data = json.load(f)

                        self.price_manager.current_prices = backup_data.get('current_prices', {})
                        self.price_manager.price_history = backup_data.get('price_history', {})

                        # Restore last_update
                        if backup_data.get('last_update'):
                            self.price_manager.last_update = datetime.fromisoformat(backup_data['last_update'])

                        self.price_manager.save_prices()
                        logger.info(f"Restored prices from backup: {latest_price_backup}")
                    except Exception as e:
                        logger.error(f"Error reading price backup file: {e}")
                        logger.info("Will use default prices")
                else:
                    logger.info("No price backup found, will use default prices")

            if users_file_ok and prices_file_ok:
                logger.info("All main data files are valid, no backup restoration needed")

        except Exception as e:
            logger.error(f"Error during backup check/restore: {e}")
            logger.info("Continuing with existing data files")

    async def auto_save_task(self):
        """Periodic auto-save task to prevent data loss"""
        while True:
            try:
                await asyncio.sleep(300)  # Auto-save every 5 minutes
                logger.info("Performing periodic auto-save...")

                # Force save user data
                self.user_manager.save_users()

                # Force save price data
                self.price_manager.save_prices()

                # Force save admin data
                self.admin_manager.save_admins()

                logger.info("Periodic auto-save completed")

            except Exception as e:
                logger.error(f"Error in auto-save task: {e}")
                await asyncio.sleep(60)  # Wait a bit before retrying

    async def create_shutdown_backup(self):
        """Create a backup when bot shuts down"""
        try:
            # Force save all data before backup
            logger.info("Forcing save of all data before shutdown...")
            self.user_manager.save_users()
            self.price_manager.save_prices()
            self.admin_manager.save_admins()

            # Backup users with shutdown prefix
            user_backup = self.user_manager.backup_users("shutdown_backup")
            logger.info(f"Shutdown backup - Users: {user_backup}")

            # Backup prices with shutdown prefix
            price_backup = f"shutdown_backup_prices_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            price_backup_path = os.path.join(self.price_manager.config.DATA_DIR, price_backup)

            with open(price_backup_path, 'w') as f:
                data = {
                    'current_prices': self.price_manager.current_prices,
                    'price_history': self.price_manager.price_history,
                    'last_update': self.price_manager.last_update.isoformat() if self.price_manager.last_update else None
                }
                json.dump(data, f, indent=2)

            logger.info(f"Shutdown backup - Prices: {price_backup}")
            logger.info("Automatic shutdown backup completed successfully")

        except Exception as e:
            logger.error(f"Error creating shutdown backup: {e}")

    async def on_command_error(self, ctx, error):
        """Handle command errors"""
        logger.error(f"Command error: {type(error).__name__}: {error}")
        logger.error(f"Command attempted: {ctx.message.content}")
        logger.error(f"User: {ctx.author} in {ctx.guild}")

        if isinstance(error, commands.CommandNotFound):
            # List available commands for debugging
            available_commands = [cmd.name for cmd in self.commands]
            logger.info(f"Available commands: {available_commands}")
            await ctx.send(f"❌ Commande introuvable. Commandes disponibles : {', '.join(available_commands)}")
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ Vous n'avez pas les permissions pour utiliser cette commande.")
        elif isinstance(error, commands.CheckFailure):
            # Check if there are any admins configured
            admin_list = bot.admin_manager.get_admins()
            if len(admin_list) == 0:
                await ctx.send("❌ Vous n'avez pas les permissions administrateur pour cette commande. Utilisez `/addadmin @vous` pour devenir le premier admin.")
            else:
                await ctx.send("❌ Vous n'avez pas les permissions administrateur pour cette commande. Contactez un administrateur existant.")
        else:
            logger.error(f"Command error in {ctx.command}: {error}")
            logger.error(f"Error details: {type(error).__name__}: {str(error)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            await ctx.send(f"❌ Une erreur est survenue lors du traitement de votre commande: {type(error).__name__}")

    async def on_app_command_error(self, interaction: discord.Interaction, error: Exception):
        """Handle slash command errors"""
        logger.error(f"Slash command error: {type(error).__name__}: {error}")
        logger.error(f"Command: {interaction.command.name if interaction.command else 'Unknown'}")
        logger.error(f"User: {interaction.user} in {interaction.guild}")

        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ Une erreur est survenue lors du traitement de votre commande: {type(error).__name__}", 
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"❌ Une erreur est survenue lors du traitement de votre commande: {type(error).__name__}", 
                    ephemeral=True
                )
        except Exception as e:
            logger.error(f"Failed to send error message: {e}")

    async def log_transaction(self, user, action, currency=None, amount=None, price=None):
        """Log transactions to the admin log channel"""
        log_channel_id = self.admin_manager.get_log_channel()
        if not log_channel_id:
            return

        try:
            channel = self.get_channel(log_channel_id)
            if not channel:
                return

            embed = discord.Embed(
                title="🔔 Transaction Log",
                color=0x00ff00 if action == "buy" else 0xff0000 if action == "sell" else 0x0099ff,
                timestamp=datetime.now()
            )

            embed.add_field(name="Utilisateur", value=f"{user.name} (ID: {user.id})", inline=False)
            embed.add_field(name="Action", value=action.title(), inline=True)

            if currency:
                embed.add_field(name="Cryptomonnaie", value=currency.title(), inline=True)
            if amount:
                embed.add_field(name="Montant", value=f"{amount}", inline=True)
            if price:
                embed.add_field(name="Prix", value=f"€{price:.2f}", inline=True)

            await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Error logging transaction: {e}")

    async def start_web_server(self):
        """Start the web server"""
        try:
            app = web.Application()
            
            # Setup CORS
            cors = aiohttp_cors.setup(app, defaults={
                "*": aiohttp_cors.ResourceOptions(
                    allow_credentials=True,
                    expose_headers="*",
                    allow_headers="*",
                    allow_methods="*"
                )
            })

            # Add routes
            app.router.add_get('/', self.handle_root)
            app.router.add_get('/health', self.handle_health)  # Health check pour Render
            app.router.add_get('/status', self.handle_status)
            app.router.add_get('/prices', self.handle_prices_api)
            app.router.add_get('/stats', self.handle_stats)
            app.router.add_get('/ping', self.handle_ping)

            # Add CORS to all routes
            for route in list(app.router.routes()):
                cors.add(route)

            # Port dynamique pour Render (utilise PORT env var ou 5000 par défaut)
            port = int(os.getenv('PORT', 5000))
            
            # Start server
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '0.0.0.0', port)
            await site.start()
            
            logger.info(f"Web server started on http://0.0.0.0:{port}")
            
        except OSError as e:
            if "Address already in use" in str(e):
                logger.warning(f"Port {port} already in use, trying alternative ports...")
                # Essayer d'autres ports si le port principal est occupé
                for alt_port in [port + 1, port + 2, 8000, 8080]:
                    try:
                        site = web.TCPSite(runner, '0.0.0.0', alt_port)
                        await site.start()
                        logger.info(f"Web server started on alternative port http://0.0.0.0:{alt_port}")
                        break
                    except OSError:
                        continue
                else:
                    logger.error("Could not find available port for web server")
            else:
                logger.error(f"OS error starting web server: {e}")
        except Exception as e:
            logger.error(f"Error starting web server: {e}")

    async def handle_health(self, request):
        """Handle health check endpoint for Render"""
        return web.json_response({
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "bot_status": "online" if self.is_ready() else "starting"
        })

    async def handle_root(self, request):
        """Handle root endpoint"""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>CryptoBot Status</title>
            <meta charset="UTF-8">
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
                .container { max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
                h1 { color: #333; text-align: center; }
                .status { padding: 20px; border-radius: 5px; margin: 20px 0; }
                .online { background: #d4edda; border-left: 5px solid #28a745; }
                .info { background: #d1ecf1; border-left: 5px solid #17a2b8; }
                .endpoint { background: #f8f9fa; padding: 15px; margin: 10px 0; border-radius: 5px; border-left: 3px solid #007bff; }
                code { background: #e9ecef; padding: 2px 5px; border-radius: 3px; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🤖 CryptoBot Status</h1>
                
                <div class="status online">
                    <h3>✅ Bot Status: Online</h3>
                    <p>Le bot Discord fonctionne correctement et est prêt à recevoir des commandes.</p>
                </div>
                
                <div class="status info">
                    <h3>📊 Informations</h3>
                    <p><strong>Serveurs connectés:</strong> """ + str(len(self.guilds)) + """</p>
                    <p><strong>Latence:</strong> """ + f"{self.latency * 1000:.2f}ms" + """</p>
                    <p><strong>Utilisateur:</strong> """ + str(self.user) + """</p>
                </div>
                
                <div class="status info">
                    <h3>🔗 API Endpoints</h3>
                    <div class="endpoint">
                        <strong>GET /status</strong><br>
                        <code>Statut détaillé du bot en JSON</code>
                    </div>
                    <div class="endpoint">
                        <strong>GET /prices</strong><br>
                        <code>Prix actuels des cryptomonnaies en JSON</code>
                    </div>
                    <div class="endpoint">
                        <strong>GET /stats</strong><br>
                        <code>Statistiques générales du bot en JSON</code>
                    </div>
                </div>
                
                <div class="status info">
                    <h3>💰 Commandes Discord</h3>
                    <p>Utilisez <code>/help</code> dans Discord pour voir toutes les commandes disponibles.</p>
                </div>
            </div>
        </body>
        </html>
        """
        return web.Response(text=html, content_type='text/html')

    async def handle_status(self, request):
        """Handle status API endpoint"""
        try:
            status_data = {
                "status": "online",
                "bot_user": str(self.user),
                "guild_count": len(self.guilds),
                "latency_ms": round(self.latency * 1000, 2),
                "uptime": str(datetime.now()),
                "last_price_update": self.price_manager.get_last_update().isoformat() if self.price_manager.get_last_update() else None,
                "admin_count": len(self.admin_manager.get_admins()),
                "user_count": len(self.user_manager.users),
                "commands_registered": len(self.commands)
            }
            return web.json_response(status_data)
        except Exception as e:
            logger.error(f"Error in status endpoint: {e}")
            return web.json_response({"error": "Internal server error"}, status=500)

    async def handle_prices_api(self, request):
        """Handle prices API endpoint"""
        try:
            prices = self.price_manager.get_current_prices()
            price_data = {
                "prices": prices,
                "last_update": self.price_manager.get_last_update().isoformat() if self.price_manager.get_last_update() else None,
                "timestamp": datetime.now().isoformat()
            }
            return web.json_response(price_data)
        except Exception as e:
            logger.error(f"Error in prices endpoint: {e}")
            return web.json_response({"error": "Internal server error"}, status=500)

    async def handle_stats(self, request):
        """Handle stats API endpoint"""
        try:
            total_balance = 0
            total_buxcoin = 0
            total_bitcoin = 0
            
            for user_data in self.user_manager.users.values():
                total_balance += user_data.get('balance', 0)
                total_buxcoin += user_data.get('buxcoin', 0)
                total_bitcoin += user_data.get('bitcoin', 0)
            
            prices = self.price_manager.get_current_prices()
            
            stats_data = {
                "total_users": len(self.user_manager.users),
                "total_balance_eur": round(total_balance, 2),
                "total_buxcoin": round(total_buxcoin, 4),
                "total_bitcoin": round(total_bitcoin, 4),
                "total_crypto_value_eur": round((total_buxcoin * prices['buxcoin']) + (total_bitcoin * prices['bitcoin']), 2),
                "current_prices": prices,
                "admin_count": len(self.admin_manager.get_admins()),
                "timestamp": datetime.now().isoformat()
            }
            return web.json_response(stats_data)
        except Exception as e:
            logger.error(f"Error in stats endpoint: {e}")
            return web.json_response({"error": "Internal server error"}, status=500)

    async def handle_ping(self, request):
        """Handle ping endpoint"""
        return web.Response(text='Pong!', status=200)

# Create bot instance before defining commands
bot = CryptoBot()

class PricesView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.bot = bot

    @discord.ui.button(label="🔄 Actualiser", style=discord.ButtonStyle.primary)
    async def refresh_prices(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            prices = self.bot.price_manager.get_current_prices()

            embed = discord.Embed(
                title="🪙 Prix Actuels des Cryptomonnaies",
                color=0x00ff00,
                timestamp=interaction.created_at
            )

            embed.add_field(
                name="💰 Buxcoin",
                value=f"€{prices['buxcoin']:.2f}",
                inline=True
            )

            embed.add_field(
                name="₿ Bitcoin",
                value=f"€{prices['bitcoin']:.2f}",
                inline=True
            )

            # Add last update info
            last_update = self.bot.price_manager.get_last_update()
            if last_update:
                embed.add_field(
                    name="📅 Dernière Mise à Jour",
                    value=last_update.strftime("%Y-%m-%d %H:%M:%S"),
                    inline=False
                )

            embed.set_footer(text="Les prix se mettent à jour toutes les 3 minutes")

            await interaction.response.edit_message(embed=embed, view=self)

        except Exception as e:
            logger.error(f"Error refreshing prices: {e}")
            await interaction.response.send_message("❌ Erreur lors de l'actualisation des prix.", ephemeral=True)

@bot.tree.command(name='prices', description='Afficher les prix actuels des cryptomonnaies')
async def show_prices(interaction: discord.Interaction):
    """Show current prices for both currencies"""
    try:
        await interaction.response.defer()
        logger.info(f"Command /prices called by {interaction.user}")
        prices = bot.price_manager.get_current_prices()
        logger.info(f"Prices retrieved: {prices}")

        embed = discord.Embed(
            title="🪙 Prix Actuels des Cryptomonnaies",
            color=0x00ff00,
            timestamp=interaction.created_at
        )

        embed.add_field(
            name="💰 Buxcoin",
            value=f"€{prices['buxcoin']:.2f}",
            inline=True
        )

        embed.add_field(
            name="₿ Bitcoin",
            value=f"€{prices['bitcoin']:.2f}",
            inline=True
        )

        # Add last update info
        last_update = bot.price_manager.get_last_update()
        if last_update:
            embed.add_field(
                name="📅 Dernière Mise à Jour",
                value=last_update.strftime("%Y-%m-%d %H:%M:%S"),
                inline=False
            )

        embed.set_footer(text="Les prix se mettent à jour toutes les 3 minutes")

        view = PricesView(bot)
        await interaction.followup.send(embed=embed, view=view)

        # Log the command usage
        await bot.log_transaction(interaction.user, "prices_check")

    except Exception as e:
        logger.error(f"Error showing prices: {e}")
        await interaction.response.send_message("❌ Erreur lors de la récupération des prix actuels.", ephemeral=True)

class WalletView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.bot = bot
        self.user_id = user_id

    @discord.ui.button(label="🔄 Actualiser", style=discord.ButtonStyle.primary)
    async def refresh_wallet(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Vous ne pouvez pas utiliser cette interface.", ephemeral=True)
            return

        try:
            wallet = self.bot.user_manager.get_user_wallet(self.user_id)
            prices = self.bot.price_manager.get_current_prices()

            # Calculate crypto values
            buxcoin_value = wallet['buxcoin'] * prices['buxcoin']
            bitcoin_value = wallet['bitcoin'] * prices['bitcoin']
            total_crypto_value = buxcoin_value + bitcoin_value

            embed = discord.Embed(
                title="💰 Votre Portefeuille",
                color=0xffd700,
                timestamp=interaction.created_at
            )

            embed.add_field(
                name="💵 Solde",
                value=f"€{wallet['balance']:.2f}",
                inline=True
            )

            embed.add_field(
                name="💰 Buxcoin",
                value=f"{wallet['buxcoin']:.4f} BUX\n€{prices['buxcoin']:.2f}/unité\n**Total: €{buxcoin_value:.2f}**",
                inline=True
            )

            embed.add_field(
                name="🪙 Bitcoin",
                value=f"{wallet['bitcoin']:.4f} BTC\n€{prices['bitcoin']:.2f}/unité\n**Total: €{bitcoin_value:.2f}**",
                inline=True
            )

            embed.add_field(
                name="💎 Valeur Totale Crypto",
                value=f"**€{total_crypto_value:.2f}**",
                inline=False
            )

            embed.set_footer(text="Utilisez /buy et /sell pour acheter ou vendre des cryptomonnaies")

            await interaction.response.edit_message(embed=embed, view=self)

        except Exception as e:
            logger.error(f"Error refreshing wallet: {e}")
            await interaction.response.send_message("❌ Erreur lors de l'actualisation du portefeuille.", ephemeral=True)

@bot.tree.command(name='wallet', description='Afficher votre portefeuille')
async def show_wallet(interaction: discord.Interaction):
    """Show user's wallet"""
    try:
        await interaction.response.defer()
        logger.info(f"Command /wallet called by {interaction.user}")
        wallet = bot.user_manager.get_user_wallet(str(interaction.user.id))
        logger.info(f"Wallet retrieved: {wallet}")
        prices = bot.price_manager.get_current_prices()

        # Calculate crypto values
        buxcoin_value = wallet['buxcoin'] * prices['buxcoin']
        bitcoin_value = wallet['bitcoin'] * prices['bitcoin']
        total_crypto_value = buxcoin_value + bitcoin_value

        embed = discord.Embed(
            title="💰 Votre Portefeuille",
            color=0xffd700,
            timestamp=interaction.created_at
        )

        embed.add_field(
            name="💵 Solde",
            value=f"€{wallet['balance']:.2f}",
            inline=True
        )

        embed.add_field(
            name="💰 Buxcoin",
            value=f"{wallet['buxcoin']:.4f} BUX\n€{prices['buxcoin']:.2f}/unité\n**Total: €{buxcoin_value:.2f}**",
            inline=True
        )

        embed.add_field(
            name="🪙 Bitcoin",
            value=f"{wallet['bitcoin']:.4f} BTC\n€{prices['bitcoin']:.2f}/unité\n**Total: €{bitcoin_value:.2f}**",
            inline=True
        )

        embed.add_field(
            name="💎 Valeur Totale Crypto",
            value=f"**€{total_crypto_value:.2f}**",
            inline=False
        )

        embed.set_footer(text="Utilisez /buy et /sell pour acheter ou vendre des cryptomonnaies")

        view = WalletView(bot, interaction.user.id)
        await interaction.followup.send(embed=embed, view=view)

        # Log the command usage
        await bot.log_transaction(interaction.user, "wallet_check")

    except Exception as e:
        logger.error(f"Error showing wallet: {e}")
        await interaction.response.send_message("❌ Erreur lors de la récupération du portefeuille.", ephemeral=True)

# All commands are now slash commands

@bot.tree.command(name='help', description='Afficher la liste de toutes les commandes disponibles')
async def show_help(interaction: discord.Interaction):
    """Show all available commands"""
    try:
        embed = discord.Embed(
            title="🤖 Aide - Commandes Disponibles",
            description="Voici toutes les commandes que vous pouvez utiliser avec ce bot crypto",
            color=0x00bfff,
            timestamp=interaction.created_at
        )

        # Trading commands
        embed.add_field(
            name="💰 Trading",
            value="• `/prices` - Voir les prix actuels des cryptomonnaies\n" +
                  "• `/wallet` - Afficher votre portefeuille\n" +
                  "• `/buy <crypto> <montant>` - Acheter des cryptomonnaies\n" +
                  "• `/sell <crypto> <montant>` - Vendre des cryptomonnaies",
            inline=False
        )

        # Info commands
        embed.add_field(
            name="ℹ️ Informations",
            value="• `/help` - Afficher cette aide\n" +
                  "• `/listadmins` - Voir la liste des administrateurs\n" +
                  "• `/pricehistory <crypto> [limite]` - Historique des prix",
            inline=False
        )

        # Admin commands removed from help display 


        # Usage examples
        embed.add_field(
            name="💡 Exemples d'Usage",
            value="• `/buy buxcoin 10` - Acheter 10 BuxCoin\n" +
                  "• `/sell bitcoin 5` - Vendre 5 Bitcoin\n" +
                  "• `/pricehistory bitcoin 15` - Voir les 15 derniers prix Bitcoin",
            inline=False
        )



        embed.set_footer(text="Les prix se mettent à jour automatiquement toutes les heures")

        await interaction.response.send_message(embed=embed)

    except Exception as e:
        logger.error(f"Error showing help: {e}")
        await interaction.response.send_message("❌ Erreur lors de l'affichage de l'aide.", ephemeral=True)

@bot.tree.command(name='listadmins', description='Afficher la liste de tous les administrateurs')
async def list_admins(interaction: discord.Interaction):
    """Show list of all administrators"""
    try:
        admin_list = bot.admin_manager.get_admins()

        embed = discord.Embed(
            title="👑 Liste des Administrateurs",
            color=0xff6b6b,
            timestamp=interaction.created_at
        )

        if not admin_list:
            embed.description = "Aucun administrateur configuré pour le moment."
        else:
            admin_mentions = []
            for admin_id in admin_list:
                try:
                    user = await bot.fetch_user(admin_id)
                    admin_mentions.append(f"• {user.mention} (ID: {admin_id})")
                except:
                    admin_mentions.append(f"• Utilisateur inconnu (ID: {admin_id})")

            embed.add_field(
                name=f"Administrateurs ({len(admin_list)})",
                value="\n".join(admin_mentions),
                inline=False
            )

        embed.set_footer(text="Les administrateurs peuvent utiliser les commandes slash /admin")

        await interaction.response.send_message(embed=embed)

    except Exception as e:
        logger.error(f"Error listing admins: {e}")
        await interaction.response.send_message("❌ Erreur lors de la récupération de la liste des administrateurs.", ephemeral=True)


@bot.tree.command(name='buy', description='Acheter des cryptomonnaies')
async def buy_crypto(interaction: discord.Interaction, crypto: str, montant: float):
    """Buy cryptocurrency"""
    try:
        crypto = crypto.lower()

        if crypto not in ['buxcoin', 'bitcoin']:
            await interaction.response.send_message("❌ Cryptomonnaie invalide. Utilisez 'buxcoin' ou 'bitcoin'.", ephemeral=True)
            return

        if montant <= 0:
            await interaction.response.send_message("❌ Le montant doit être positif.", ephemeral=True)
            return

        if montant < 0.0001:
            await interaction.response.send_message("❌ Le montant minimum est 0.0001.", ephemeral=True)
            return

        price = bot.price_manager.get_price(crypto)
        total_cost = montant * price

        success = bot.user_manager.buy_currency(str(interaction.user.id), crypto, montant, price)

        if success:
            embed = discord.Embed(
                title="✅ Achat Réussi",
                color=0x00ff00,
                timestamp=interaction.created_at
            )
            embed.add_field(name="Cryptomonnaie", value=crypto.title(), inline=True)
            embed.add_field(name="Montant", value=f"{montant}", inline=True)
            embed.add_field(name="Prix Unitaire", value=f"€{price:.2f}", inline=True)
            embed.add_field(name="Coût Total", value=f"€{total_cost:.2f}", inline=False)

            await interaction.response.send_message(embed=embed)
            await bot.log_transaction(interaction.user, "buy", crypto, montant, price)
        else:
            await interaction.response.send_message("❌ Solde insuffisant pour cet achat.", ephemeral=True)

    except Exception as e:
        logger.error(f"Error in buy command: {e}")
        await interaction.response.send_message("❌ Erreur lors de l'achat.", ephemeral=True)

@bot.tree.command(name='sell', description='Vendre des cryptomonnaies')
async def sell_crypto(interaction: discord.Interaction, crypto: str, montant: float):
    """Sell cryptocurrency"""
    try:
        crypto = crypto.lower()

        if crypto not in ['buxcoin', 'bitcoin']:
            await interaction.response.send_message("❌ Cryptomonnaie invalide. Utilisez 'buxcoin' ou 'bitcoin'.", ephemeral=True)
            return

        if montant <= 0:
            await interaction.response.send_message("❌ Le montant doit être positif.", ephemeral=True)
            return

        if montant < 0.0001:
            await interaction.response.send_message("❌ Le montant minimum est 0.0001.", ephemeral=True)
            return

        price = bot.price_manager.get_price(crypto)
        total_value = montant * price

        success = bot.user_manager.sell_currency(str(interaction.user.id), crypto, montant, price)

        if success:
            embed = discord.Embed(
                title="✅ Vente Réussie",
                color=0xff0000,
                timestamp=interaction.created_at
            )
            embed.add_field(name="Cryptomonnaie", value=crypto.title(), inline=True)
            embed.add_field(name="Montant", value=f"{montant}", inline=True)
            embed.add_field(name="Prix Unitaire", value=f"€{price:.2f}", inline=True)
            embed.add_field(name="Valeur Totale", value=f"€{total_value:.2f}", inline=False)

            await interaction.response.send_message(embed=embed)
            await bot.log_transaction(interaction.user, "sell", crypto, montant, price)
        else:
            await interaction.response.send_message("❌ Vous n'avez pas assez de cette cryptomonnaie.", ephemeral=True)

    except Exception as e:
        logger.error(f"Error in sell command: {e}")
        await interaction.response.send_message("❌ Erreur lors de la vente.", ephemeral=True)

# Admin slash commands (keeping prefix commands as well)
@bot.tree.command(name='give', description='[ADMIN] Donner de l\'argent à un utilisateur')
async def give_money_slash(interaction: discord.Interaction, user: discord.Member, amount: float):
    """Give money to a user (admin only)"""
    try:
        if not bot.admin_manager.is_admin(interaction.user.id):
            await interaction.response.send_message("❌ Vous n'avez pas les permissions administrateur pour cette commande.", ephemeral=True)
            return

        if amount <= 0:
            await interaction.response.send_message("❌ Le montant doit être positif.", ephemeral=True)
            return

        success = bot.user_manager.update_balance(str(user.id), amount)

        if success:
            # Force save after admin command
            bot.user_manager.save_users()

            embed = discord.Embed(
                title="✅ Argent Donné",
                color=0x00ff00,
                timestamp=interaction.created_at
            )
            embed.add_field(name="Utilisateur", value=user.mention, inline=True)
            embed.add_field(name="Montant", value=f"€{amount:.2f}", inline=True)
            embed.add_field(name="Admin", value=interaction.user.mention, inline=True)

            await interaction.response.send_message(embed=embed)
            await bot.log_transaction(interaction.user, "admin_give", amount=amount)
        else:
            await interaction.response.send_message("❌ Erreur lors de l'ajout d'argent.", ephemeral=True)

    except Exception as e:
        logger.error(f"Error giving money: {e}")
        await interaction.response.send_message("❌ Erreur lors de l'exécution de la commande.", ephemeral=True)

@bot.tree.command(name='updatepriceset', description='[ADMIN] Changer manuellement le prix d\'une cryptomonnaie')
async def update_price_set_slash(interaction: discord.Interaction, currency: str, price: float):
    """Manually set the price of a currency (admin only)"""
    try:
        if not bot.admin_manager.is_admin(interaction.user.id):
            await interaction.response.send_message("❌ Vous n'avez pas les permissions administrateur pour cette commande.", ephemeral=True)
            return

        currency = currency.lower()

        if currency not in ['buxcoin', 'bitcoin']:
            await interaction.response.send_message("❌ Cryptomonnaie invalide. Utilisez 'buxcoin' ou 'bitcoin'.", ephemeral=True)
            return

        if price <= 0:
            await interaction.response.send_message("❌ Le prix doit être positif.", ephemeral=True)
            return

        # Update price manually
        bot.price_manager.current_prices[currency] = price

        # Add to history
        timestamp = datetime.now().isoformat()
        bot.price_manager.price_history[currency].append({
            'price': price,
            'timestamp': timestamp,
            'change': 0.0,
            'manual': True
        })

        bot.price_manager.last_update = datetime.now()
        bot.price_manager.save_prices()

        embed = discord.Embed(
            title="✅ Prix Mis à Jour",
            color=0x00ff00,
            timestamp=interaction.created_at
        )
        embed.add_field(name="Cryptomonnaie", value=currency.title(), inline=True)
        embed.add_field(name="Nouveau Prix", value=f"€{price:.2f}", inline=True)
        embed.add_field(name="Admin", value=interaction.user.mention, inline=True)

        await interaction.response.send_message(embed=embed)
        await bot.log_transaction(interaction.user, "admin_price_update", currency, price=price)

    except Exception as e:
        logger.error(f"Error updating price: {e}")
        await interaction.response.send_message("❌ Erreur lors de la mise à jour du prix.", ephemeral=True)

@bot.tree.command(name='setuplogschannel', description='[ADMIN] Configurer le canal de logs pour les transactions')
async def setup_logs_channel_slash(interaction: discord.Interaction):
    """Setup logs channel for transactions (admin only)"""
    try:
        if not bot.admin_manager.is_admin(interaction.user.id):
            await interaction.response.send_message("❌ Vous n'avez pas les permissions administrateur pour cette commande.", ephemeral=True)
            return

        bot.admin_manager.set_log_channel(interaction.channel.id)

        embed = discord.Embed(
            title="✅ Canal de Logs Configuré",
            description=f"Les logs de transactions seront envoyés dans {interaction.channel.mention}",
            color=0x00ff00,
            timestamp=interaction.created_at
        )

        await interaction.response.send_message(embed=embed)

    except Exception as e:
        logger.error(f"Error setting up logs channel: {e}")
        await interaction.response.send_message("❌ Erreur lors de la configuration du canal de logs.", ephemeral=True)

@bot.tree.command(name='pricehistory', description='Afficher l\'historique des prix d\'une cryptomonnaie')
async def price_history(interaction: discord.Interaction, currency: str, limit: int = 10):
    """Show price history for a currency"""
    try:
        currency = currency.lower()

        if currency not in ['buxcoin', 'bitcoin']:
            await interaction.response.send_message("❌ Cryptomonnaie invalide. Utilisez 'buxcoin' ou 'bitcoin'.", ephemeral=True)
            return

        if limit < 1 or limit > 30:
            await interaction.response.send_message("❌ La limite doit être entre 1 et 30.", ephemeral=True)
            return

        history = bot.price_manager.get_price_history(currency, limit)

        if not history:
            await interaction.response.send_message("❌ Aucun historique disponible pour cette cryptomonnaie.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📊 Historique des Prix - {currency.title()}",
            color=0x0099ff,
            timestamp=interaction.created_at
        )

        # Show recent entries
        history_text = ""
        for entry in history[-limit:]:
            timestamp = entry['timestamp']
            price = entry['price']
            change = entry.get('change', 0.0)

            # Format timestamp
            try:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                formatted_time = dt.strftime("%d/%m %H:%M")
            except:
                formatted_time = timestamp[:16]  # Fallback

            # Format change
            change_symbol = "+" if change >= 0 else ""
            change_text = f"({change_symbol}€{change:.2f})" if change != 0 else ""

            history_text += f"`{formatted_time}` - €{price:.2f} {change_text}\n"

        embed.add_field(
            name=f"Dernières {len(history[-limit:])} entrées",
            value=history_text or "Aucune donnée",
            inline=False
        )

        # Current price
        current_price = bot.price_manager.get_price(currency)
        embed.add_field(
            name="Prix Actuel",
            value=f"€{current_price:.2f}",
            inline=True
        )

        embed.set_footer(text="Format: Date/Heure - Prix (Changement)")

        await interaction.response.send_message(embed=embed)

    except Exception as e:
        logger.error(f"Error showing price history: {e}")
        await interaction.response.send_message("❌ Erreur lors de la récupération de l'historique des prix.", ephemeral=True)

@bot.tree.command(name='addadmin', description='[ADMIN] Ajouter un administrateur')
async def add_admin_slash(interaction: discord.Interaction, user: discord.Member):
    """Add a user as admin (admin only or if no admins exist)"""
    try:
        admin_list = bot.admin_manager.get_admins()

        # Allow if user is admin OR if no admins exist (first admin)
        if not bot.admin_manager.is_admin(interaction.user.id) and len(admin_list) > 0:
            await interaction.response.send_message("❌ Vous n'avez pas les permissions administrateur pour cette commande.", ephemeral=True)
            return

        if bot.admin_manager.is_admin(user.id):
            await interaction.response.send_message(f"❌ {user.mention} est déjà administrateur.", ephemeral=True)
            return

        bot.admin_manager.add_admin(user.id)

        embed = discord.Embed(
            title="✅ Administrateur Ajouté",
            color=0x00ff00,
            timestamp=interaction.created_at
        )
        embed.add_field(name="Nouvel Admin", value=user.mention, inline=True)
        embed.add_field(name="Ajouté par", value=interaction.user.mention, inline=True)

        await interaction.response.send_message(embed=embed)
        await bot.log_transaction(interaction.user, "admin_add", user.name)

    except Exception as e:
        logger.error(f"Error adding admin: {e}")
        await interaction.response.send_message("❌ Erreur lors de l'ajout de l'administrateur.", ephemeral=True)

@bot.tree.command(name='removeadmin', description='[ADMIN] Retirer les permissions administrateur d\'un utilisateur')
async def remove_admin_slash(interaction: discord.Interaction, user: discord.Member):
    """Remove admin permissions from a user (admin only)"""
    try:
        if not bot.admin_manager.is_admin(interaction.user.id):
            await interaction.response.send_message("❌ Vous n'avez pas les permissions administrateur pour cette commande.", ephemeral=True)
            return

        if not bot.admin_manager.is_admin(user.id):
            await interaction.response.send_message(f"❌ {user.mention} n'est pas administrateur.", ephemeral=True)
            return

        # Prevent removing the last admin
        admin_list = bot.admin_manager.get_admins()
        if len(admin_list) <= 1:
            await interaction.response.send_message("❌ Impossible de retirer le dernier administrateur. Ajoutez d'abord un autre admin.", ephemeral=True)
            return

        # Prevent self-removal (optional security measure)
        if user.id == interaction.user.id:
            await interaction.response.send_message("❌ Vous ne pouvez pas retirer vos propres permissions d'administrateur.", ephemeral=True)
            return

        success = bot.admin_manager.remove_admin(user.id)

        if success:
            embed = discord.Embed(
                title="✅ Permissions Retirées",
                color=0xff0000,
                timestamp=interaction.created_at
            )
            embed.add_field(name="Ex-Admin", value=user.mention, inline=True)
            embed.add_field(name="Retiré par", value=interaction.user.mention, inline=True)

            await interaction.response.send_message(embed=embed)
            await bot.log_transaction(interaction.user, "admin_remove", user.name)
        else:
            await interaction.response.send_message("❌ Erreur lors de la suppression des permissions.", ephemeral=True)

    except Exception as e:
        logger.error(f"Error removing admin: {e}")
        await interaction.response.send_message("❌ Erreur lors de la suppression de l'administrateur.", ephemeral=True)



@bot.tree.command(name='admin', description='[ADMIN] Afficher toutes les commandes administrateur')
async def admin_help(interaction: discord.Interaction):
    """Show all admin commands (admin only)"""
    try:
        if not bot.admin_manager.is_admin(interaction.user.id):
            await interaction.response.send_message("❌ Vous n'avez pas les permissions administrateur pour cette commande.", ephemeral=True)
            return

        embed = discord.Embed(
            title="👑 Commandes Administrateur",
            description="Voici toutes les commandes administrateur disponibles",
            color=0xff6b6b,
            timestamp=interaction.created_at
        )

        # Slash commands
        embed.add_field(
            name="🔧 Commandes Slash",
            value="• `/give <user> <montant>` - Donner de l'argent\n" +
                  "• `/updatepriceset <crypto> <prix>` - Changer le prix\n" +
                  "• `/setuplogschannel` - Configurer les logs\n" +
                  "• `/addadmin <user>` - Ajouter un administrateur\n" +
                  "• `/removeadmin <user>` - Retirer un administrateur",
            inline=False
        )

        # Admin management commands
        embed.add_field(
            name="👥 Gestion des Utilisateurs",
            value="• `/adminaction removeuser <user> <montant>` - Retirer de l'argent\n" +
                  "• `/adminaction resetuser <user>` - Reset le portefeuille\n" +
                  "• `/adminaction viewuser <user>` - Voir le portefeuille",
            inline=False
        )

        # Info
        embed.add_field(
            name="ℹ️ Informations",
            value="• `/admin` - Afficher cette aide\n" +
                  "• `/listadmins` - Liste des administrateurs",
            inline=False
        )

        embed.set_footer(text="Utilisez ces commandes avec précaution")

        await interaction.response.send_message(embed=embed)

    except Exception as e:
        logger.error(f"Error showing admin help: {e}")
        await interaction.response.send_message("❌ Erreur lors de l'affichage des commandes admin.", ephemeral=True)

@bot.tree.command(name='adminaction', description='[ADMIN] Actions administrateur avancées')
async def admin_actions(interaction: discord.Interaction, action: str, user: discord.Member = None, montant: float = None):
    """Advanced admin actions"""
    try:
        if not bot.admin_manager.is_admin(interaction.user.id):
            await interaction.response.send_message("❌ Vous n'avez pas les permissions administrateur pour cette commande.", ephemeral=True)
            return

        action = action.lower()

        if action == "removeuser":
            if not user or montant is None:
                await interaction.response.send_message("❌ Usage: `/adminaction removeuser <@user> <montant>`", ephemeral=True)
                return

            if montant <= 0:
                await interaction.response.send_message("❌ Le montant doit être positif.", ephemeral=True)
                return

            wallet = bot.user_manager.get_user_wallet(str(user.id))
            if wallet['balance'] < montant:
                await interaction.response.send_message(f"❌ {user.mention} n'a que €{wallet['balance']:.2f} dans son portefeuille.", ephemeral=True)
                return

            success = bot.user_manager.update_balance(str(user.id), -montant)

            if success:
                embed = discord.Embed(
                    title="✅ Argent Retiré",
                    color=0xff0000,
                    timestamp=interaction.created_at
                )
                embed.add_field(name="Utilisateur", value=user.mention, inline=True)
                embed.add_field(name="Montant Retiré", value=f"€{montant:.2f}", inline=True)
                embed.add_field(name="Admin", value=interaction.user.mention, inline=True)

                new_wallet = bot.user_manager.get_user_wallet(str(user.id))
                embed.add_field(name="Nouveau Solde", value=f"€{new_wallet['balance']:.2f}", inline=True)

                await interaction.response.send_message(embed=embed)
                await bot.log_transaction(interaction.user, "admin_remove_money", amount=montant)
            else:
                await interaction.response.send_message("❌ Erreur lors du retrait d'argent.", ephemeral=True)

        elif action == "resetuser":
            if not user:
                await interaction.response.send_message("❌ Usage: `/adminaction resetuser <@user>`", ephemeral=True)
                return

            # Reset user wallet to default values
            bot.user_manager.users[str(user.id)] = {
                'balance': bot.user_manager.config.INITIAL_BALANCE,
                'buxcoin': 0.0,
                'bitcoin': 0.0,
                'transactions': []
            }
            bot.user_manager.save_users()

            embed = discord.Embed(
                title="✅ Utilisateur Réinitialisé",
                color=0xff9900,
                timestamp=interaction.created_at
            )
            embed.add_field(name="Utilisateur", value=user.mention, inline=True)
            embed.add_field(name="Admin", value=interaction.user.mention, inline=True)
            embed.add_field(name="Nouveau Solde", value=f"€{bot.user_manager.config.INITIAL_BALANCE:.2f}", inline=True)

            await interaction.response.send_message(embed=embed)
            await bot.log_transaction(interaction.user, "admin_reset_user", user.name)

        elif action == "viewuser":
            if not user:
                await interaction.response.send_message("❌ Usage: `/adminaction viewuser <@user>`", ephemeral=True)
                return

            wallet = bot.user_manager.get_user_wallet(str(user.id))
            prices = bot.price_manager.get_current_prices()

            # Calculate crypto values
            buxcoin_value = wallet['buxcoin'] * prices['buxcoin']
            bitcoin_value = wallet['bitcoin'] * prices['bitcoin']
            total_crypto_value = buxcoin_value + bitcoin_value

            embed = discord.Embed(
                title=f"👤 Portefeuille de {user.display_name}",
                color=0x00bfff,
                timestamp=interaction.created_at
            )

            embed.add_field(
                name="💵 Solde",
                value=f"€{wallet['balance']:.2f}",
                inline=True
            )

            embed.add_field(
                name="💰 Buxcoin",
                value=f"{wallet['buxcoin']:.4f} BUX\n€{buxcoin_value:.2f}",
                inline=True
            )

            embed.add_field(
                name="🪙 Bitcoin",
                value=f"{wallet['bitcoin']:.4f} BTC\n€{bitcoin_value:.2f}",
                inline=True
            )

            embed.add_field(
                name="💎 Valeur Totale Crypto",
                value=f"€{total_crypto_value:.2f}",
                inline=False
            )

            embed.add_field(
                name="📊 Valeur Totale",
                value=f"€{wallet['balance'] + total_crypto_value:.2f}",
                inline=False
            )

            # Show recent transactions
            if wallet['transactions']:
                recent_transactions = wallet['transactions'][-3:]  # Last 3 transactions
                trans_text = ""
                for trans in recent_transactions:
                    trans_type = trans['type']
                    currency = trans['currency']
                    amount = trans['amount']
                    trans_text += f"• {trans_type.title()} {amount:.4f} {currency}\n"

                embed.add_field(
                    name="📝 Dernières Transactions",
                    value=trans_text or "Aucune transaction",
                    inline=False
                )

            embed.set_footer(text=f"Demandé par {interaction.user.display_name}")

            await interaction.response.send_message(embed=embed)

        else:
            await interaction.response.send_message(
                "❌ Action invalide. Actions disponibles: `removeuser`, `resetuser`, `viewuser`", 
                ephemeral=True
            )

    except Exception as e:
        logger.error(f"Error in admin action: {e}")
        await interaction.response.send_message("❌ Erreur lors de l'exécution de l'action admin.", ephemeral=True)

# Prefix commands for admin
@bot.command(name='admin')
async def admin_help_prefix(ctx):
    """Show all admin commands (admin only)"""
    try:
        if not bot.admin_manager.is_admin(ctx.author.id):
            await ctx.send("❌ Vous n'avez pas les permissions administrateur pour cette commande.")
            return

        embed = discord.Embed(
            title="👑 Commandes Administrateur (Préfixe)",
            description="Voici toutes les commandes administrateur avec préfixe `!`",
            color=0xff6b6b,
            timestamp=ctx.message.created_at
        )

        # Prefix commands
        embed.add_field(
            name="🔧 Commandes Préfixe (!)",
            value="• `!give <user> <montant>` - Donner de l'argent\n" +
                  "• `!removeuser <user> <montant>` - Retirer de l'argent\n" +
                  "• `!resetuser <user>` - Reset le portefeuille\n" +
                  "• `!viewuser <user>` - Voir le portefeuille\n" +
                  "• `!updateprice <crypto> <prix>` - Changer le prix\n" +
                  "• `!addadmin <user>` - Ajouter un admin\n" +
                  "• `!removeadmin <user>` - Retirer un admin\n" +
                  "• `!setlogschannel` - Configurer les logs",
            inline=False
        )

        embed.add_field(
            name="ℹ️ Informations",
            value="• `!admin` - Afficher cette aide",
            inline=False
        )

        embed.set_footer(text="Utilisez ces commandes avec précaution")
        await ctx.send(embed=embed)

    except Exception as e:
        logger.error(f"Error showing admin help: {e}")
        await ctx.send("❌ Erreur lors de l'affichage des commandes admin.")

@bot.command(name='give')
async def give_money_prefix(ctx, user: discord.Member, amount: float):
    """Give money to a user (admin only)"""
    try:
        if not bot.admin_manager.is_admin(ctx.author.id):
            await ctx.send("❌ Vous n'avez pas les permissions administrateur pour cette commande.")
            return

        if amount <= 0:
            await ctx.send("❌ Le montant doit être positif.")
            return

        success = bot.user_manager.update_balance(str(user.id), amount)

        if success:
            # Force save immediately after admin action
            bot.user_manager.save_users()

            embed = discord.Embed(
                title="✅ Argent Donné",
                color=0x00ff00,
                timestamp=ctx.message.created_at
            )
            embed.add_field(name="Utilisateur", value=user.mention, inline=True)
            embed.add_field(name="Montant", value=f"€{amount:.2f}", inline=True)
            embed.add_field(name="Admin", value=ctx.author.mention, inline=True)

            await ctx.send(embed=embed)
            await bot.log_transaction(ctx.author, "admin_give", amount=amount)
        else:
            await ctx.send("❌ Erreur lors de l'ajout d'argent.")

    except Exception as e:
        logger.error(f"Error giving money: {e}")
        await ctx.send("❌ Erreur lors de l'exécution de la commande.")

@bot.command(name='removeuser')
async def remove_user_money_prefix(ctx, user: discord.Member, amount: float):
    """Remove money from a user (admin only)"""
    try:
        if not bot.admin_manager.is_admin(ctx.author.id):
            await ctx.send("❌ Vous n'avez pas les permissions administrateur pour cette commande.")
            return

        if amount <= 0:
            await ctx.send("❌ Le montant doit être positif.")
            return

        wallet = bot.user_manager.get_user_wallet(str(user.id))
        if wallet['balance'] < amount:
            await ctx.send(f"❌ {user.mention} n'a que €{wallet['balance']:.2f} dans son portefeuille.")
            return

        success = bot.user_manager.update_balance(str(user.id), -amount)

        if success:
            # Force save immediately after admin action
            bot.user_manager.save_users()

            embed = discord.Embed(
                title="✅ Argent Retiré",
                color=0xff0000,
                timestamp=ctx.message.created_at
            )
            embed.add_field(name="Utilisateur", value=user.mention, inline=True)
            embed.add_field(name="Montant Retiré", value=f"€{amount:.2f}", inline=True)
            embed.add_field(name="Admin", value=ctx.author.mention, inline=True)

            new_wallet = bot.user_manager.get_user_wallet(str(user.id))
            embed.add_field(name="Nouveau Solde", value=f"€{new_wallet['balance']:.2f}", inline=True)

            await ctx.send(embed=embed)
            await bot.log_transaction(ctx.author, "admin_remove_money", amount=amount)
        else:
            await ctx.send("❌ Erreur lors du retrait d'argent.")

    except Exception as e:
        logger.error(f"Error removing money: {e}")
        await ctx.send("❌ Erreur lors de l'exécution de la commande.")

@bot.command(name='resetuser')
async def reset_user_prefix(ctx, user: discord.Member):
    """Reset user wallet (admin only)"""
    try:
        if not bot.admin_manager.is_admin(ctx.author.id):
            await ctx.send("❌ Vous n'avez pas les permissions administrateur pour cette commande.")
            return

        # Reset user wallet to default values
        bot.user_manager.users[str(user.id)] = {
            'balance': bot.user_manager.config.INITIAL_BALANCE,
            'buxcoin': 0.0,
            'bitcoin': 0.0,
            'transactions': []
        }
        bot.user_manager.save_users()

        embed = discord.Embed(
            title="✅ Utilisateur Réinitialisé",
            color=0xff9900,
            timestamp=ctx.message.created_at
        )
        embed.add_field(name="Utilisateur", value=user.mention, inline=True)
        embed.add_field(name="Admin", value=ctx.author.mention, inline=True)
        embed.add_field(name="Nouveau Solde", value=f"€{bot.user_manager.config.INITIAL_BALANCE:.2f}", inline=True)

        await ctx.send(embed=embed)
        await bot.log_transaction(ctx.author, "admin_reset_user", user.name)

    except Exception as e:
        logger.error(f"Error resetting user: {e}")
        await ctx.send("❌ Erreur lors de la réinitialisation de l'utilisateur.")

@bot.command(name='viewuser')
async def view_user_prefix(ctx, user: discord.Member):
    """View user wallet (admin only)"""
    try:
        if not bot.admin_manager.is_admin(ctx.author.id):
            await ctx.send("❌ Vous n'avez pas les permissions administrateur pour cette commande.")
            return

        wallet = bot.user_manager.get_user_wallet(str(user.id))
        prices = bot.price_manager.get_current_prices()

        # Calculate crypto values
        buxcoin_value = wallet['buxcoin'] * prices['buxcoin']
        bitcoin_value = wallet['bitcoin'] * prices['bitcoin']
        total_crypto_value = buxcoin_value + bitcoin_value

        embed = discord.Embed(
            title=f"👤 Portefeuille de {user.display_name}",
            color=0x00bfff,
            timestamp=ctx.message.created_at
        )

        embed.add_field(
            name="💵 Solde",
            value=f"€{wallet['balance']:.2f}",
            inline=True
        )

        embed.add_field(
            name="💰 Buxcoin",
            value=f"{wallet['buxcoin']:.4f} BUX\n€{buxcoin_value:.2f}",
            inline=True
        )

        embed.add_field(
            name="🪙 Bitcoin",
            value=f"{wallet['bitcoin']:.4f} BTC\n€{bitcoin_value:.2f}",
            inline=True
        )

        embed.add_field(
            name="💎 Valeur Totale Crypto",
            value=f"€{total_crypto_value:.2f}",
            inline=False
        )

        embed.add_field(
            name="📊 Valeur Totale",
            value=f"€{wallet['balance'] + total_crypto_value:.2f}",
            inline=False
        )

        # Show recent transactions
        if wallet['transactions']:
            recent_transactions = wallet['transactions'][-3:]  # Last 3 transactions
            trans_text = ""
            for trans in recent_transactions:
                trans_type = trans['type']
                currency = trans['currency']
                amount = trans['amount']
                trans_text += f"• {trans_type.title()} {amount:.4f} {currency}\n"

            embed.add_field(
                name="📝 Dernières Transactions",
                value=trans_text or "Aucune transaction",
                inline=False
            )

        embed.set_footer(text=f"Demandé par {ctx.author.display_name}")
        await ctx.send(embed=embed)

    except Exception as e:
        logger.error(f"Error viewing user: {e}")
        await ctx.send("❌ Erreur lors de la récupération du portefeuille.")

@bot.command(name='updateprice')
async def update_price_prefix(ctx, currency: str, price: float):
    """Update cryptocurrency price (admin only)"""
    try:
        if not bot.admin_manager.is_admin(ctx.author.id):
            await ctx.send("❌ Vous n'avez pas les permissions administrateur pour cette commande.")
            return

        currency = currency.lower()

        if currency not in ['buxcoin', 'bitcoin']:
            await ctx.send("❌ Cryptomonnaie invalide. Utilisez 'buxcoin' ou 'bitcoin'.")
            return

        if price <= 0:
            await ctx.send("❌ Le prix doit être positif.")
            return

        if price < bot.price_manager.config.MINIMUM_PRICE:
            await ctx.send(f"❌ Le prix ne peut pas être inférieur à €{bot.price_manager.config.MINIMUM_PRICE:.2f}.")
            return

        # Update price manually
        bot.price_manager.current_prices[currency] = price

        # Add to history
        timestamp = datetime.now().isoformat()
        bot.price_manager.price_history[currency].append({
            'price': price,
            'timestamp': timestamp,
            'change': 0.0,
            'manual': True
        })

        bot.price_manager.last_update = datetime.now()
        bot.price_manager.save_prices()

        # Also force save user data to ensure consistency
        bot.user_manager.save_users()

        embed = discord.Embed(
            title="✅ Prix Mis à Jour",
            color=0x00ff00,
            timestamp=ctx.message.created_at
        )
        embed.add_field(name="Cryptomonnaie", value=currency.title(), inline=True)
        embed.add_field(name="Nouveau Prix", value=f"€{price:.2f}", inline=True)
        embed.add_field(name="Admin", value=ctx.author.mention, inline=True)

        await ctx.send(embed=embed)
        await bot.log_transaction(ctx.author, "admin_price_update", currency, price=price)

    except Exception as e:
        logger.error(f"Error updating price: {e}")
        await ctx.send("❌ Erreur lors de la mise à jour du prix.")

@bot.command(name='addadmin')
async def add_admin_prefix(ctx, user: discord.Member):
    """Add admin (admin only or first admin)"""
    try:
        admin_list = bot.admin_manager.get_admins()

        # Allow if user is admin OR if no admins exist (first admin)
        if not bot.admin_manager.is_admin(ctx.author.id) and len(admin_list) > 0:
            await ctx.send("❌ Vous n'avez pas les permissions administrateur pour cette commande.")
            return

        if bot.admin_manager.is_admin(user.id):
            await ctx.send(f"❌ {user.mention} est déjà administrateur.")
            return

        bot.admin_manager.add_admin(user.id)

        embed = discord.Embed(
            title="✅ Administrateur Ajouté",
            color=0x00ff00,
            timestamp=ctx.message.created_at
        )
        embed.add_field(name="Nouvel Admin", value=user.mention, inline=True)
        embed.add_field(name="Ajouté par", value=ctx.author.mention, inline=True)

        await ctx.send(embed=embed)
        await bot.log_transaction(ctx.author, "admin_add", user.name)

    except Exception as e:
        logger.error(f"Error adding admin: {e}")
        await ctx.send("❌ Erreur lors de l'ajout de l'administrateur.")

@bot.command(name='removeadmin')
async def remove_admin_prefix(ctx, user: discord.Member):
    """Remove admin (admin only)"""
    try:
        if not bot.admin_manager.is_admin(ctx.author.id):
            await ctx.send("❌ Vous n'avez pas les permissions administrateur pour cette commande.")
            return

        if not bot.admin_manager.is_admin(user.id):
            await ctx.send(f"❌ {user.mention} n'est pas administrateur.")
            return

        # Prevent removing the last admin
        admin_list = bot.admin_manager.get_admins()
        if len(admin_list) <= 1:
            await ctx.send("❌ Impossible de retirer le dernier administrateur. Ajoutez d'abord un autre admin.")
            return

        # Prevent self-removal (optional security measure)
        if user.id == ctx.author.id:
            await ctx.send("❌ Vous ne pouvez pas retirer vos propres permissions d'administrateur.")
            return

        success = bot.admin_manager.remove_admin(user.id)

        if success:
            embed = discord.Embed(
                title="✅ Permissions Retirées",
                color=0xff0000,
                timestamp=ctx.message.created_at
            )
            embed.add_field(name="Ex-Admin", value=user.mention, inline=True)
            embed.add_field(name="Retiré par", value=ctx.author.mention, inline=True)

            await ctx.send(embed=embed)
            await bot.log_transaction(ctx.author, "admin_remove", user.name)
        else:
            await ctx.send("❌ Erreur lors de la suppression des permissions.")

    except Exception as e:
        logger.error(f"Error removing admin: {e}")
        await ctx.send("❌ Erreur lors de la suppression de l'administrateur.")

@bot.command(name='setlogschannel')
async def set_logs_channel_prefix(ctx):
    """Set logs channel (admin only)"""
    try:
        if not bot.admin_manager.is_admin(ctx.author.id):
            await ctx.send("❌ Vous n'avez pas les permissions administrateur pour cette commande.")
            return

        bot.admin_manager.set_log_channel(ctx.channel.id)

        embed = discord.Embed(
            title="✅ Canal de Logs Configuré",
            description=f"Les logs de transactions seront envoyés dans {ctx.channel.mention}",
            color=0x00ff00,
            timestamp=ctx.message.created_at
        )

        await ctx.send(embed=embed)

    except Exception as e:
        logger.error(f"Error setting logs channel: {e}")
        await ctx.send("❌ Erreur lors de la configuration du canal de logs.")

async def shutdown_handler():
    """Handle graceful shutdown"""
    logger.info("Shutting down bot...")
    await bot.close()

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}, initiating shutdown...")
    # Set a flag or use asyncio to schedule shutdown
    loop = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        pass
    
    if loop and not loop.is_closed():
        loop.create_task(shutdown_handler())
    else:
        # If no loop is running, we'll let the normal exception handling take care of it
        logger.info("No event loop running, relying on normal shutdown process")

if __name__ == "__main__":
    # Get Discord bot token from environment
    token = os.getenv('DISCORD_BOT_TOKEN')

    # Setup signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Termination signal

    try:
        bot.run(token)
    except KeyboardInterrupt:
        logger.info("Bot interrupted by user")
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        print(f"Error starting bot: {e}")