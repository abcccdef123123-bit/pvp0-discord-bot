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


ANNOUNCEMENTS_FILE = os.path.join(DATA_DIR, "announcements.json")


def load_announcements() -> list[dict]:
    if not os.path.exists(ANNOUNCEMENTS_FILE):
        return []
    try:
        with open(ANNOUNCEMENTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def save_announcements(items: list[dict]) -> None:
    try:
        with open(ANNOUNCEMENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error("Błąd zapisu announcements.json: %s", e)


def record_announcement(msg_id: int, channel_id: int, guild_id: int, title: str, content: str, author_id: int, is_poll: bool = False) -> None:
    items = load_announcements()
    items.append({
        "message_id": msg_id,
        "channel_id": channel_id,
        "guild_id": guild_id,
        "title": title,
        "content": content,
        "author_id": author_id,
        "is_poll": is_poll,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "deleted": False,
    })
    save_announcements(items)


def mark_announcement_deleted(msg_id: int) -> None:
    items = load_announcements()
    for it in items:
        if it.get("message_id") == msg_id:
            it["deleted"] = True
    save_announcements(items)


def update_announcement_record(msg_id: int, new_title: str, new_content: str) -> None:
    items = load_announcements()
    for it in items:
        if it.get("message_id") == msg_id:
            it["title"] = new_title
            it["content"] = new_content
            it["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_announcements(items)


def get_last_active_announcement(guild_id: int) -> dict | None:
    items = load_announcements()
    for it in reversed(items):
        if it.get("guild_id") == guild_id and not it.get("deleted", False):
            return it
    return None


def parse_message_id(raw: str | None) -> int | None:
    if not raw:
        return None
    matches = re.findall(r"\d{17,21}", raw)
    if matches:
        return int(matches[-1])
    return None


POLLS_FILE = os.path.join(DATA_DIR, "polls.json")


def load_polls() -> dict[str, dict]:
    if not os.path.exists(POLLS_FILE):
        return {}
    try:
        with open(POLLS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_polls(data: dict) -> None:
    try:
        with open(POLLS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error("Błąd zapisu polls.json: %s", e)


def record_poll(msg_id: int) -> None:
    data = load_polls()
    data[str(msg_id)] = {"yes_votes": [], "no_votes": []}
    save_polls(data)


def is_poll_message(msg_id: int) -> bool:
    data = load_polls()
    return str(msg_id) in data


def get_poll_votes(msg_id: int) -> tuple[list[int], list[int]]:
    data = load_polls()
    poll = data.get(str(msg_id), {"yes_votes": [], "no_votes": []})
    return poll.get("yes_votes", []), poll.get("no_votes", [])


def register_vote(msg_id: int, user_id: int, choice: str) -> tuple[bool, str, int, int]:
    """Rejestruje głos i zwraca (czy_zmieniono_glos, komunikat, yes_count, no_count)."""
    data = load_polls()
    str_id = str(msg_id)
    if str_id not in data:
        data[str_id] = {"yes_votes": [], "no_votes": []}

    yes_list = [int(x) for x in data[str_id].get("yes_votes", [])]
    no_list = [int(x) for x in data[str_id].get("no_votes", [])]

    if choice == "yes":
        if user_id in yes_list:
            return False, "ℹ️ Twój głos na **TAK** został już wcześniej zarejestrowany.", len(yes_list), len(no_list)
        if user_id in no_list:
            no_list.remove(user_id)
            msg = "🔄 Zmieniono Twój głos na: **TAK** ✅!"
        else:
            msg = "✅ Oddano głos na: **TAK**!"
        yes_list.append(user_id)
    else:  # choice == "no"
        if user_id in no_list:
            return False, "ℹ️ Twój głos na **NIE** został już wcześniej zarejestrowany.", len(yes_list), len(no_list)
        if user_id in yes_list:
            yes_list.remove(user_id)
            msg = "🔄 Zmieniono Twój głos na: **NIE** ❌!"
        else:
            msg = "❌ Oddano głos na: **NIE**!"
        no_list.append(user_id)

    data[str_id]["yes_votes"] = yes_list
    data[str_id]["no_votes"] = no_list
    save_polls(data)
    return True, msg, len(yes_list), len(no_list)


def make_poll_progress_bar(yes_count: int, no_count: int, total_length: int = 12) -> str:
    total = yes_count + no_count
    if total == 0:
        return "░" * total_length
    yes_pct = yes_count / total
    green_blocks = int(round(yes_pct * total_length))
    red_blocks = total_length - green_blocks
    return ("🟩" * green_blocks) + ("🟥" * red_blocks)


def format_voters_list(user_ids: list[int], max_display: int = 25) -> str:
    if not user_ids:
        return "*Brak*"
    displayed = user_ids[:max_display]
    mentions = [f"<@{uid}>" for uid in displayed]
    res = ", ".join(mentions)
    if len(user_ids) > max_display:
        res += f" *...i {len(user_ids) - max_display} więcej*"
    if len(res) > 1000:
        res = res[:990] + "..."
    return res


def update_poll_embed(embed: discord.Embed, yes_votes: list[int], no_votes: list[int]) -> discord.Embed:
    yes_count = len(yes_votes)
    no_count = len(no_votes)
    total = yes_count + no_count
    yes_pct = int(round((yes_count / total) * 100)) if total > 0 else 0
    no_pct = 100 - yes_pct if total > 0 else 0
    bar = make_poll_progress_bar(yes_count, no_count)

    poll_text = (
        f"✅ **TAK:** `{yes_count}` ({yes_pct}%)\n"
        f"❌ **NIE:** `{no_count}` ({no_pct}%)\n"
        f"`[{bar}]` 👥 Łącznie: **{total}**\n"
        "*(Użyj przycisków poniżej, aby oddać lub zmienić swój głos)*"
    )

    yes_list_text = format_voters_list(yes_votes)
    no_list_text = format_voters_list(no_votes)

    # Usuń ewentualne stare pola ankiety, aby nie dublować
    clean_fields = []
    for field in embed.fields:
        fname = field.name.lower()
        if any(keyword in fname for keyword in ("głosowanie", "wyniki", "głosy na tak", "głosy na nie", "ankieta")):
            continue
        clean_fields.append(field)

    embed.clear_fields()
    for f in clean_fields:
        embed.add_field(name=f.name, value=f.value, inline=f.inline)

    embed.add_field(name="🗳️ Wyniki ankiety", value=poll_text, inline=False)
    embed.add_field(name=f"✅ Głosy na TAK ({yes_count})", value=yes_list_text, inline=True)
    embed.add_field(name=f"❌ Głosy na NIE ({no_count})", value=no_list_text, inline=True)

    return embed


async def handle_poll_vote(interaction: discord.Interaction, choice: str) -> None:
    if not interaction.message:
        await interaction.response.send_message("❌ Nie można zarejestrować głosu dla tej wiadomości.", ephemeral=True)
        return

    msg = interaction.message
    user_id = interaction.user.id
    changed, user_msg, yes_count, no_count = register_vote(msg.id, user_id, choice)

    await interaction.response.send_message(user_msg, ephemeral=True)

    if changed and msg.embeds:
        try:
            yes_votes, no_votes = get_poll_votes(msg.id)
            new_embed = update_poll_embed(msg.embeds[0].copy(), yes_votes, no_votes)
            new_view = PollVoteView(len(yes_votes), len(no_votes))
            await msg.edit(embed=new_embed, view=new_view)
        except Exception as e:
            logging.error("Błąd aktualizacji embedu ankiety: %s", e)


class PollVoteView(discord.ui.View):
    def __init__(self, yes_count: int = 0, no_count: int = 0) -> None:
        super().__init__(timeout=None)
        label_yes = f"TAK ({yes_count})" if yes_count > 0 else "TAK"
        label_no = f"NIE ({no_count})" if no_count > 0 else "NIE"

        self.yes_button = discord.ui.Button(
            label=label_yes,
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id="pvp0:poll:yes",
        )
        self.yes_button.callback = self.on_vote_yes
        self.add_item(self.yes_button)

        self.no_button = discord.ui.Button(
            label=label_no,
            emoji="❌",
            style=discord.ButtonStyle.danger,
            custom_id="pvp0:poll:no",
        )
        self.no_button.callback = self.on_vote_no
        self.add_item(self.no_button)

    async def on_vote_yes(self, interaction: discord.Interaction) -> None:
        await handle_poll_vote(interaction, "yes")

    async def on_vote_no(self, interaction: discord.Interaction) -> None:
        await handle_poll_vote(interaction, "no")


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


def _get_announcements_channel(guild: discord.Guild) -> discord.TextChannel | None:
    ann_id = getattr(config, "ANNOUNCEMENTS_CHANNEL_ID", None)
    if ann_id:
        ch = guild.get_channel(ann_id)
        if isinstance(ch, discord.TextChannel):
            return ch
    for ch in guild.text_channels:
        name = ch.name.lower()
        if "ogłoszen" in name or "ogloszen" in name or "announcement" in name:
            return ch
    return None


async def _find_target_announcement(
    guild: discord.Guild,
    channel: discord.TextChannel,
    raw_id: str | None,
    bot_user: discord.ClientUser,
) -> tuple[discord.Message | None, str | None]:
    """Wyszukuje wiadomość ogłoszenia po ID/linku lub znajduje ostatnie aktywne ogłoszenie bota."""
    mid = parse_message_id(raw_id)
    if mid:
        try:
            msg = await channel.fetch_message(mid)
            return msg, None
        except discord.NotFound:
            return None, f"❌ Nie znaleziono wiadomości o ID `{mid}` na kanale {channel.mention}."
        except discord.Forbidden:
            return None, f"❌ Bot nie ma uprawnień do odczytania wiadomości na kanale {channel.mention}."
        except discord.HTTPException as e:
            return None, f"❌ Błąd pobierania wiadomości: {e}"

    # Brak podanego ID - sprawdzamy ostatnie zarejestrowane ogłoszenie
    last_record = get_last_active_announcement(guild.id)
    if last_record:
        try:
            msg = await channel.fetch_message(last_record["message_id"])
            return msg, None
        except (discord.NotFound, discord.HTTPException):
            mark_announcement_deleted(last_record["message_id"])

    # Fallback: przeszukaj 30 ostatnich wiadomości na kanale za wiadomością bota z embedem
    try:
        async for m in channel.history(limit=30):
            if m.author.id == bot_user.id and m.embeds:
                return m, None
    except Exception:
        pass

    return None, f"⚠️ Nie znaleziono żadnego ogłoszenia do edycji/usunięcia na kanale {channel.mention}. Podaj ID wiadomości w parametrze."


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


async def get_role_members(guild: discord.Guild, role: discord.Role) -> list[discord.Member]:
    """Wyszukuje i zwraca wszystkich członków serwera posiadających daną rolę."""
    found: dict[int, discord.Member] = {}

    # 1. Sprawdź members z roli w pamięci podręcznej
    for m in role.members:
        if not m.bot:
            found[m.id] = m

    # 2. Jeśli serwer ma więcej członków niż w pamięci podręcznej, spróbuj chunk
    if len(found) < guild.member_count:
        try:
            await guild.chunk()
            for m in role.members:
                if not m.bot:
                    found[m.id] = m
        except Exception:
            pass

    # 3. Sprawdź fetch_members
    try:
        async for m in guild.fetch_members(limit=None):
            if not m.bot and role in m.roles:
                found[m.id] = m
    except Exception:
        pass

    # 4. Jeśli nadal mało członków (np. brak Server Members Intent na bramie), przeszukaj historię kanałów tekstowych
    for ch in guild.text_channels:
        if not ch.permissions_for(guild.me).read_message_history:
            continue
        try:
            async for msg in ch.history(limit=50):
                if msg.author.bot or msg.author.id in found:
                    continue
                m = guild.get_member(msg.author.id)
                if m is None:
                    try:
                        m = await guild.fetch_member(msg.author.id)
                    except Exception:
                        continue
                if m and not m.bot and role in m.roles:
                    found[m.id] = m
        except Exception:
            continue

    # 5. Sprawdź bazę znanych klanowiczów
    known_ids = load_known_clan_ids()
    for uid in known_ids:
        if uid not in found:
            m = guild.get_member(uid)
            if m is None:
                try:
                    m = await guild.fetch_member(uid)
                except Exception:
                    m = None
            if m and not m.bot and role in m.roles:
                found[m.id] = m

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

    # ══════════════════════════════════════════════════════════════════
    #  MODUŁ OGŁOSZEŃ: /ogloszenie (wyslij, zmien, usun)
    # ══════════════════════════════════════════════════════════════════
    ogloszenie_group = app_commands.Group(
        name="ogloszenie",
        description="Zarządzanie oficjalnymi ogłoszeniami gildii PVP0",
        default_permissions=discord.Permissions(administrator=True),
    )

    # ── Logika obsługi ogłoszeń (współdzielona z aliasami) ───────────
    async def _do_ogloszenie_wyslij(
        self,
        interaction: discord.Interaction,
        tytul: str,
        tresc: str,
        ankieta: bool = False,
        wyslij_pv: bool = False,
        ping: bool = False,
        zdjecie_url: str | None = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Ta komenda może być użyta tylko na serwerze.", ephemeral=True)
            return

        if not _is_staff_or_admin(interaction):
            await interaction.response.send_message(
                "❌ Ta komenda jest dostępna tylko dla Zarządu / Administratorów.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        channel = _get_announcements_channel(interaction.guild)
        if not channel:
            await interaction.followup.send(
                "❌ Nie znaleziono kanału ogłoszeń!\n"
                "Ustaw go za pomocą komendy `/ustaw kanal typ:📢 Kanał Ogłoszeń (#ogłoszenia) kanal:#twoj-kanal` "
                "lub utwórz kanał tekstowy zawierający w nazwie `ogłoszenia`.",
                ephemeral=True,
            )
            return

        clan_role = _get_clan_role(interaction.guild)
        members = await get_clan_members(interaction.guild) if wyslij_pv else []

        embed_title = f"🗳️ ANKIETA: {tytul}" if (ankieta and not tytul.lower().startswith(("ankieta", "🗳️"))) else f"📢 {tytul}"
        embed = discord.Embed(
            title=embed_title,
            description=tresc,
            color=0x38BDF8 if ankieta else config.COLOR_TICKET,
            timestamp=datetime.now(timezone.utc),
        )
        if interaction.guild.icon:
            embed.set_author(name=f"Gildia PVP0 • {interaction.guild.name}", icon_url=interaction.guild.icon.url)
            embed.set_thumbnail(url=interaction.guild.icon.url)
        else:
            embed.set_author(name="Gildia PVP0")

        if zdjecie_url and zdjecie_url.strip().startswith(("http://", "https://")):
            embed.set_image(url=zdjecie_url.strip())

        embed.set_footer(text=f"{config.FOOTER_TEXT_ZBIORKA} • Ogłosił: {interaction.user.display_name}")

        view = None
        if ankieta:
            embed = update_poll_embed(embed, [], [])
            view = PollVoteView(0, 0)

        content_ping = None
        if ping:
            if clan_role:
                content_ping = clan_role.mention
            else:
                content_ping = "@everyone"

        try:
            channel_msg = await channel.send(content=content_ping, embed=embed, view=view)
        except Exception as e:
            await interaction.followup.send(
                f"❌ Wystąpił błąd podczas wysyłania ogłoszenia na kanał {channel.mention}: {e}",
                ephemeral=True,
            )
            return

        if ankieta:
            record_poll(channel_msg.id)

        # Zapisz ogłoszenie w bazie danych
        record_announcement(channel_msg.id, channel.id, interaction.guild.id, tytul, tresc, interaction.user.id, is_poll=ankieta)

        sent_count = 0
        blocked_count = 0

        if wyslij_pv and members:
            dm_embed = embed.copy()
            if ankieta:
                dm_embed.add_field(
                    name="🗳️ Zagłosuj w ankiecie",
                    value=f"To ogłoszenie zawiera ankietę (TAK / NIE)!\n👉 **[Kliknij tutaj, aby oddać swój głos na kanale #{channel.name}]({channel_msg.jump_url})**",
                    inline=False,
                )
            else:
                dm_embed.add_field(
                    name="🔗 Wiadomość na serwerze",
                    value=f"[Kliknij tutaj, aby zobaczyć ogłoszenie na #{channel.name}]({channel_msg.jump_url})",
                    inline=False,
                )

            for member in members:
                if member.bot:
                    continue
                try:
                    await member.send(embed=dm_embed)
                    sent_count += 1
                except (discord.Forbidden, discord.HTTPException):
                    blocked_count += 1
                await asyncio.sleep(0.35)

        pv_desc = " oraz rozesłane w wiadomościach prywatnych (PV) do członków klanu." if wyslij_pv else "."
        report_embed = discord.Embed(
            title="🗳️ Ankieta wysłana pomyślnie!" if ankieta else "📢 Ogłoszenie wysłane pomyślnie!",
            description=(
                f"Twoje {'pytanie z ankietą (TAK/NIE)' if ankieta else 'ogłoszenie'} zostało opublikowane na kanale {channel.mention}{pv_desc}\n\n"
                f"🔗 **[Przejdź do wpisu]({channel_msg.jump_url})**"
            ),
            color=config.COLOR_SUCCESS,
            timestamp=datetime.now(timezone.utc),
        )
        report_embed.add_field(name="📢 Kanał", value=channel.mention, inline=True)
        report_embed.add_field(name="🗳️ Tryb", value="Ankieta (Przyciski: TAK / NIE)" if ankieta else "Zwykłe ogłoszenie", inline=True)
        if wyslij_pv:
            report_embed.add_field(name="📨 Wysyłka PV", value="Włączona", inline=True)
            report_embed.add_field(name="✅ Wysłano na PV", value=f"**{sent_count}**", inline=True)
            report_embed.add_field(name="🚫 Zablokowane DM", value=f"**{blocked_count}**", inline=True)
            report_embed.add_field(
                name="👥 Łącznie klanowiczów",
                value=f"**{len(members)}** (z rolą {clan_role.mention if clan_role else 'Brak'})",
                inline=False,
            )
        else:
            report_embed.add_field(name="📨 Wysyłka PV", value="Wyłączona (tylko kanał)", inline=True)

        report_embed.set_footer(text=config.FOOTER_TEXT_ZBIORKA)

        await interaction.followup.send(embed=report_embed, ephemeral=True)

    # ── /ogloszenie wyslij ───────────────────────────────────────────
    @ogloszenie_group.command(
        name="wyslij",
        description="Wysyła oficjalne ogłoszenie lub ankietę na kanał #ogłoszenia (oraz opcjonalnie na PV).",
    )
    @app_commands.describe(
        tytul="Tytuł ogłoszenia lub ankiety (np. Nowy sojusz, Ważna informacja, Głosowanie)",
        tresc="Treść ogłoszenia lub pytanie w ankiecie",
        ankieta="Czy to ogłoszenie jest ankietą/pytaniem z przyciskami TAK / NIE? (Domyślnie: Nie)",
        wyslij_pv="Czy wysłać to ogłoszenie również w wiadomości prywatnej (PV) do członków klanu? (Domyślnie: Nie)",
        ping="Czy oznaczyć rolę klanu na kanale ogłoszeń? (Domyślnie: Nie)",
        zdjecie_url="Opcjonalny link do obrazka/grafiki do embedu",
    )
    async def ogloszenie_wyslij(
        self,
        interaction: discord.Interaction,
        tytul: str,
        tresc: str,
        ankieta: bool = False,
        wyslij_pv: bool = False,
        ping: bool = False,
        zdjecie_url: str | None = None,
    ) -> None:
        await self._do_ogloszenie_wyslij(interaction, tytul, tresc, ankieta, wyslij_pv, ping, zdjecie_url)

    # ── Logika edycji ogłoszenia (współdzielona z aliasem) ───────────
    async def _do_ogloszenie_zmien(
        self,
        interaction: discord.Interaction,
        nowa_tresc: str,
        nowy_tytul: str | None = None,
        wiadomosc_id: str | None = None,
        nowe_zdjecie_url: str | None = None,
        powiadom_pv: bool = False,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Ta komenda może być użyta tylko na serwerze.", ephemeral=True)
            return

        if not _is_staff_or_admin(interaction):
            await interaction.response.send_message(
                "❌ Ta komenda jest dostępna tylko dla Zarządu / Administratorów.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        channel = _get_announcements_channel(interaction.guild)
        if not channel:
            await interaction.followup.send(
                "❌ Nie znaleziono kanału ogłoszeń!\n"
                "Ustaw go za pomocą komendy `/ustaw kanal typ:📢 Kanał Ogłoszeń (#ogłoszenia) kanal:#twoj-kanal`.",
                ephemeral=True,
            )
            return

        target_msg, err = await _find_target_announcement(interaction.guild, channel, wiadomosc_id, self.bot.user)
        if err or not target_msg:
            await interaction.followup.send(err or "❌ Nie znaleziono ogłoszenia do edycji.", ephemeral=True)
            return

        if not target_msg.embeds:
            await interaction.followup.send("❌ Wybrana wiadomość nie posiada embedu ogłoszenia.", ephemeral=True)
            return

        old_embed = target_msg.embeds[0]
        title = f"📢 {nowy_tytul.strip()}" if (nowy_tytul and nowy_tytul.strip()) else (old_embed.title or "📢 Ogłoszenie")

        new_embed = discord.Embed(
            title=title,
            description=nowa_tresc,
            color=old_embed.color or config.COLOR_TICKET,
            timestamp=datetime.now(timezone.utc),
        )
        if old_embed.author:
            new_embed.set_author(name=old_embed.author.name, icon_url=old_embed.author.icon_url)
        elif interaction.guild.icon:
            new_embed.set_author(name=f"Gildia PVP0 • {interaction.guild.name}", icon_url=interaction.guild.icon.url)
        else:
            new_embed.set_author(name="Gildia PVP0")

        if old_embed.thumbnail:
            new_embed.set_thumbnail(url=old_embed.thumbnail.url)
        elif interaction.guild.icon:
            new_embed.set_thumbnail(url=interaction.guild.icon.url)

        # Obsługa obrazka
        if nowe_zdjecie_url:
            cleaned = nowe_zdjecie_url.strip().lower()
            if cleaned in ("brak", "usun", "none", "remove", "nie"):
                pass
            elif nowe_zdjecie_url.strip().startswith(("http://", "https://")):
                new_embed.set_image(url=nowe_zdjecie_url.strip())
        elif old_embed.image and old_embed.image.url:
            new_embed.set_image(url=old_embed.image.url)

        new_embed.set_footer(text=f"{config.FOOTER_TEXT_ZBIORKA} • Zaktualizował: {interaction.user.display_name}")

        is_poll = is_poll_message(target_msg.id)
        edit_view = None
        if is_poll:
            yes_votes, no_votes = get_poll_votes(target_msg.id)
            new_embed = update_poll_embed(new_embed, yes_votes, no_votes)
            edit_view = PollVoteView(len(yes_votes), len(no_votes))

        try:
            if edit_view is not None:
                await target_msg.edit(embed=new_embed, view=edit_view)
            else:
                await target_msg.edit(embed=new_embed)
        except Exception as e:
            await interaction.followup.send(f"❌ Błąd podczas edycji ogłoszenia: {e}", ephemeral=True)
            return

        update_announcement_record(target_msg.id, title, nowa_tresc)

        sent_count = 0
        blocked_count = 0
        if powiadom_pv:
            members = await get_clan_members(interaction.guild)
            dm_embed = new_embed.copy()
            dm_embed.title = f"🔄 ZAKTUALIZOWANO: {title}"
            dm_embed.add_field(
                name="🔗 Wiadomość na serwerze",
                value=f"[Kliknij tutaj, aby zobaczyć zaktualizowaną treść]({target_msg.jump_url})",
                inline=False,
            )
            for member in members:
                if member.bot:
                    continue
                try:
                    await member.send(embed=dm_embed)
                    sent_count += 1
                except (discord.Forbidden, discord.HTTPException):
                    blocked_count += 1
                await asyncio.sleep(0.35)

        report = discord.Embed(
            title="✏️ Ogłoszenie zostało zaktualizowane!",
            description=(
                f"Treść ogłoszenia na kanale {channel.mention} została pomyślnie zmieniona.\n\n"
                f"🔗 **[Przejdź do ogłoszenia]({target_msg.jump_url})**"
            ),
            color=config.COLOR_SUCCESS,
            timestamp=datetime.now(timezone.utc),
        )
        report.add_field(name="📢 Kanał", value=channel.mention, inline=True)
        report.add_field(name="🆔 ID wiadomości", value=f"`{target_msg.id}`", inline=True)
        if powiadom_pv:
            report.add_field(name="📨 Powiadomienia PV", value=f"Wysłano: **{sent_count}**, Zablokowane: **{blocked_count}**", inline=False)
        report.set_footer(text=config.FOOTER_TEXT_ZBIORKA)
        await interaction.followup.send(embed=report, ephemeral=True)

    # ── /ogloszenie zmien ────────────────────────────────────────────
    @ogloszenie_group.command(
        name="zmien",
        description="Edytuje treść lub tytuł istniejącego ogłoszenia na kanale #ogłoszenia.",
    )
    @app_commands.describe(
        nowa_tresc="Nowa treść ogłoszenia",
        nowy_tytul="Nowy tytuł ogłoszenia (opcjonalnie; jeśli puste, zachowuje dotychczasowy)",
        wiadomosc_id="ID lub link wiadomości z ogłoszeniem (jeśli puste, edytuje ostatnie ogłoszenie)",
        nowe_zdjecie_url="Nowy link do zdjęcia (wpisz 'brak' aby usunąć dotychczasowe zdjęcie)",
        powiadom_pv="Czy wysłać zaktualizowaną treść na PV do członków klanu? (Domyślnie: Nie)",
    )
    async def ogloszenie_zmien(
        self,
        interaction: discord.Interaction,
        nowa_tresc: str,
        nowy_tytul: str | None = None,
        wiadomosc_id: str | None = None,
        nowe_zdjecie_url: str | None = None,
        powiadom_pv: bool = False,
    ) -> None:
        await self._do_ogloszenie_zmien(interaction, nowa_tresc, nowy_tytul, wiadomosc_id, nowe_zdjecie_url, powiadom_pv)

    # ── Logika usuwania ogłoszenia (współdzielona z aliasem) ──────────
    async def _do_ogloszenie_usun(
        self,
        interaction: discord.Interaction,
        wiadomosc_id: str | None = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Ta komenda może być użyta tylko na serwerze.", ephemeral=True)
            return

        if not _is_staff_or_admin(interaction):
            await interaction.response.send_message(
                "❌ Ta komenda jest dostępna tylko dla Zarządu / Administratorów.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        channel = _get_announcements_channel(interaction.guild)
        if not channel:
            await interaction.followup.send(
                "❌ Nie znaleziono kanału ogłoszeń!\n"
                "Ustaw go za pomocą komendy `/ustaw kanal typ:📢 Kanał Ogłoszeń (#ogłoszenia) kanal:#twoj-kanal`.",
                ephemeral=True,
            )
            return

        target_msg, err = await _find_target_announcement(interaction.guild, channel, wiadomosc_id, self.bot.user)
        if err or not target_msg:
            await interaction.followup.send(err or "❌ Nie znaleziono ogłoszenia do usunięcia.", ephemeral=True)
            return

        msg_id = target_msg.id
        try:
            await target_msg.delete()
        except discord.NotFound:
            pass
        except Exception as e:
            await interaction.followup.send(f"❌ Błąd podczas usuwania wiadomości: {e}", ephemeral=True)
            return

        mark_announcement_deleted(msg_id)

        report = discord.Embed(
            title="🗑️ Ogłoszenie zostało usunięte!",
            description=f"Wiadomość ogłoszenia (ID: `{msg_id}`) została trwale usunięta z kanału {channel.mention}.",
            color=config.COLOR_CLOSE,
            timestamp=datetime.now(timezone.utc),
        )
        report.set_footer(text=config.FOOTER_TEXT_ZBIORKA)
        await interaction.followup.send(embed=report, ephemeral=True)

    # ── /ogloszenie usun ─────────────────────────────────────────────
    @ogloszenie_group.command(
        name="usun",
        description="Usuwa ogłoszenie z kanału #ogłoszenia.",
    )
    @app_commands.describe(
        wiadomosc_id="ID lub link wiadomości do usunięcia (jeśli puste, usuwa ostatnie ogłoszenie)",
    )
    async def ogloszenie_usun(
        self,
        interaction: discord.Interaction,
        wiadomosc_id: str | None = None,
    ) -> None:
        await self._do_ogloszenie_usun(interaction, wiadomosc_id)

    # ── Szybkie aliasy bezpośrednie (top-level) ──────────────────────
    @app_commands.command(
        name="ogloszenie_wyslij",
        description="Szybkie wysłanie nowego ogłoszenia lub ankiety na kanał #ogłoszenia (z opcją PV).",
    )
    @app_commands.describe(
        tytul="Tytuł ogłoszenia lub ankiety",
        tresc="Treść ogłoszenia lub pytanie",
        ankieta="Czy to ogłoszenie jest ankietą/pytaniem z przyciskami TAK / NIE? (Domyślnie: Nie)",
        wyslij_pv="Czy wysłać to ogłoszenie również w wiadomości prywatnej (PV) do członków klanu? (Domyślnie: Nie)",
        ping="Czy oznaczyć rolę klanu na kanale ogłoszeń?",
        zdjecie_url="Opcjonalny link do obrazka",
    )
    @app_commands.default_permissions(administrator=True)
    async def ogloszenie_wyslij_alias(
        self,
        interaction: discord.Interaction,
        tytul: str,
        tresc: str,
        ankieta: bool = False,
        wyslij_pv: bool = False,
        ping: bool = False,
        zdjecie_url: str | None = None,
    ) -> None:
        await self._do_ogloszenie_wyslij(interaction, tytul, tresc, ankieta, wyslij_pv, ping, zdjecie_url)

    @app_commands.command(
        name="ogloszenie_zmien",
        description="Szybka edycja istniejącego ogłoszenia na kanale #ogłoszenia.",
    )
    @app_commands.describe(
        nowa_tresc="Nowa treść ogłoszenia",
        nowy_tytul="Nowy tytuł ogłoszenia (opcjonalnie)",
        wiadomosc_id="ID lub link wiadomości z ogłoszeniem (opcjonalnie, domyślnie ostatnie)",
        nowe_zdjecie_url="Nowy link do zdjęcia (lub 'brak')",
        powiadom_pv="Czy wysłać zaktualizowaną treść na PV?",
    )
    @app_commands.default_permissions(administrator=True)
    async def ogloszenie_zmien_alias(
        self,
        interaction: discord.Interaction,
        nowa_tresc: str,
        nowy_tytul: str | None = None,
        wiadomosc_id: str | None = None,
        nowe_zdjecie_url: str | None = None,
        powiadom_pv: bool = False,
    ) -> None:
        await self._do_ogloszenie_zmien(interaction, nowa_tresc, nowy_tytul, wiadomosc_id, nowe_zdjecie_url, powiadom_pv)

    @app_commands.command(
        name="ogloszenie_usun",
        description="Szybkie usunięcie ogłoszenia z kanału #ogłoszenia.",
    )
    @app_commands.describe(
        wiadomosc_id="ID lub link wiadomości do usunięcia (opcjonalnie, domyślnie ostatnie)",
    )
    @app_commands.default_permissions(administrator=True)
    async def ogloszenie_usun_alias(
        self,
        interaction: discord.Interaction,
        wiadomosc_id: str | None = None,
    ) -> None:
        await self._do_ogloszenie_usun(interaction, wiadomosc_id)

    # ── Logika /komunikat (współdzielona z aliasem /pw_rola) ─────────
    async def _do_komunikat(
        self,
        interaction: discord.Interaction,
        rola: discord.Role,
        tytul: str,
        tresc: str,
        zdjecie_url: str | None = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Ta komenda może być użyta tylko na serwerze.", ephemeral=True)
            return

        if not _is_staff_or_admin(interaction):
            await interaction.response.send_message(
                "❌ Ta komenda jest dostępna tylko dla Zarządu / Administratorów.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        members = await get_role_members(guild, rola)

        if not members:
            await interaction.followup.send(
                f"⚠️ Rola {rola.mention} nie posiada żadnych członków (niebędących botami) lub bot nie ma do nich dostępu.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"📨 {tytul}",
            description=tresc,
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc),
        )
        if guild.icon:
            embed.set_author(name=f"{guild.name} • Komunikat", icon_url=guild.icon.url)
            embed.set_thumbnail(url=guild.icon.url)
        else:
            embed.set_author(name=f"{guild.name} • Komunikat")

        if zdjecie_url and zdjecie_url.strip().startswith(("http://", "https://")):
            embed.set_image(url=zdjecie_url.strip())

        embed.set_footer(text=f"{config.FOOTER_TEXT_ZBIORKA} • Od: {interaction.user.display_name}")

        sent_count = 0
        blocked_count = 0

        for member in members:
            try:
                await member.send(embed=embed)
                sent_count += 1
            except (discord.Forbidden, discord.HTTPException):
                blocked_count += 1
            await asyncio.sleep(0.35)

        report = discord.Embed(
            title="📨 Komunikat został wysłany!",
            description=f"Wysłano prywatną wiadomość do użytkowników posiadających rolę {rola.mention}.",
            color=config.COLOR_SUCCESS,
            timestamp=datetime.now(timezone.utc),
        )
        report.add_field(name="👥 Rola docelowa", value=rola.mention, inline=True)
        report.add_field(name="✅ Wysłano pomyślnie", value=f"**{sent_count}**", inline=True)
        report.add_field(name="🚫 Zablokowane DM", value=f"**{blocked_count}**", inline=True)
        report.add_field(name="👥 Łącznie członków roli", value=f"**{len(members)}**", inline=False)
        report.set_footer(text=config.FOOTER_TEXT_ZBIORKA)

        await interaction.followup.send(embed=report, ephemeral=True)

    # ── /komunikat (oraz alias /pw_rola) ─────────────────────────────
    @app_commands.command(
        name="komunikat",
        description="Wysyła prywatną wiadomość (PV) do każdego użytkownika z wybraną rolą.",
    )
    @app_commands.describe(
        rola="Wskaż rolę, której członkom chcesz wysłać wiadomość na PV",
        tytul="Tytuł komunikatu",
        tresc="Treść wiadomości do przekazania",
        zdjecie_url="Opcjonalny link do obrazka/grafiki do wiadomości",
    )
    @app_commands.default_permissions(administrator=True)
    async def komunikat(
        self,
        interaction: discord.Interaction,
        rola: discord.Role,
        tytul: str,
        tresc: str,
        zdjecie_url: str | None = None,
    ) -> None:
        await self._do_komunikat(interaction, rola, tytul, tresc, zdjecie_url)

    @komunikat.error
    async def komunikat_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.errors.MissingPermissions):
            msg = "❌ Ta komenda jest dostępna tylko dla Zarządu / Administratorów."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(
        name="pw_rola",
        description="Szybkie wysłanie wiadomości na PV do każdego z wybraną rolą (alias dla /komunikat).",
    )
    @app_commands.describe(
        rola="Wskaż rolę docelową",
        tytul="Tytuł komunikatu",
        tresc="Treść wiadomości",
        zdjecie_url="Opcjonalny link do obrazka",
    )
    @app_commands.default_permissions(administrator=True)
    async def pw_rola_alias(
        self,
        interaction: discord.Interaction,
        rola: discord.Role,
        tytul: str,
        tresc: str,
        zdjecie_url: str | None = None,
    ) -> None:
        await self._do_komunikat(interaction, rola, tytul, tresc, zdjecie_url)



async def setup(bot: commands.Bot) -> None:
    bot.add_view(PollVoteView())
    await bot.add_cog(Treasury(bot))

