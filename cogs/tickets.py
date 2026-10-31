from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import config

logger = logging.getLogger(__name__)

CATEGORIES = {
    "recruit": {
        "label": "Rekrutacja",
        "description": "Chcesz dołączyć do gildii PVP0?",
        "emoji": "⚔️",
        "title": "Rekrutacja",
        "color": config.COLOR_RECRUIT,
    },
    "alliance": {
        "label": "Sojusz",
        "description": "Chcesz zawrzeć sojusz klanowy z PVP0?",
        "emoji": "🤝",
        "title": "Sojusz",
        "color": config.COLOR_ALLIANCE,
    },
    "rank": {
        "label": "Nadanie Rangi",
        "description": "Wnioskuj o rangę Sojusz lub Członek",
        "emoji": "🎖️",
        "title": "Nadanie Rangi",
        "color": config.COLOR_RANK,
    },
}


# ── Pomocnicy do ról ──────────────────────────────────────────────

def _get_clan_role(guild: discord.Guild) -> discord.Role | None:
    if config.CLAN_ROLE_ID:
        role = guild.get_role(config.CLAN_ROLE_ID)
        if role:
            return role
    for r in guild.roles:
        if r.name.lower() in ("czlonek", "członek"):
            return r
    return None


def _get_alliance_role(guild: discord.Guild) -> discord.Role | None:
    if config.ALLIANCE_ROLE_ID:
        role = guild.get_role(config.ALLIANCE_ROLE_ID)
        if role:
            return role
    for r in guild.roles:
        if r.name.lower() in ("sojusz", "sojusznik", "sojusze"):
            return r
    return None


async def _get_or_create_alliance_leader_role(guild: discord.Guild) -> discord.Role | None:
    if getattr(config, "ALLIANCE_LEADER_ROLE_ID", None):
        role = guild.get_role(config.ALLIANCE_LEADER_ROLE_ID)
        if role:
            return role

    for r in guild.roles:
        if r.name.lower() in ("lider sojuszu", "lider-sojuszu", "lider sojusz"):
            return r

    # Jeśli rola nie istnieje, utwórz ją automatycznie
    try:
        role = await guild.create_role(
            name="Lider Sojuszu",
            color=discord.Color.from_rgb(245, 158, 11),
            reason="Automatyczne utworzenie roli Lider Sojuszu dla zaakceptowanego sojuszu",
        )
        return role
    except discord.Forbidden:
        return _get_alliance_role(guild)


def _can_manage_tickets(admin: discord.Member, guild: discord.Guild) -> bool:
    """Sprawdza, czy użytkownik ma uprawnienia do akceptacji/odrzucania podań (2 określone rangi)."""
    allowed_ids = {
        rid for rid in (
            getattr(config, "APPROVAL_ROLE_1_ID", None),
            getattr(config, "APPROVAL_ROLE_2_ID", None),
            config.STAFF_ROLE_ID,
        ) if rid
    }

    # 1. Sprawdź po ID skonfigurowanych ról
    for role in admin.roles:
        if role.id in allowed_ids:
            return True

    # 2. Sprawdź po nazwach ról zarządu / administracji
    for role in admin.roles:
        if role.name.lower() in ("admin", "administrator", "zarząd", "zarzad", "rekruter", "lider"):
            return True

    # 3. Uprawnienia administratora na serwerze
    if admin.guild_permissions.administrator:
        return True

    return False


ACTIVE_TICKET_USERS: set[int] = set()


async def has_open_ticket(guild: discord.Guild, user_id: int) -> bool:
    """Sprawdza, czy gracz ma już aktywny ticket (w trakcie wypełniania lub oczekujący na decyzję)."""
    if user_id in ACTIVE_TICKET_USERS:
        return True

    # Sprawdź kanał logów pod kątem nierozpatrzonych zgłoszeń z aktywnymi przyciskami
    if config.LOG_CHANNEL_ID:
        log_channel = guild.get_channel(config.LOG_CHANNEL_ID)
        if isinstance(log_channel, discord.TextChannel):
            try:
                async for msg in log_channel.history(limit=50):
                    if msg.author.id == guild.me.id and msg.components:
                        for row in msg.components:
                            for comp in getattr(row, "children", []):
                                cid = getattr(comp, "custom_id", "")
                                if cid.startswith(f"pvp0:approve:{user_id}:") or cid.startswith(f"pvp0:reject:{user_id}:"):
                                    return True
            except Exception:
                pass

    return False


# ══════════════════════════════════════════════════════════════════
#  KROK 1 — Panel ticketów z przyciskiem po prawej i gifem
# ══════════════════════════════════════════════════════════════════

class CreateTicketButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="Utwórz ticket",
            style=discord.ButtonStyle.primary,
            custom_id="pvp0:create_ticket",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return

        guild = interaction.guild
        member = interaction.user

        # Sprawdzenie limitu jednego otwartego ticketa
        if await has_open_ticket(guild, member.id):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Masz już otwarty ticket",
                    description=(
                        "🔒 **Możesz posiadać maksymalnie jednego otwartego ticketa.**\n\n"
                        "Masz już aktywne zgłoszenie w toku lub oczekujące na decyzję administracji."
                    ),
                    color=config.COLOR_TICKET,
                ),
                ephemeral=True,
            )
            return

        # Sprawdź czy bot może wysłać DM
        dm_channel = member.dm_channel
        if dm_channel is None:
            try:
                dm_channel = await member.create_dm()
            except discord.Forbidden:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="❌ Nie mogę wysłać wiadomości prywatnej",
                        description=(
                            "Masz wyłączone wiadomości prywatne od członków tego serwera.\n\n"
                            "**Jak to naprawić:**\n"
                            "1. Kliknij PPM na serwer → **Ustawienia prywatności**.\n"
                            "2. Włącz **Wiadomości bezpośrednie od członków serwera**.\n"
                            "3. Spróbuj ponownie."
                        ),
                        color=config.COLOR_CLOSE,
                    ),
                    ephemeral=True,
                )
                return

        ACTIVE_TICKET_USERS.add(member.id)

        await interaction.response.send_message(
            embed=discord.Embed(
                title="📩 Sprawdź wiadomości prywatne",
                description="Wysłałem Ci wiadomość prywatną. Podaj w niej swój nick w grze.",
                color=config.COLOR_SUCCESS,
            ),
            ephemeral=True,
        )

        interaction.client.loop.create_task(
            start_ticket_flow(
                bot=interaction.client,  # type: ignore[arg-type]
                member=member,
                guild_id=guild.id,
            )
        )


