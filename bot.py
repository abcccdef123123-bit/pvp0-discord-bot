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
        await self.load_extension("cogs.settings")

        target_guilds = {1541920890328059994}
        if config.GUILD_ID:
            target_guilds.add(config.GUILD_ID)

        for gid in target_guilds:
            guild_obj = discord.Object(id=gid)
            self.tree.copy_global_to(guild=guild_obj)
            try:
                synced = await self.tree.sync(guild=guild_obj)
                logging.info("Zsynchronizowano %s komend na serwerze %s", len(synced), gid)
            except discord.Forbidden:
                logging.warning(
                    "Brak uprawnień (403) do synchronizacji na serwerze %s. Upewnij się, że bot jest na serwerze z zakresem 'applications.commands'.",
                    gid,
                )
            except Exception as e:
                logging.warning("Nie udało się zsynchronizować komend na serwerze %s: %s", gid, e)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        try:
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logging.info("Zsynchronizowano %s komend po dołączeniu do %s (%s)", len(synced), guild.name, guild.id)
        except Exception as exc:
            logging.error("Nie udało się zsynchronizować komend na serwerze %s (%s): %s", guild.name, guild.id, exc)

    async def on_ready(self) -> None:
        logging.info("Zalogowano jako %s (ID: %s)", self.user, self.user.id if self.user else "?")
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                logging.info("Zsynchronizowano %s komend na serwerze %s (%s)", len(synced), guild.name, guild.id)
            except Exception as e:
                logging.warning("Błąd synchronizacji na %s (%s): %s", guild.name, guild.id, e)
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
        await self.change_presence(activity=None, status=discord.Status.online)


async def main() -> None:
    if not acquire_instance_lock():
        logging.error("Inna instancja bota jest już uruchomiona! Zamykanie tej instancji, aby zapobiec podwójnym wiadomościom.")
        return
    bot = Pvp0Bot()
    try:
        async with bot:
            await bot.start(config.TOKEN)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logging.info("Bot został pomyślnie zatrzymany.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
