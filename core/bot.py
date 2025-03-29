import logging

from pyrogram import Client

from .config import Settings

logger = logging.getLogger("Delta")


class Delta:
    def __init__(self, config: Settings = None):
        self.config = config or Settings()
        self.bot_client = None
        self.user_client = None

    async def start_clients(self):

        self.bot_client = Client(
            name="bot",
            api_id=self.config.api_id,
            api_hash=self.config.api_hash,
            bot_token=self.config.bot_token,
            plugins={"root": "plugins"},
            sleep_threshold=180,
        )
        logger.info("Bot client initialized.")

        if self.config.session_string:
            self.user_client = Client(
                name="user",
                api_id=self.config.api_id,
                api_hash=self.config.api_hash,
                session_string=self.config.session_string,
                takeout=True,
                sleep_threshold=180,
            )
            logger.info("User client initialized.")

        if self.user_client:
            await self.user_client.start()
            logger.info("User client started.")

        if self.bot_client:
            await self.bot_client.start()
            logger.info("Bot client started.")

    async def stop_clients(self):
        if self.bot_client:
            await self.bot_client.stop()
            logger.info("Bot client stopped.")

        if self.user_client:
            await self.user_client.stop()
            logger.info("User client stopped.")


# Create a default instance if needed
delta = Delta()