class TicketPanelView(discord.ui.LayoutView):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        button = CreateTicketButton()
        header_section = discord.ui.Section(
            discord.ui.TextDisplay("### **⚔️ Rekrutacja & Sojusz | Gildia PVP0**"),
            accessory=button,
        )
        gallery = discord.ui.MediaGallery(discord.MediaGalleryItem("attachment://pvp0.gif"))
        container = discord.ui.Container(
            header_section,
            discord.ui.TextDisplay(
                "Chcesz dołączyć do PVP0, zawrzeć sojusz klanowy lub otrzymać rangę?\n"
                "Utwórz ticket i wybierz odpowiednią kategorię.\n\n"
                "Po kliknięciu przycisku podaj swój nick, a następnie wybierz kategorię:\n"
                "⚔️ **Rekrutacja** | 🤝 **Sojusz** | 🎖️ **Nadanie Rangi**\n\n"
                "🔒 **Możesz posiadać maksymalnie jednego otwartego ticketa.**\n"
                ">> **Ważne:** Upewnij się, że masz włączone wiadomości prywatne od innych."
            ),
            gallery,
            discord.ui.TextDisplay(f"-# {config.FOOTER_TEXT}"),
            accent_colour=config.COLOR_TICKET,
        )
        self.add_item(container)


# ══════════════════════════════════════════════════════════════════
#  Pomocnik do pobierania odpowiedzi tekstowej w DM
# ══════════════════════════════════════════════════════════════════

async def ask_dm_question(
    bot: commands.Bot,
    dm_channel: discord.DMChannel,
    user_id: int,
    *,
    title: str,
    description: str,
    color: int,
    content: str | None = None,
    min_len: int = 1,
    max_len: int = 500,
    timeout: int = 180,
) -> str | None:
    embed = discord.Embed(
        title=title,
        description=f"{description}\n\nAby anulować, napisz `anuluj`.",
        color=color,
    )
    await dm_channel.send(content=content, embed=embed)

    def check(m: discord.Message) -> bool:
        return (
            m.author.id == user_id
            and isinstance(m.channel, discord.DMChannel)
            and m.channel.id == dm_channel.id
        )

    try:
        msg = await bot.wait_for("message", check=check, timeout=timeout)
    except asyncio.TimeoutError:
        await dm_channel.send(
            embed=discord.Embed(
                title="⏰ Czas minął",
                description="Brak odpowiedzi. Tworzenie zgłoszenia zostało anulowane.",
                color=config.COLOR_CLOSE,
            )
        )
        return None

    text = msg.content.strip()
    if text.lower() == "anuluj":
        await dm_channel.send(
            embed=discord.Embed(
                title="❌ Anulowano",
                description="Tworzenie zgłoszenia zostało anulowane.",
                color=config.COLOR_CLOSE,
            )
        )
        return None

    if len(text) < min_len or len(text) > max_len:
        await dm_channel.send(
            embed=discord.Embed(
                title="❌ Nieprawidłowa długość",
                description=f"Wiadomość musi mieć od {min_len} do {max_len} znaków. Rozpocznij procedurę od nowa na serwerze.",
                color=config.COLOR_CLOSE,
            )
        )
        return None

    return text


# ══════════════════════════════════════════════════════════════════
#  KROK 2 — Zapytanie o nick w grze (DM)
# ══════════════════════════════════════════════════════════════════

