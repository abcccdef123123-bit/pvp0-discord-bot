from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config

DATA_DIR = os.path.join(config.BASE_DIR, "data")
CLAN_MEMBERS_FILE = os.path.join(DATA_DIR, "clan_members.json")
ZBIORKI_FILE = os.path.join(DATA_DIR, "zbiorki.json")

os.makedirs(DATA_DIR, exist_ok=True)


# ══════════════════════════════════════════════════════════════════
#  Pomocniki baz danych JSON & Dat
# ══════════════════════════════════════════════════════════════════

def load_zbiorki() -> list[dict]:
    if not os.path.exists(ZBIORKI_FILE):
        return []
    try:
        with open(ZBIORKI_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def save_zbiorki(items: list[dict]) -> None:
    try:
        with open(ZBIORKI_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error("Błąd zapisu zbiorki.json: %s", e)


def parse_meeting_datetime(data_str: str, time_str: str) -> datetime | None:
    """Parsuje polskie formaty daty i godziny zbiórki na obiekt datetime."""
    now = datetime.now().astimezone()
    tz = now.tzinfo

    # 1. Parsowanie godziny (np. 19:00, 20.30, 18)
    time_match = re.search(r"(\d{1,2})[:.](\d{2})", time_str)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
    else:
        single_h = re.search(r"\b(\d{1,2})\b", time_str)
        if single_h:
            hour = int(single_h.group(1))
            minute = 0
        else:
            return None

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    # 2. Parsowanie daty
    d_clean = data_str.strip().lower()
    DAYS_PL = {
        "poniedzialek": 0, "poniedziałek": 0, "pon": 0,
        "wtorek": 1, "wt": 1,
        "sroda": 2, "środa": 2, "sr": 2, "śr": 2,
        "czwartek": 3, "czw": 3,
        "piatek": 4, "piątek": 4, "pt": 4,
        "sobota": 5, "sob": 5, "sb": 5,
        "niedziela": 6, "ndz": 6, "nd": 6,
    }

    if d_clean in ("dzisiaj", "dzis", "dziś", "today"):
        target_date = now.date()
    elif d_clean in ("jutro", "tomorrow"):
        target_date = now.date() + timedelta(days=1)
    elif d_clean in ("pojutrze",):
        target_date = now.date() + timedelta(days=2)
    elif d_clean in DAYS_PL:
        target_weekday = DAYS_PL[d_clean]
        days_ahead = (target_weekday - now.weekday()) % 7
        if days_ahead == 0 and (hour, minute) < (now.hour, now.minute):
            days_ahead = 7
        target_date = now.date() + timedelta(days=days_ahead)
    else:
        # Format DD.MM.YYYY lub DD.MM
        m = re.search(r"(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?", data_str)
        if m:
            day = int(m.group(1))
            month = int(m.group(2))
            year = int(m.group(3)) if m.group(3) else now.year
            if year < 100:
                year += 2000
            try:
                target_date = datetime(year, month, day).date()
            except ValueError:
                return None
        else:
            return None

    try:
        return datetime(target_date.year, target_date.month, target_date.day, hour, minute, tzinfo=tz)
    except Exception:
        return None

def load_known_clan_ids() -> set[int]:
    if not os.path.exists(CLAN_MEMBERS_FILE):
        return set()
    try:
        with open(CLAN_MEMBERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data) if isinstance(data, list) else set()
    except Exception:
        return set()


def add_known_clan_id(user_id: int) -> None:
    current = load_known_clan_ids()
    if user_id not in current:
        current.add(user_id)
        try:
            with open(CLAN_MEMBERS_FILE, "w", encoding="utf-8") as f:
                json.dump(list(current), f, indent=2)
        except Exception as e:
            logging.error("Błąd zapisu clan_members.json: %s", e)


def remove_known_clan_id(user_id: int) -> None:
    current = load_known_clan_ids()
    if user_id in current:
        current.remove(user_id)
        try:
            with open(CLAN_MEMBERS_FILE, "w", encoding="utf-8") as f:
                json.dump(list(current), f, indent=2)
        except Exception as e:
            logging.error("Błąd zapisu clan_members.json: %s", e)


def _get_clan_role(guild: discord.Guild) -> discord.Role | None:
    if config.CLAN_ROLE_ID:
        role = guild.get_role(config.CLAN_ROLE_ID)
        if role:
            return role
    for r in guild.roles:
        if r.name.lower() in ("czlonek", "członek", "klanowicz"):
            return r
    return None


async def get_clan_members(guild: discord.Guild) -> list[discord.Member]:
    """Wyszukuje i zwraca listę wszystkich członków z rolą klanowicza (bez botów)."""
    clan_role = _get_clan_role(guild)
    if not clan_role:
        return []

    found: dict[int, discord.Member] = {}

    # 1. Sprawdź cache bota
    for m in clan_role.members:
        if not m.bot:
            found[m.id] = m
            add_known_clan_id(m.id)

    # 2. Sprawdź znane ID z bazy danych
    known_ids = load_known_clan_ids()
    for uid in known_ids:
        if uid not in found:
            m = guild.get_member(uid)
            if m is None:
                try:
                    m = await guild.fetch_member(uid)
                except (discord.NotFound, discord.HTTPException):
                    m = None
            if m and not m.bot and clan_role in m.roles:
                found[m.id] = m

    # 3. Jeśli lista jest mała, przeskanuj historię kanałów tekstowych
    if len(found) < 30:
        for ch in guild.text_channels:
            if not ch.permissions_for(guild.me).read_message_history:
                continue
            try:
                async for msg in ch.history(limit=40):
                    if msg.author.bot or msg.author.id in found:
                        continue
                    m = guild.get_member(msg.author.id)
                    if m is None:
                        try:
                            m = await guild.fetch_member(msg.author.id)
                        except (discord.NotFound, discord.HTTPException):
                            continue
                    if m and not m.bot and clan_role in m.roles:
                        found[m.id] = m
                        add_known_clan_id(m.id)
            except Exception:
                continue

    return list(found.values())


def _is_staff_or_admin(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    return (
        interaction.user.guild_permissions.administrator
        or any(r.id == config.STAFF_ROLE_ID for r in interaction.user.roles)
    )


# ══════════════════════════════════════════════════════════════════
#  COG: Treasury & Clan Events
# ══════════════════════════════════════════════════════════════════

class Treasury(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.check_reminders_task.start()

    def cog_unload(self) -> None:
        self.check_reminders_task.cancel()

    @tasks.loop(seconds=30)
    async def check_reminders_task(self) -> None:
        """Automatycznie wysyła przypomnienie przed zbiórką na DM klanowiczów."""
        try:
            items = load_zbiorki()
            if not items:
                return

            now_ts = datetime.now().astimezone().timestamp()
            updated = False

            for item in items:
                if item.get("reminder_sent") or item.get("cancelled"):
                    continue

                rem_ts = item.get("reminder_timestamp", 0)
                tgt_ts = item.get("target_timestamp", 0)

                # Sprawdź, czy nadszedł czas przypomnienia (i czy zbiórka nie minęła dawniej niż godzinę temu)
                if rem_ts <= now_ts < tgt_ts + 3600:
                    guild = self.bot.get_guild(item.get("guild_id", 0))
                    if guild:
                        members = await get_clan_members(guild)
                        rem_min = item.get("reminder_minutes", 15)

                        rem_embed = discord.Embed(
                            title=f"⏰ PRZYPOMNIENIE: Zbiórka za {rem_min} minut! | Gildia PVP0",
                            description=f"Zbliża się zbiórka gildii **PVP0**! Zostało około **{rem_min} minut** — wbijaj do gry i na kanał głosowy! ⚔️",
                            color=0xF1C40F,
                            timestamp=datetime.now(timezone.utc),
                        )
                        rem_embed.add_field(name="📅 Data", value=f"**{item.get('data_str', 'Dzisiaj')}**", inline=True)
                        rem_embed.add_field(name="⏰ Godzina", value=f"**{item.get('godzina_str', '')}**", inline=True)
                        rem_embed.add_field(name="🎯 Cel", value=f"**{item.get('cel', '')}**", inline=False)
                        if item.get("created_by"):
                            rem_embed.add_field(name="📢 Zarządził", value=f"<@{item['created_by']}>", inline=False)
                        rem_embed.set_footer(text=config.FOOTER_TEXT_ZBIORKA)
                        if guild.icon:
                            rem_embed.set_thumbnail(url=guild.icon.url)

                        for member in members:
                            try:
                                await member.send(embed=rem_embed)
                            except (discord.Forbidden, discord.HTTPException):
                                pass
                            await asyncio.sleep(0.4)

                    item["reminder_sent"] = True
                    updated = True

            if updated:
                save_zbiorki(items)
        except Exception as e:
            logging.error("Błąd w check_reminders_task: %s", e)

    # ──────────────────────────────────────────────────────────────
    # 1. KOMENDA /zbiorka
    # ──────────────────────────────────────────────────────────────
    @app_commands.command(
        name="zbiorka",
        description="Wyślij pilny alarm o zbiórce gildii PVP0 do wszystkich klanowiczów na DM.",
    )
    @app_commands.describe(
        data="Data zbiórki (np. Dzisiaj, 31.10, Piątek)",
        godzina="Godzina zbiórki (np. 19:00, 20:30)",
        cel="Cel zbiórki (np. Rajd na bazę wroga, klepa, zamek)",
        przypomnienie_minut="Za ile minut przed zbiórką wysłać automatyczne przypomnienie? (domyślnie 15)",
    )
    @app_commands.choices(
        przypomnienie_minut=[
            app_commands.Choice(name="15 minut przed (domyślnie)", value=15),
            app_commands.Choice(name="10 minut przed", value=10),
            app_commands.Choice(name="30 minut przed", value=30),
            app_commands.Choice(name="5 minut przed", value=5),
            app_commands.Choice(name="Brak przypomnienia", value=0),
        ]
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def zbiorka(
        self,
        interaction: discord.Interaction,
        data: str,
        godzina: str,
        cel: str,
        przypomnienie_minut: int = 15,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Ta komenda może być użyta tylko na serwerze.", ephemeral=True)
            return

        if not _is_staff_or_admin(interaction):
            await interaction.response.send_message("❌ Tylko administratorzy i zarząd mogą zarządzać zbiórkę.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        clan_role = _get_clan_role(interaction.guild)
        if not clan_role:
            await interaction.followup.send(
                "❌ Nie znaleziono roli klanowicza na serwerze. Upewnij się, że rola istnieje i jest poprawnie skonfigurowana.",
                ephemeral=True,
            )
            return

        members = await get_clan_members(interaction.guild)
        if not members:
            await interaction.followup.send(
                f"⚠️ Nie znaleziono żadnych członków z rolą {clan_role.mention} na serwerze.",
                ephemeral=True,
            )
            return

        # Estetyczny czerwony embed alarmowy
        embed = discord.Embed(
            title="⚔️ ALARM: Zbiórka Gildii PVP0",
            description="Ogłoszono oficjalną zbiórkę członków gildii **PVP0**! Twoja obecność jest obowiązkowa.",
            color=config.COLOR_ALARM,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="📅 Data", value=f"**{data}**", inline=True)
        embed.add_field(name="⏰ Godzina", value=f"**{godzina}**", inline=True)
        embed.add_field(name="🎯 Cel zbiórki", value=f"**{cel}**", inline=False)
        embed.add_field(name="📢 Zarządził", value=f"{interaction.user.mention}", inline=False)
        embed.set_footer(text=config.FOOTER_TEXT_ZBIORKA)
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        sent_count = 0
        blocked_count = 0

        for member in members:
            try:
                await member.send(embed=embed)
                sent_count += 1
            except discord.Forbidden:
                blocked_count += 1
            except discord.HTTPException:
                blocked_count += 1
            await asyncio.sleep(0.4)

        # Planowanie automatycznego przypomnienia
        reminder_info = "Nie zaplanowano (opcja wyłączona)."
        if przypomnienie_minut > 0:
            target_dt = parse_meeting_datetime(data, godzina)
            if target_dt:
                now_dt = datetime.now().astimezone()
                reminder_dt = target_dt - timedelta(minutes=przypomnienie_minut)
                if reminder_dt > now_dt:
                    z_items = load_zbiorki()
                    z_items.append({
                        "id": str(interaction.id),
                        "guild_id": interaction.guild.id,
                        "data_str": data,
                        "godzina_str": godzina,
                        "cel": cel,
                        "target_timestamp": target_dt.timestamp(),
                        "reminder_timestamp": reminder_dt.timestamp(),
                        "reminder_minutes": przypomnienie_minut,
                        "created_by": interaction.user.id,
                        "reminder_sent": False,
                    })
                    save_zbiorki(z_items)
                    reminder_info = f"✅ Zaplanowano na **{reminder_dt.strftime('%H:%M')}** ({przypomnienie_minut} min przed zbiórką)."
                elif target_dt > now_dt:
                    reminder_info = "⚠️ Do zbiórki zostało mniej czasu niż wybrane przypomnienie."
                else:
                    reminder_info = "⚠️ Podana data/godzina już minęła."
            else:
                reminder_info = "⚠️ Nie udało się rozpoznać formatu daty/godziny do automatycznego przypomnienia."

        report_embed = discord.Embed(
            title="📢 Raport z wysyłki zbiórki",
            description=f"Wysłano powiadomienia o zbiórce dla roli {clan_role.mention}.",
            color=config.COLOR_SUCCESS if sent_count > 0 else config.COLOR_CLOSE,
        )
        report_embed.add_field(name="✅ Wysłano pomyślnie", value=f"**{sent_count}**", inline=True)
        report_embed.add_field(name="🚫 Zablokowane DM", value=f"**{blocked_count}**", inline=True)
        report_embed.add_field(name="👥 Wszyscy klanowicze", value=f"**{len(members)}**", inline=True)
        report_embed.add_field(name="⏰ Automatyczne przypomnienie", value=reminder_info, inline=False)
        report_embed.set_footer(text=config.FOOTER_TEXT_ZBIORKA)

        await interaction.followup.send(embed=report_embed, ephemeral=True)

    @zbiorka.error
    async def zbiorka_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.errors.MissingPermissions):
            msg = "❌ Ta komenda jest dostępna tylko dla Administratorów."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)

    # ──────────────────────────────────────────────────────────────
    # 2. KOMENDA /zbiorka_przeloz
    # ──────────────────────────────────────────────────────────────
    @app_commands.command(
        name="zbiorka_przeloz",
        description="Przełóż termin aktywnej zbiórki gildii PVP0 i powiadom klanowiczów na DM.",
    )
    @app_commands.describe(
        nowa_data="Nowa data zbiórki (np. Dzisiaj, Jutro, 01.11, Sobota)",
        nowa_godzina="Nowa godzina zbiórki (np. 20:00, 20:30)",
        powod="Powód przełożenia zbiórki (np. Sprawy prywatne, brak frekwencji)",
        przypomnienie_minut="Za ile minut przed nowym terminem wysłać przypomnienie? (domyślnie 15)",
    )
    @app_commands.choices(
        przypomnienie_minut=[
            app_commands.Choice(name="15 minut przed (domyślnie)", value=15),
            app_commands.Choice(name="10 minut przed", value=10),
            app_commands.Choice(name="30 minut przed", value=30),
            app_commands.Choice(name="5 minut przed", value=5),
            app_commands.Choice(name="Brak przypomnienia", value=0),
        ]
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def zbiorka_przeloz(
        self,
        interaction: discord.Interaction,
        nowa_data: str,
        nowa_godzina: str,
        powod: str = "Brak podanego powodu",
        przypomnienie_minut: int = 15,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Ta komenda może być użyta tylko na serwerze.", ephemeral=True)
            return

        if not _is_staff_or_admin(interaction):
            await interaction.response.send_message("❌ Tylko administratorzy i zarząd mogą zarządzać zbiórką.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        items = load_zbiorki()
        active_item = None
        now_ts = datetime.now().astimezone().timestamp()
        for it in reversed(items):
            if it.get("guild_id") == interaction.guild.id and not it.get("cancelled", False):
                if it.get("target_timestamp", 0) + 7200 > now_ts:
                    active_item = it
                    break

        if not active_item:
            await interaction.followup.send(
                "⚠️ Nie znaleziono żadnej aktywnej zbiórki do przełożenia. Użyj najpierw `/zbiorka`, aby zaplanować zbiórkę.",
                ephemeral=True,
            )
            return

        clan_role = _get_clan_role(interaction.guild)
        if not clan_role:
            await interaction.followup.send(
                "❌ Nie znaleziono roli klanowicza na serwerze.",
                ephemeral=True,
            )
            return

        members = await get_clan_members(interaction.guild)
        if not members:
            await interaction.followup.send(
                f"⚠️ Nie znaleziono żadnych członków z rolą {clan_role.mention} na serwerze.",
                ephemeral=True,
            )
            return

        # Obliczanie nowego czasu i przypomnienia
        target_dt = parse_meeting_datetime(nowa_data, nowa_godzina)
        now_dt = datetime.now().astimezone()

        active_item["data_str"] = nowa_data
        active_item["godzina_str"] = nowa_godzina
        active_item["reminder_sent"] = False

        reminder_info = "Nie zaplanowano (opcja wyłączona)."
        if target_dt:
            active_item["target_timestamp"] = target_dt.timestamp()
            if przypomnienie_minut > 0:
                reminder_dt = target_dt - timedelta(minutes=przypomnienie_minut)
                if reminder_dt > now_dt:
                    active_item["reminder_timestamp"] = reminder_dt.timestamp()
                    active_item["reminder_minutes"] = przypomnienie_minut
                    reminder_info = f"✅ Zaplanowano na **{reminder_dt.strftime('%H:%M')}** ({przypomnienie_minut} min przed nowym terminem)."
                elif target_dt > now_dt:
                    active_item["reminder_timestamp"] = 0
                    reminder_info = "⚠️ Do nowego terminu zostało mniej czasu niż wybrane przypomnienie."
                else:
                    active_item["reminder_timestamp"] = 0
                    reminder_info = "⚠️ Nowy termin jest już w przeszłości."
            else:
                active_item["reminder_timestamp"] = 0
        else:
            reminder_info = "⚠️ Nie udało się rozpoznać formatu nowej daty/godziny."

        save_zbiorki(items)

        # Niebieski embed informujący o zmianie terminu
        embed = discord.Embed(
            title="🔄 ZMIANA TERMINU: Zbiórka Gildii PVP0",
            description="Termin zbiórki gildii **PVP0** został zmieniony przez zarząd! Prosimy o zapoznanie się z nową datą i godziną.",
            color=0x3498DB,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="📅 Nowa data", value=f"**{nowa_data}**", inline=True)
        embed.add_field(name="⏰ Nowa godzina", value=f"**{nowa_godzina}**", inline=True)
        embed.add_field(name="🎯 Cel zbiórki", value=f"**{active_item.get('cel', 'Zbiórka')}**", inline=False)
        embed.add_field(name="📝 Powód zmiany", value=f"*{powod}*", inline=False)
        embed.add_field(name="📢 Zarządził", value=f"{interaction.user.mention}", inline=False)
        embed.set_footer(text=config.FOOTER_TEXT_ZBIORKA)
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        sent_count = 0
        blocked_count = 0

        for member in members:
            try:
                await member.send(embed=embed)
                sent_count += 1
            except discord.Forbidden:
                blocked_count += 1
            except discord.HTTPException:
                blocked_count += 1
            await asyncio.sleep(0.4)

        report_embed = discord.Embed(
            title="🔄 Zaktualizowano termin zbiórki",
            description=f"Powiadomiono klanowiczów o nowym terminie zbiórki dla roli {clan_role.mention}.",
            color=config.COLOR_SUCCESS if sent_count > 0 else config.COLOR_CLOSE,
        )
        report_embed.add_field(name="✅ Wysłano pomyślnie", value=f"**{sent_count}**", inline=True)
        report_embed.add_field(name="🚫 Zablokowane DM", value=f"**{blocked_count}**", inline=True)
        report_embed.add_field(name="👥 Wszyscy klanowicze", value=f"**{len(members)}**", inline=True)
        report_embed.add_field(name="⏰ Nowe przypomnienie", value=reminder_info, inline=False)
        report_embed.set_footer(text=config.FOOTER_TEXT_ZBIORKA)

        await interaction.followup.send(embed=report_embed, ephemeral=True)

    @zbiorka_przeloz.error
    async def zbiorka_przeloz_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.errors.MissingPermissions):
            msg = "❌ Ta komenda jest dostępna tylko dla Administratorów."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)

    # ──────────────────────────────────────────────────────────────
    # 3. KOMENDA /zbiorka_anuluj
    # ──────────────────────────────────────────────────────────────
    @app_commands.command(
        name="zbiorka_anuluj",
        description="Odwołaj aktywną zbiórkę gildii PVP0 i powiadom klanowiczów na DM.",
    )
    @app_commands.describe(
        powod="Powód odwołania zbiórki (np. Zmiana planów, brak czasu, brak frekwencji)",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def zbiorka_anuluj(
        self,
        interaction: discord.Interaction,
        powod: str = "Zbiórka została odwołana przez zarząd.",
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Ta komenda może być użyta tylko na serwerze.", ephemeral=True)
            return

        if not _is_staff_or_admin(interaction):
            await interaction.response.send_message("❌ Tylko administratorzy i zarząd mogą odwołać zbiórkę.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        items = load_zbiorki()
        active_item = None
        now_ts = datetime.now().astimezone().timestamp()
        for it in reversed(items):
            if it.get("guild_id") == interaction.guild.id and not it.get("cancelled", False):
                if it.get("target_timestamp", 0) + 7200 > now_ts:
                    active_item = it
                    break

        if not active_item:
            await interaction.followup.send(
                "⚠️ Nie znaleziono żadnej aktywnej zbiórki do odwołania.",
                ephemeral=True,
            )
            return

        clan_role = _get_clan_role(interaction.guild)
        if not clan_role:
            await interaction.followup.send(
                "❌ Nie znaleziono roli klanowicza na serwerze.",
                ephemeral=True,
            )
            return

        members = await get_clan_members(interaction.guild)

        # Oznacz zbiórkę jako odwołaną
        active_item["cancelled"] = True
        active_item["reminder_sent"] = True
        save_zbiorki(items)

        if not members:
            await interaction.followup.send(
                "✅ Odwołano zbiórkę, ale nie znaleziono klanowiczów do wysłania DM.",
                ephemeral=True,
            )
            return

        # Czerwony embed odwołania
        embed = discord.Embed(
            title="❌ ODWOŁANO: Zbiórka Gildii PVP0",
            description="Zaplanowana zbiórka gildii **PVP0** została **odwołana** przez administrację.",
            color=config.COLOR_CLOSE,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="📅 Odwołana data", value=f"**{active_item.get('data_str', 'Brak')}**", inline=True)
        embed.add_field(name="⏰ Odwołana godzina", value=f"**{active_item.get('godzina_str', 'Brak')}**", inline=True)
        embed.add_field(name="🎯 Cel zbiórki", value=f"**{active_item.get('cel', 'Zbiórka')}**", inline=False)
        embed.add_field(name="📝 Powód odwołania", value=f"*{powod}*", inline=False)
        embed.add_field(name="📢 Odwołał", value=f"{interaction.user.mention}", inline=False)
        embed.set_footer(text=config.FOOTER_TEXT_ZBIORKA)
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        sent_count = 0
        blocked_count = 0

        for member in members:
            try:
                await member.send(embed=embed)
                sent_count += 1
            except discord.Forbidden:
                blocked_count += 1
            except discord.HTTPException:
                blocked_count += 1
            await asyncio.sleep(0.4)

        report_embed = discord.Embed(
            title="❌ Zbiórka została pomyślnie odwołana",
            description=f"Wysłano informację o odwołaniu zbiórki do członków roli {clan_role.mention}.",
            color=config.COLOR_CLOSE,
        )
        report_embed.add_field(name="✅ Wysłano pomyślnie", value=f"**{sent_count}**", inline=True)
        report_embed.add_field(name="🚫 Zablokowane DM", value=f"**{blocked_count}**", inline=True)
        report_embed.add_field(name="👥 Wszyscy klanowicze", value=f"**{len(members)}**", inline=True)
        report_embed.set_footer(text=config.FOOTER_TEXT_ZBIORKA)

        await interaction.followup.send(embed=report_embed, ephemeral=True)

    @zbiorka_anuluj.error
    async def zbiorka_anuluj_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.errors.MissingPermissions):
            msg = "❌ Ta komenda jest dostępna tylko dla Administratorów."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Treasury(bot))

