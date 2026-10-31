from __future__ import annotations

import asyncio
import logging
import socket

import discord
from discord.ext import commands

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

_INSTANCE_LOCK: socket.socket | None = None


def acquire_instance_lock(port: int = 48291) -> bool:
    global _INSTANCE_LOCK
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        s.listen(1)
        _INSTANCE_LOCK = s
        return True
    except OSError:
        return False


intents = discord.Intents.default()
intents.guilds = True


class Pvp0Bot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self) -> None:
        await self.load_extension("cogs.verification")
        await self.load_extension("cogs.tickets")
        await self.load_extension("cogs.treasury")
        guild = discord.Object(id=config.GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        try:
            synced = await self.tree.sync(guild=guild)
            logging.info("Zsynchronizowano %s komend na serwerze %s", len(synced), config.GUILD_ID)
        except discord.Forbidden:
            logging.error(
                "Brak dostępu do serwera (403). Zaproś bota ponownie z zakresem "
                "'bot' + 'applications.commands'. Link pojawi się po zalogowaniu."
            )

    async def on_guild_join(self, guild: discord.Guild) -> None:
        if guild.id != config.GUILD_ID:
            return
        try:
            synced = await self.tree.sync(guild=guild)
            logging.info("Zsynchronizowano %s komend po dołączeniu do %s", len(synced), guild.name)
        except discord.HTTPException as exc:
            logging.error("Nie udało się zsynchronizować komend: %s", exc)

    async def on_ready(self) -> None:
        logging.info("Zalogowano jako %s (ID: %s)", self.user, self.user.id if self.user else "?")
        invite = discord.utils.oauth_url(
            self.user.id,
            permissions=discord.Permissions(
                manage_roles=True,
                manage_channels=True,
                view_channel=True,
                send_messages=True,
                embed_links=True,
                attach_files=True,
                read_message_history=True,
            ),
            scopes=("bot", "applications.commands"),
        )
        logging.info("Zaproszenie bota: %s", invite)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="gildię PVP0",
            )
        )


async def main() -> None:
    if not acquire_instance_lock():
        logging.error("Inna instancja bota jest już uruchomiona! Zamykanie tej instancji, aby zapobiec podwójnym wiadomościom.")
        return
    bot = Pvp0Bot()
    async with bot:
        await bot.start(config.TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