async def start_ticket_flow(
    bot: commands.Bot,
    member: discord.Member,
    guild_id: int,
) -> None:
    handed_off = False
    try:
        dm_channel = member.dm_channel or await member.create_dm()

        nick_embed = discord.Embed(
            title="🎫 Tworzenie ticketu",
            description=(
                "Podaj swój nick w grze.\n\n"
                "Dozwolone są 3-16 znaków: litery, cyfry i `_`.\n"
                "Aby anulować, napisz `anuluj`."
            ),
            color=config.COLOR_CLOSE,
        )

        try:
            await dm_channel.send(embed=nick_embed)
        except discord.Forbidden:
            return

        def check(m: discord.Message) -> bool:
            return (
                m.author.id == member.id
                and isinstance(m.channel, discord.DMChannel)
                and m.channel.id == dm_channel.id
            )

        try:
            msg = await bot.wait_for("message", check=check, timeout=120)
        except asyncio.TimeoutError:
            await dm_channel.send(
                embed=discord.Embed(
                    title="⏰ Czas minął",
                    description="Nie podałeś nicku w ciągu 2 minut. Spróbuj ponownie klikając przycisk na kanale.",
                    color=config.COLOR_CLOSE,
                )
            )
            return

        if msg.content.strip().lower() == "anuluj":
            await dm_channel.send(
                embed=discord.Embed(
                    title="❌ Anulowano",
                    description="Tworzenie ticketa zostało anulowane.",
                    color=config.COLOR_CLOSE,
                )
            )
            return

        nick = msg.content.strip()

        if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", nick):
            await dm_channel.send(
                embed=discord.Embed(
                    title="❌ Nieprawidłowy nick",
                    description=(
                        "Nick musi mieć 3–16 znaków i może zawierać tylko litery, cyfry i `_`.\n"
                        "Spróbuj ponownie klikając przycisk **Utwórz ticket** na serwerze."
                    ),
                    color=config.COLOR_CLOSE,
                )
            )
            return

        # KROK 3 — Wybór kategorii w DM
        category_embed = discord.Embed(
            title="⚔️ Utwórz ticket | Gildia PVP0",
            description=(
                "Wybierz kategorię za pomocą przycisków poniżej, aby utworzyć ticket.\n\n"
                "⚔️ **Rekrutacja** — chcesz dołączyć do gildii PVP0\n"
                "🤝 **Sojusz** — chcesz zawrzeć sojusz klanowy\n"
                "🎖️ **Nadanie Rangi** — wniosek o rangę Sojusz lub Członek\n\n"
                "🔒 **Możesz posiadać maksymalnie jednego otwartego ticketa.**\n"
                "│ Masz **2 minuty** na dokonanie wyboru."
            ),
            color=config.COLOR_TICKET,
        )
        category_embed.set_footer(text=config.FOOTER_TEXT)

        cat_view = DMCategoryChoiceView(guild_id=guild_id, nick=nick, user_id=member.id)
        cat_msg = await dm_channel.send(embed=category_embed, view=cat_view)
        cat_view.message = cat_msg
        handed_off = True
    finally:
        if not handed_off:
            ACTIVE_TICKET_USERS.discard(member.id)


# ══════════════════════════════════════════════════════════════════
#  KROK 3 — Wybór kategorii i formularz szczegółowy w DM
# ══════════════════════════════════════════════════════════════════

class DMCategoryChoiceView(discord.ui.View):
    def __init__(self, guild_id: int, nick: str, user_id: int) -> None:
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.nick = nick
        self.user_id = user_id

    async def _handle_choice(self, interaction: discord.Interaction, category_key: str) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("To nie Twoje menu wyboru.", ephemeral=True)
            return

        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        await interaction.response.edit_message(view=self)

        interaction.client.loop.create_task(
            collect_category_details(
                bot=interaction.client,  # type: ignore[arg-type]
                dm_channel=interaction.channel,  # type: ignore[arg-type]
                user=interaction.user,
                guild_id=self.guild_id,
                category_key=category_key,
                nick=self.nick,
            )
        )

    @discord.ui.button(label="Rekrutacja", emoji="⚔️", style=discord.ButtonStyle.primary)
    async def recruit_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._handle_choice(interaction, "recruit")

    @discord.ui.button(label="Sojusz", emoji="🤝", style=discord.ButtonStyle.secondary)
    async def alliance_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._handle_choice(interaction, "alliance")

    @discord.ui.button(label="Nadanie Rangi", emoji="🎖️", style=discord.ButtonStyle.secondary)
    async def rank_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._handle_choice(interaction, "rank")

    async def on_timeout(self) -> None:
        ACTIVE_TICKET_USERS.discard(self.user_id)
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


# ══════════════════════════════════════════════════════════════════
#  Widok wyboru rangi (Sojusz lub Członek) dla kategorii "rank"
# ══════════════════════════════════════════════════════════════════

class RankChoiceView(discord.ui.View):
    def __init__(self, user_id: int) -> None:
        super().__init__(timeout=120)
        self.user_id = user_id
        self._future: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()

    @discord.ui.button(label="Ranga Sojusz", emoji="🤝", style=discord.ButtonStyle.secondary)
    async def choose_alliance(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            return
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        await interaction.response.edit_message(view=self)
        if not self._future.done():
            self._future.set_result("Sojusz")

    @discord.ui.button(label="Ranga Członek", emoji="⚔️", style=discord.ButtonStyle.primary)
    async def choose_member(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            return
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        await interaction.response.edit_message(view=self)
        if not self._future.done():
            self._future.set_result("Członek")

    async def on_timeout(self) -> None:
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
        if not self._future.done():
            self._future.set_result(None)


# ══════════════════════════════════════════════════════════════════
#  KROK 4 — Zbieranie pytań szczegółowych (Rekrutacja / Sojusz / Rangi)
# ══════════════════════════════════════════════════════════════════

async def collect_category_details(
    bot: commands.Bot,
    dm_channel: discord.DMChannel,
    user: discord.User,
    guild_id: int,
    category_key: str,
    nick: str,
) -> None:
    success = False
    try:
        meta = CATEGORIES[category_key]
        fields: dict[str, str] = {}

        if category_key == "recruit":
            # 1. Wiek (z ponowną próbą w przypadku błędnej liczby)
            first_ask = True
            while True:
                if first_ask:
                    title = "⚔️ Rekrutacja · Wiek"
                    description = "Podaj swój wiek (liczba od 10 do 99):"
                    color = config.COLOR_RECRUIT
                else:
                    title = "❌ Nieprawidłowy wiek"
                    description = "Wiek musi być liczbą od 10 do 99. Wpisz wiek jeszcze raz:"
                    color = config.COLOR_CLOSE

                age_ans = await ask_dm_question(
                    bot,
                    dm_channel,
                    user.id,
                    title=title,
                    description=description,
                    color=color,
                    min_len=1,
                    max_len=30,
                )
                if not age_ans:
                    return

                if age_ans.isdigit() and (10 <= int(age_ans) <= 99):
                    fields["Wiek"] = age_ans
                    break

                first_ask = False

            # 2. Formularz rekrutacyjny
            raw_form = (
                "1.Ocen swoje pvp 1-10 -\n"
                "2.Twoja ostatnia gildia i dlaczego w niej nie jesteś? -\n"
                "3.Dlaczego akurat my? -\n"
                "4.Ile czasu poświęciłbyś dziennie na gildię? -\n"
                "5.Posiadasz premkę? -\n"
                "6.Potrafisz percritowac? -\n"
                "7.Masz jakies doświadczenie w gildiach? jak tak to ile lat/miesiecy -\n"
                "8.Jaki jest twój ulubiony przedmiot w szkole? -"
            )
            form_box = f"```text\n{raw_form}\n```"
            exp_ans = await ask_dm_question(
                bot,
                dm_channel,
                user.id,
                title="⚔️ Rekrutacja · Formularz",
                description=(
                    "Skopiuj i wypełnij poniższy formularz (wpisz swoje odpowiedzi po myślniku `-`):\n\n"
                    f"{form_box}"
                ),
                content=form_box,
                color=config.COLOR_RECRUIT,
                min_len=5,
                max_len=1500,
            )
            if not exp_ans:
                return
            fields["Formularz rekrutacyjny"] = exp_ans

        elif category_key == "alliance":
            # 1. Nazwa gildii
            guild_name = await ask_dm_question(
                bot,
                dm_channel,
                user.id,
                title="🤝 Sojusz · Nazwa gildii",
                description="Podaj nazwę gildii lub klanu, którą reprezentujesz:",
                color=config.COLOR_ALLIANCE,
                min_len=2,
                max_len=60,
            )
            if not guild_name:
                return
            fields["Nazwa gildii"] = guild_name

            # 2. Rola w gildii
            role_ans = await ask_dm_question(
                bot,
                dm_channel,
                user.id,
                title="🤝 Sojusz · Twoja rola",
                description="Jaka jest Twoja rola w gildii? (np. Lider, Zastępca):",
                color=config.COLOR_ALLIANCE,
                min_len=2,
                max_len=60,
            )
            if not role_ans:
                return
            fields["Rola w gildii"] = role_ans

            # 3. Propozycja sojuszu
            proposal_ans = await ask_dm_question(
                bot,
                dm_channel,
                user.id,
                title="🤝 Sojusz · Propozycja",
                description="Napisz krótko, dlaczego chcecie zawrzeć sojusz z PVP0 i jakie warunki proponujecie:",
                color=config.COLOR_ALLIANCE,
                min_len=5,
                max_len=500,
            )
            if not proposal_ans:
                return
            fields["Propozycja"] = proposal_ans

        elif category_key == "rank":
            # 1. Wybór rangi: Sojusz lub Członek
            rank_view = RankChoiceView(user.id)
            rank_msg = await dm_channel.send(
                embed=discord.Embed(
                    title="🎖️ Nadanie Rangi · Wybierz rangę",
                    description="Wybierz rangę, o którą wnioskujesz:\n\n🤝 **Ranga Sojusz**\n⚔️ **Ranga Członek**",
                    color=config.COLOR_RANK,
                ),
                view=rank_view,
            )
            rank_view.message = rank_msg

            try:
                chosen_rank = await asyncio.wait_for(rank_view._future, timeout=120)
            except asyncio.TimeoutError:
                await dm_channel.send(
                    embed=discord.Embed(
                        title="⏰ Czas minął",
                        description="Nie wybrano rangi w ciągu 2 minut. Zgłoszenie zostało anulowane.",
                        color=config.COLOR_CLOSE,
                    )
                )
                return

            if not chosen_rank:
                return

            fields["Wnioskowana ranga"] = f"Ranga {chosen_rank}"

            # 2. Pytanie o szczegóły / powód
            if chosen_rank == "Sojusz":
                info_ans = await ask_dm_question(
                    bot,
                    dm_channel,
                    user.id,
                    title="🤝 Ranga Sojusz · Szczegóły",
                    description="Podaj nazwę gildii sojuszniczej, z której jesteś:",
                    color=config.COLOR_ALLIANCE,
                    min_len=2,
                    max_len=100,
                )
                if not info_ans:
                    return
                fields["Gildia"] = info_ans
            else:
                info_ans = await ask_dm_question(
                    bot,
                    dm_channel,
                    user.id,
                    title="⚔️ Ranga Członek · Szczegóły",
                    description="Podaj powód / uzasadnienie nadania rangi Członek:",
                    color=config.COLOR_RECRUIT,
                    min_len=2,
                    max_len=300,
                )
                if not info_ans:
                    return
                fields["Uzasadnienie"] = info_ans

        # Wysyłka do kanału administracji (#logi-ticket)
        guild = bot.get_guild(guild_id)
        if guild is None:
            await dm_channel.send("Nie znaleziono serwera.")
            return

        if not config.LOG_CHANNEL_ID:
            await dm_channel.send("Kanał logów nie jest skonfigurowany. Skontaktuj się z administracją.")
            return

        log_channel = guild.get_channel(config.LOG_CHANNEL_ID)
        if not isinstance(log_channel, discord.TextChannel):
            await dm_channel.send("Kanał logów nie został znaleziony. Skontaktuj się z administracją.")
            return

        # Embed zgłoszenia dla administracji na kanale #logi-ticket
        approval_embed = discord.Embed(
            title=f"📋 Nowe zgłoszenie — {meta['label']}",
            color=meta["color"],
            timestamp=datetime.now(timezone.utc),
        )
        approval_embed.add_field(name="Discord", value=f"{user.mention}\n`{user}`", inline=True)
        approval_embed.add_field(name="Nick MC", value=f"`{nick}`", inline=True)
        approval_embed.add_field(name="Kategoria", value=f"{meta['emoji']} {meta['label']}", inline=True)

        for name, value in fields.items():
            safe_val = value if len(value) <= 1024 else value[:1020] + "..."
            approval_embed.add_field(name=name, value=safe_val, inline=False)

        approval_embed.set_thumbnail(url=user.display_avatar.url)
        approval_embed.set_footer(text=config.FOOTER_TEXT)

        # Przyciski Akceptuj / Odrzuć
        approve_id = f"pvp0:approve:{user.id}:{category_key}"
        reject_id = f"pvp0:reject:{user.id}:{category_key}"

        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(
            label="Akceptuj",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=approve_id,
        ))
        view.add_item(discord.ui.Button(
            label="Odrzuć",
            emoji="❌",
            style=discord.ButtonStyle.danger,
            custom_id=reject_id,
        ))

        await log_channel.send(embed=approval_embed, view=view)

        # Potwierdzenie wysłania dla gracza w DM
        confirm_embed = discord.Embed(
            title="📩 Zgłoszenie wysłane",
            description=(
                f"Twoje zgłoszenie **{meta['label']}** zostało pomyślnie przesłane do administracji.\n\n"
                f"Nick: **{nick}**\n"
                f"Kategoria: **{meta['label']}**\n\n"
                "Poczekaj na decyzję — dostaniesz powiadomienie tutaj na PV."
            ),
            color=config.COLOR_SUCCESS,
        )
        confirm_embed.set_footer(text=config.FOOTER_TEXT)
        await dm_channel.send(embed=confirm_embed)
        success = True
    finally:
        ACTIVE_TICKET_USERS.discard(user.id)


# ══════════════════════════════════════════════════════════════════
#  OBSŁUGA PRZYCISKÓW AKCEPTUJ / ODRZUĆ (persistent via listener)
# ══════════════════════════════════════════════════════════════════

PROCESSED_APPROVAL_MESSAGES: set[int] = set()

async def _handle_approval(interaction: discord.Interaction, approved: bool) -> None:
    """Obsługuje kliknięcie Akceptuj lub Odrzuć w #logi-ticket."""

    custom_id = interaction.data.get("custom_id", "")  # type: ignore[union-attr]
    # Format: pvp0:approve:{user_id}:{category_key}
    parts = custom_id.split(":")
    if len(parts) < 4:
        return

    user_id = int(parts[2])
    category_key = parts[3]
    msg_id = interaction.message.id if interaction.message else 0

    # Zabezpieczenie przed podwójnym kliknięciem i podwójnym wysłaniem DM
    if msg_id and msg_id in PROCESSED_APPROVAL_MESSAGES:
        return

    if interaction.message and interaction.message.embeds:
        current_title = interaction.message.embeds[0].title or ""
        if current_title.startswith("✅") or current_title.startswith("❌"):
            if msg_id:
                PROCESSED_APPROVAL_MESSAGES.add(msg_id)
            return

    if msg_id:
        PROCESSED_APPROVAL_MESSAGES.add(msg_id)

    try:
        meta = CATEGORIES.get(category_key, {})
        guild = interaction.guild
        if guild is None:
            return

        admin = interaction.user

        # Weryfikacja uprawnień administracji / wyznaczonych ról
        if not _can_manage_tickets(admin, guild):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Tylko wyznaczone rangi mogą decydować o zgłoszeniach.",
                    ephemeral=True,
                )
            return

        # Szybkie potwierdzenie interakcji (defer), aby zapobiec wygaśnięciu (10062 Unknown interaction)
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
        except discord.HTTPException:
            pass

        # Wyciągnij Nick MC, Wnioskowaną rangę oraz Gildię z embeda
        nick = "Gracz"
        requested_rank: str | None = None
        guild_name: str | None = None
        if interaction.message and interaction.message.embeds:
            for f in interaction.message.embeds[0].fields:
                if f.name == "Nick MC":
                    nick = f.value.replace("`", "").strip()
                elif f.name == "Wnioskowana ranga":
                    requested_rank = f.value.lower()
                elif f.name in ("Gildia", "Nazwa gildii"):
                    guild_name = f.value.replace("`", "").strip()

        # Pobierz gracza
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except (discord.NotFound, discord.HTTPException):
                member = None

        if approved:
            # ── AKCEPTACJA ────────────────────────────────────────
            role_given = False
            target_role: discord.Role | None = None

            if category_key == "recruit" or (category_key == "rank" and requested_rank and "członek" in requested_rank):
                target_role = _get_clan_role(guild)
            elif category_key == "alliance":
                target_role = await _get_or_create_alliance_leader_role(guild)
            elif category_key == "rank" and requested_rank and "sojusz" in requested_rank:
                target_role = _get_alliance_role(guild)

            if target_role and member:
                try:
                    await member.add_roles(target_role, reason=f"Zgłoszenie zaakceptowane przez {admin}")
                    role_given = True
                    if target_role == _get_clan_role(guild):
                        try:
                            from cogs.treasury import add_known_clan_id
                            add_known_clan_id(user_id)
                        except Exception:
                            pass
                except discord.Forbidden:
                    pass

            # Automatyczna zmiana pseudonimu gracza
            nick_changed = False
            nick_issue: str | None = None
            new_nickname: str | None = None

            if category_key == "recruit":
                new_nickname = f"[PVP0] {nick}"
            elif category_key == "rank":
                if requested_rank and "sojusz" in requested_rank:
                    tag = guild_name or "SOJUSZ"
                    tag_clean = tag.strip("[] ").strip()
                    new_nickname = f"[{tag_clean}] {nick}"
                elif requested_rank and "członek" in requested_rank:
                    new_nickname = f"[PVP0] {nick}"
                elif guild_name:
                    tag_clean = guild_name.strip("[] ").strip()
                    new_nickname = f"[{tag_clean}] {nick}"
            elif category_key == "alliance":
                tag = guild_name or "SOJUSZ"
                tag_clean = tag.strip("[] ").strip()
                new_nickname = f"[{tag_clean}] {nick}"

            if new_nickname and member:
                if len(new_nickname) > 32:
                    new_nickname = new_nickname[:32]
                if member.id == guild.owner_id:
                    nick_issue = "Discord blokuje botom zmianę pseudonimu Właściciela serwera"
                    logger.warning("Nie można zmienić nicku Właściciela serwera %s", member.id)
                elif not guild.me.guild_permissions.manage_nicknames and not guild.me.guild_permissions.administrator:
                    nick_issue = "Bot nie posiada uprawnienia 'Zarządzanie pseudonimami' na serwerze"
                    logger.warning("Brak uprawnienia manage_nicknames dla bota w gildii %s", guild.id)
                elif guild.me.top_role <= member.top_role:
                    nick_issue = f"Rola bota ({guild.me.top_role.name}) jest za niska w hierarchii ról względem gracza ({member.top_role.name})"
                    logger.warning("Rola bota (%s) jest za niska względem roli gracza (%s)", guild.me.top_role, member.top_role)
                else:
                    try:
                        await member.edit(nick=new_nickname, reason=f"Akceptacja zgłoszenia przez {admin}")
                        nick_changed = True
                    except (discord.Forbidden, discord.HTTPException) as e:
                        logger.warning("Błąd podczas edycji nicku gracza %s: %s", member.id, e)
                        nick_issue = f"Błąd uprawnień Discord: {e}"

            # Zaktualizuj embed w kanale logów
            original_embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else None
            status_embed = discord.Embed(
                title=f"✅ Zaakceptowano — {meta.get('label', category_key)}",
                color=config.COLOR_SUCCESS,
                timestamp=datetime.now(timezone.utc),
            )
            if original_embed:
                for field in original_embed.fields:
                    status_embed.add_field(name=field.name, value=field.value, inline=field.inline)
            status_embed.add_field(name="Decyzja", value=f"✅ Zaakceptowano przez {admin.mention}", inline=False)
            if role_given and target_role:
                status_embed.add_field(name="Rola", value=f"Nadano {target_role.mention}", inline=False)
            if nick_changed and new_nickname:
                status_embed.add_field(name="Nowy pseudonim", value=f"`{new_nickname}`", inline=False)
            elif nick_issue and new_nickname:
                status_embed.add_field(name="Pseudonim (niezmieniony)", value=f"`{new_nickname}`\n*(⚠️ {nick_issue})*", inline=False)
            status_embed.set_footer(text=config.FOOTER_TEXT)

            # Dezaktywuj przyciski (usuwając view)
            if interaction.message:
                try:
                    await interaction.message.edit(embed=status_embed, view=None)
                except discord.HTTPException:
                    pass

            # Wyślij DM do gracza
            user = interaction.client.get_user(user_id)
            if user is None:
                try:
                    user = await interaction.client.fetch_user(user_id)
                except (discord.NotFound, discord.HTTPException):
                    user = None

            if user:
                if category_key == "recruit":
                    dm_desc = (
                        f"Twoje podanie rekrutacyjne do gildii **PVP0** zostało zaakceptowane!\n\n"
                        f"Nick: **{nick}**\n\n"
                    )
                    if role_given and target_role:
                        dm_desc += f"Nadano Ci rolę **{target_role.name}** na serwerze. Witamy w gildii! 🎉"
                    else:
                        dm_desc += "Witamy w gildii PVP0! 🎉"
                elif category_key == "alliance":
                    role_text = f"Nadano Ci rolę **{target_role.name}** na serwerze! " if role_given and target_role else ""
                    dm_desc = (
                        f"Twoja propozycja **Sojuszu** z gildią PVP0 została zaakceptowana przez administrację!\n\n"
                        f"Nick: **{nick}**\n\n"
                        f"{role_text}"
                        "Skontaktuj się z liderami PVP0 w celu ustalenia szczegółów sojuszu. 🤝"
                    )
                elif category_key == "rank":
                    rank_name = "Sojusz" if (requested_rank and "sojusz" in requested_rank) else "Członek"
                    dm_desc = (
                        f"Twoja prośba o nadanie rangi **{rank_name}** została zaakceptowana!\n\n"
                        f"Nick: **{nick}**\n\n"
                    )
                    if role_given and target_role:
                        dm_desc += f"Nadano Ci rolę **{target_role.name}** na serwerze. 🎉"
                    else:
                        dm_desc += "Rola została pomyślnie zaakceptowana przez administrację. 🎉"
                else:
                    dm_desc = f"Twoje zgłoszenie zostało zaakceptowane!\n\nNick: **{nick}**"

                if nick_changed and new_nickname:
                    dm_desc += f"\n\n🏷️ Twój pseudonim na serwerze został zaktualizowany na: **{new_nickname}**"

                dm_embed = discord.Embed(
                    title="✅ Zgłoszenie zaakceptowane!",
                    description=dm_desc,
                    color=config.COLOR_SUCCESS,
                )
                dm_embed.set_footer(text=config.FOOTER_TEXT)
                try:
                    await user.send(embed=dm_embed)
                except discord.Forbidden:
                    pass

        else:
            # ── ODRZUCENIE ────────────────────────────────────────
            original_embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else None
            status_embed = discord.Embed(
                title=f"❌ Odrzucono — {meta.get('label', category_key)}",
                color=config.COLOR_CLOSE,
                timestamp=datetime.now(timezone.utc),
            )
            if original_embed:
                for field in original_embed.fields:
                    status_embed.add_field(name=field.name, value=field.value, inline=field.inline)
            status_embed.add_field(name="Decyzja", value=f"❌ Odrzucono przez {admin.mention}", inline=False)
            status_embed.set_footer(text=config.FOOTER_TEXT)

            if interaction.message:
                try:
                    await interaction.message.edit(embed=status_embed, view=None)
                except discord.HTTPException:
                    pass

            # Wyślij DM do gracza
            user = interaction.client.get_user(user_id)
            if user is None:
                try:
                    user = await interaction.client.fetch_user(user_id)
                except (discord.NotFound, discord.HTTPException):
                    user = None

            if user:
                dm_embed = discord.Embed(
                    title="❌ Zgłoszenie odrzucone",
                    description=(
                        f"Twoje zgłoszenie **{meta.get('label', category_key)}** zostało odrzucone.\n\n"
                        f"Nick: **{nick}**\n\n"
                        "Jeśli masz pytania, skontaktuj się z administracją."
                    ),
                    color=config.COLOR_CLOSE,
                )
                dm_embed.set_footer(text=config.FOOTER_TEXT)
                try:
                    await user.send(embed=dm_embed)
                except discord.Forbidden:
                    pass

    finally:
        ACTIVE_TICKET_USERS.discard(user_id)


# ══════════════════════════════════════════════════════════════════
#  Cog + setup
# ══════════════════════════════════════════════════════════════════

class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener("on_interaction")
    async def handle_approval_buttons(self, interaction: discord.Interaction) -> None:
        """Przechwytuje kliknięcia przycisków Akceptuj/Odrzuć (persistent)."""
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = interaction.data.get("custom_id", "")  # type: ignore[union-attr]
        if custom_id.startswith("pvp0:approve:"):
            await _handle_approval(interaction, approved=True)
        elif custom_id.startswith("pvp0:reject:"):
            await _handle_approval(interaction, approved=False)

    @app_commands.command(
        name="panel",
        description="Wyślij panel ticketów PVP0 na ten kanał.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def panel(self, interaction: discord.Interaction) -> None:
        if not (isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator):
            await interaction.response.send_message(
                "❌ Ta komenda jest dostępna tylko dla Administratorów.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        file = discord.File(config.BANNER_PATH, filename="pvp0.gif")
        await interaction.followup.send(
            view=TicketPanelView(),
            file=file,
        )

    @panel.error
    async def panel_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.errors.MissingPermissions):
            if interaction.response.is_done():
                await interaction.followup.send("❌ Ta komenda jest dostępna tylko dla Administratorów.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Ta komenda jest dostępna tylko dla Administratorów.", ephemeral=True)

    @app_commands.command(
        name="panel-tickety",
        description="Wyślij panel ticketów PVP0 na ten kanał.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def panel_tickety(self, interaction: discord.Interaction) -> None:
        if not (isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator):
            await interaction.response.send_message(
                "❌ Ta komenda jest dostępna tylko dla Administratorów.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        file = discord.File(config.BANNER_PATH, filename="pvp0.gif")
        await interaction.followup.send(
            view=TicketPanelView(),
            file=file,
        )

    @panel_tickety.error
    async def panel_tickety_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.errors.MissingPermissions):
            if interaction.response.is_done():
                await interaction.followup.send("❌ Ta komenda jest dostępna tylko dla Administratorów.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Ta komenda jest dostępna tylko dla Administratorów.", ephemeral=True)

    @app_commands.command(
        name="wyczysc-dm",
        description="Usuwa wiadomości wysłane przez bota do Ciebie na PV.",
    )
    async def wyczysc_dm(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        user = interaction.user
        dm = user.dm_channel or await user.create_dm()

        deleted = 0
        try:
            async for msg in dm.history(limit=100):
                if msg.author.id == self.bot.user.id:
                    try:
                        await msg.delete()
                        deleted += 1
                        await asyncio.sleep(0.3)
                    except discord.HTTPException:
                        pass
            await interaction.followup.send(
                f"✅ Usunięto {deleted} wiadomości bota z Twojej prywatnej rozmowy (PV).",
                ephemeral=True,
            )
        except Exception as exc:
            await interaction.followup.send(
                f"❌ Wystąpił błąd podczas usuwania wiadomości: {exc}",
                ephemeral=True,
            )

    # ── Komenda do usuwania członków gildii ─────────────────────────
    usun_group = app_commands.Group(name="usun", description="Zarządzanie usuwaniem członków z gildii")

    @usun_group.command(
        name="czlonka",
        description="Usuwa członka z gildii PVP0 (odbiera rangę, usuwa tag [PVP0] i wypisuje z bazy).",
    )
    @app_commands.describe(
        uzytkownik="Członek serwera do usunięcia z gildii",
        powod="Powód usunięcia z gildii (opcjonalny)",
    )
    async def usun_czlonka_group(
        self,
        interaction: discord.Interaction,
        uzytkownik: discord.Member,
        powod: str = "Brak podanego powodu",
    ) -> None:
        await self._process_remove_member(interaction, uzytkownik, powod)

    @app_commands.command(
        name="usun_czlonka",
        description="Usuwa członka z gildii PVP0 (odbiera rangę, usuwa tag [PVP0] i wypisuje z bazy).",
    )
    @app_commands.describe(
        uzytkownik="Członek serwera do usunięcia z gildii",
        powod="Powód usunięcia z gildii (opcjonalny)",
    )
    async def usun_czlonka_alias(
        self,
        interaction: discord.Interaction,
        uzytkownik: discord.Member,
        powod: str = "Brak podanego powodu",
    ) -> None:
        await self._process_remove_member(interaction, uzytkownik, powod)

    async def _process_remove_member(
        self,
        interaction: discord.Interaction,
        uzytkownik: discord.Member,
        powod: str,
    ) -> None:
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ Ta komenda może być użyta tylko na serwerze.", ephemeral=True)
            return

        admin = interaction.user
        if not isinstance(admin, discord.Member) or not _can_manage_tickets(admin, guild):
            await interaction.response.send_message(
                "❌ Tylko zarząd lub administratorzy mogą usuwać członków z gildii.",
                ephemeral=True,
            )
            return

        if uzytkownik.id == admin.id:
            await interaction.response.send_message("❌ Nie możesz usunąć samego siebie z gildii.", ephemeral=True)
            return

        if uzytkownik.id == guild.owner_id:
            await interaction.response.send_message("❌ Nie możesz usunąć Właściciela serwera.", ephemeral=True)
            return

        if uzytkownik.bot:
            await interaction.response.send_message("❌ Nie możesz usunąć bota.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # 1. Usuń role klanowe (Członek oraz ewentualnie Sojusz)
        roles_removed: list[str] = []
        clan_role = _get_clan_role(guild)
        if clan_role and clan_role in uzytkownik.roles:
            try:
                await uzytkownik.remove_roles(clan_role, reason=f"Usunięcie z gildii przez {admin.display_name}: {powod}")
                roles_removed.append(clan_role.name)
            except (discord.Forbidden, discord.HTTPException):
                pass

        # 2. Usuń z pliku clan_members.json
        try:
            from cogs.treasury import remove_known_clan_id
            remove_known_clan_id(uzytkownik.id)
        except Exception:
            pass

        # 3. Zresetuj pseudonim (usuń [PVP0] lub tag sojuszu z początku nicku)
        old_nick = uzytkownik.display_name
        nick_cleaned = False
        if uzytkownik.nick:
            current_nick = uzytkownik.nick
            new_nick = re.sub(r"^\[.*?\]\s*", "", current_nick).strip()
            if not new_nick:
                new_nick = None
            if new_nick != current_nick:
                try:
                    await uzytkownik.edit(nick=new_nick, reason=f"Usunięcie z gildii przez {admin.display_name}")
                    nick_cleaned = True
                except (discord.Forbidden, discord.HTTPException):
                    pass

        # 4. Wyślij DM do gracza
        dm_sent = False
        try:
            dm_embed = discord.Embed(
                title="❌ Zostałeś usunięty z gildii PVP0",
                description=(
                    f"Twoje członkostwo w gildii **PVP0** zostało zakończone przez administrację.\n\n"
                    f"**Powód:** {powod}\n"
                    f"**Osoba decydująca:** {admin.display_name}"
                ),
                color=config.COLOR_CLOSE,
                timestamp=datetime.now(timezone.utc),
            )
            dm_embed.set_footer(text="Made by Aronek • Gildia PVP0")
            await uzytkownik.send(embed=dm_embed)
            dm_sent = True
        except (discord.Forbidden, discord.HTTPException):
            dm_sent = False

        # 5. Wyślij log na kanał logów
        log_channel = None
        if config.LOG_CHANNEL_ID:
            log_channel = guild.get_channel(config.LOG_CHANNEL_ID)
        if isinstance(log_channel, discord.TextChannel):
            log_embed = discord.Embed(
                title="🗑️ Usunięto członka gildii",
                color=config.COLOR_CLOSE,
                timestamp=datetime.now(timezone.utc),
            )
            log_embed.add_field(name="Gracz", value=f"{uzytkownik.mention} (`{uzytkownik.id}`)", inline=True)
            log_embed.add_field(name="Poprzedni nick", value=f"`{old_nick}`", inline=True)
            log_embed.add_field(name="Wyrzucony przez", value=f"{admin.mention}", inline=False)
            log_embed.add_field(name="Powód", value=powod, inline=False)
            if roles_removed:
                log_embed.add_field(name="Odebrane role", value=", ".join(roles_removed), inline=False)
            log_embed.add_field(name="Powiadomienie DM", value="✅ Wysłano" if dm_sent else "⚠️ Zablokowane DM", inline=True)
            log_embed.add_field(name="Reset nicku", value="✅ Usunięto tag" if nick_cleaned else "—", inline=True)
            log_embed.set_footer(text=config.FOOTER_TEXT)
            try:
                await log_channel.send(embed=log_embed)
            except discord.HTTPException:
                pass

        # 6. Odpowiedź dla moderatora
        res_desc = [
            f"Pomyślnie usunięto gracza {uzytkownik.mention} (`{uzytkownik.name}`) z gildii PVP0.",
            f"**Powód:** {powod}",
            f"• Odebrane role: **{', '.join(roles_removed) if roles_removed else 'Brak roli do odebrania'}**",
            f"• Reset pseudonimu: **{'Zresetowano (usunięto tag)' if nick_cleaned else 'Nie zmieniono'}**",
            f"• Status DM: **{'Wysłano powiadomienie' if dm_sent else 'Gracz ma zablokowane wiadomości DM'}**",
        ]
        res_embed = discord.Embed(
            title="✅ Członek został usunięty",
            description="\n".join(res_desc),
            color=config.COLOR_SUCCESS,
        )
        res_embed.set_footer(text=config.FOOTER_TEXT)
        await interaction.followup.send(embed=res_embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tickets(bot))
    bot.add_view(TicketPanelView())
