from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config

ROLE_OPTIONS = {
    "zarzad": ("STAFF_ROLE_ID", "🛡️ Zarząd / Administracja"),
    "lider": ("APPROVAL_ROLE_1_ID", "👑 Lider"),
    "zastepca": ("APPROVAL_ROLE_2_ID", "⚔️ Zastępca"),
    "czlonek": ("CLAN_ROLE_ID", "🛡️ Członek klanu PVP0"),
    "sojusz": ("ALLIANCE_ROLE_ID", "🤝 Rola Sojusz"),
    "lider_sojuszu": ("ALLIANCE_LEADER_ROLE_ID", "🏰 Lider Sojuszu"),
    "weryfikacja": ("VERIFIED_ROLE_ID", "✅ Zweryfikowany"),
}

CHANNEL_OPTIONS = {
    "kategoria_ticketow": ("TICKET_CATEGORY_ID", "📁 Kategoria Ticketów"),
    "logi": ("LOG_CHANNEL_ID", "📜 Kanał Logów Głównych"),
    "ogloszenia": ("ANNOUNCEMENTS_CHANNEL_ID", "📢 Kanał Ogłoszeń (#ogłoszenia)"),
}


class Settings(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    ustaw_group = app_commands.Group(
        name="ustaw",
        description="Konfiguracja ról i kanałów gildii PVP0",
        default_permissions=discord.Permissions(administrator=True),
    )

    # ── /ustaw rola ──────────────────────────────────────────────────
    @ustaw_group.command(
        name="rola",
        description="Przypisz rolę Discorda do wybranej funkcji w bocie (np. Zarząd, Lider, Członek).",
    )
    @app_commands.describe(
        typ="Wybierz funkcję roli, którą chcesz skonfigurować",
        rola="Wskaż rolę na serwerze",
    )
    @app_commands.choices(
        typ=[
            app_commands.Choice(name="🛡️ Zarząd / Administracja", value="zarzad"),
            app_commands.Choice(name="👑 Lider", value="lider"),
            app_commands.Choice(name="⚔️ Zastępca", value="zastepca"),
            app_commands.Choice(name="🛡️ Członek klanu PVP0", value="czlonek"),
            app_commands.Choice(name="🤝 Rola Sojusz", value="sojusz"),
            app_commands.Choice(name="🏰 Lider Sojuszu", value="lider_sojuszu"),
            app_commands.Choice(name="✅ Rola Weryfikacji", value="weryfikacja"),
        ]
    )
    async def ustaw_rola(
        self,
        interaction: discord.Interaction,
        typ: app_commands.Choice[str],
        rola: discord.Role,
    ) -> None:
        if not (isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("❌ Ta komenda jest dostępna tylko dla Administratorów.", ephemeral=True)
            return

        opt = ROLE_OPTIONS.get(typ.value)
        if not opt:
            await interaction.response.send_message("❌ Nieprawidłowy typ roli.", ephemeral=True)
            return

        config_key, label = opt
        config.update_setting(config_key, rola.id)

        embed = discord.Embed(
            title="✅ Zaktualizowano konfigurację roli",
            description=(
                f"Funkcja: **{label}**\n"
                f"Przypisana rola: {rola.mention} (`{rola.name}`)\n"
                f"ID: `{rola.id}`\n\n"
                "💾 *Ustawienie zostało trwale zapisane i działa natychmiastowo.*"
            ),
            color=config.COLOR_SUCCESS,
        )
        embed.set_footer(text=config.FOOTER_TEXT)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /ustaw kanal ─────────────────────────────────────────────────
    @ustaw_group.command(
        name="kanal",
        description="Przypisz kanał lub kategorię Discorda do wybranej funkcji (np. Kategoria Ticketów, Logi).",
    )
    @app_commands.describe(
        typ="Wybierz funkcję kanału, którą chcesz skonfigurować",
        kanal="Wskaż kanał tekstowy lub kategorię na serwerze",
    )
    @app_commands.choices(
        typ=[
            app_commands.Choice(name="📁 Kategoria Ticketów", value="kategoria_ticketow"),
            app_commands.Choice(name="📜 Kanał Logów Głównych (#logi)", value="logi"),
            app_commands.Choice(name="📢 Kanał Ogłoszeń (#ogłoszenia)", value="ogloszenia"),
        ]
    )
    async def ustaw_kanal(
        self,
        interaction: discord.Interaction,
        typ: app_commands.Choice[str],
        kanal: discord.abc.GuildChannel,
    ) -> None:
        if not (isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("❌ Ta komenda jest dostępna tylko dla Administratorów.", ephemeral=True)
            return

        opt = CHANNEL_OPTIONS.get(typ.value)
        if not opt:
            await interaction.response.send_message("❌ Nieprawidłowy typ kanału.", ephemeral=True)
            return

        config_key, label = opt

        # Walidacja kategorii vs kanału
        if typ.value == "kategoria_ticketow" and not isinstance(kanal, discord.CategoryChannel):
            await interaction.response.send_message(
                f"⚠️ Ostrzeżenie: Wybrany element {kanal.mention} nie jest kategorią, ale został przypisany.",
                ephemeral=True,
            )

        config.update_setting(config_key, kanal.id)

        embed = discord.Embed(
            title="✅ Zaktualizowano konfigurację kanału",
            description=(
                f"Funkcja: **{label}**\n"
                f"Przypisany kanał/kategoria: {kanal.name} (`{kanal.id}`)\n\n"
                "💾 *Ustawienie zostało trwale zapisane i działa natychmiastowo.*"
            ),
            color=config.COLOR_SUCCESS,
        )
        embed.set_footer(text=config.FOOTER_TEXT)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /ustaw pokaz / /ustawienia ───────────────────────────────────
    @ustaw_group.command(
        name="pokaz",
        description="Wyświetla aktualną konfigurację ról i kanałów bota.",
    )
    async def ustaw_pokaz(self, interaction: discord.Interaction) -> None:
        await self._send_settings_embed(interaction)

    @app_commands.command(
        name="ustawienia",
        description="Wyświetla aktualną konfigurację ról i kanałów bota PVP0.",
    )
    @app_commands.default_permissions(administrator=True)
    async def ustawienia(self, interaction: discord.Interaction) -> None:
        await self._send_settings_embed(interaction)

    # Bezpośrednie aliasy
    @app_commands.command(
        name="ustaw_role",
        description="Szybkie ustawienie wybranej roli w bocie.",
    )
    @app_commands.describe(
        typ="Wybierz funkcję roli, którą chcesz skonfigurować",
        rola="Wskaż rolę na serwerze",
    )
    @app_commands.choices(
        typ=[
            app_commands.Choice(name="🛡️ Zarząd / Administracja", value="zarzad"),
            app_commands.Choice(name="👑 Lider", value="lider"),
            app_commands.Choice(name="⚔️ Zastępca", value="zastepca"),
            app_commands.Choice(name="🛡️ Członek klanu PVP0", value="czlonek"),
            app_commands.Choice(name="🤝 Rola Sojusz", value="sojusz"),
            app_commands.Choice(name="🏰 Lider Sojuszu", value="lider_sojuszu"),
            app_commands.Choice(name="✅ Rola Weryfikacji", value="weryfikacja"),
        ]
    )
    @app_commands.default_permissions(administrator=True)
    async def ustaw_role_alias(
        self,
        interaction: discord.Interaction,
        typ: app_commands.Choice[str],
        rola: discord.Role,
    ) -> None:
        await self.ustaw_rola(interaction, typ, rola)

    @app_commands.command(
        name="ustaw_kanal",
        description="Szybkie ustawienie wybranego kanału lub kategorii w bocie.",
    )
    @app_commands.describe(
        typ="Wybierz funkcję kanału, którą chcesz skonfigurować",
        kanal="Wskaż kanał tekstowy lub kategorię na serwerze",
    )
    @app_commands.choices(
        typ=[
            app_commands.Choice(name="📁 Kategoria Ticketów", value="kategoria_ticketow"),
            app_commands.Choice(name="📜 Kanał Logów Głównych (#logi)", value="logi"),
            app_commands.Choice(name="📢 Kanał Ogłoszeń (#ogłoszenia)", value="ogloszenia"),
        ]
    )
    @app_commands.default_permissions(administrator=True)
    async def ustaw_kanal_alias(
        self,
        interaction: discord.Interaction,
        typ: app_commands.Choice[str],
        kanal: discord.abc.GuildChannel,
    ) -> None:
        await self.ustaw_kanal(interaction, typ, kanal)

    async def _send_settings_embed(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ Ta komenda może być użyta tylko na serwerze.", ephemeral=True)
            return

        if not (isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("❌ Ta komenda jest dostępna tylko dla Administratorów.", ephemeral=True)
            return

        embed = discord.Embed(
            title="⚙️ Aktualna konfiguracja bota | Gildia PVP0",
            description=(
                "Poniżej znajduje się aktualne mapowanie ról oraz kanałów na serwerze.\n"
                "Aby zmienić którekolwiek ustawienie, użyj komendy `/ustaw rola` lub `/ustaw kanal`."
            ),
            color=config.COLOR_TICKET,
        )

        # Sekcja ról
        roles_text = []
        for key, (config_key, label) in ROLE_OPTIONS.items():
            role_id = getattr(config, config_key, None)
            if role_id:
                role = guild.get_role(role_id)
                val = f"{role.mention} (`{role_id}`)" if role else f"⚠️ Rola nie istnieje (`{role_id}`)"
            else:
                val = "*Nie ustawiono* ❌"
            roles_text.append(f"• **{label}:** {val}")

        embed.add_field(
            name="👥 Skonfigurowane Role",
            value="\n".join(roles_text),
            inline=False,
        )

        # Sekcja kanałów
        channels_text = []
        for key, (config_key, label) in CHANNEL_OPTIONS.items():
            ch_id = getattr(config, config_key, None)
            if ch_id:
                ch = guild.get_channel(ch_id)
                if isinstance(ch, discord.CategoryChannel):
                    val = f"📁 **{ch.name}** (`{ch_id}`)"
                elif ch:
                    val = f"{ch.mention} (`{ch_id}`)"
                else:
                    val = f"⚠️ Kanał nie istnieje (`{ch_id}`)"
            else:
                val = "*Nie ustawiono* ❌"
            channels_text.append(f"• **{label}:** {val}")

        embed.add_field(
            name="📁 Skonfigurowane Kanały i Kategorie",
            value="\n".join(channels_text),
            inline=False,
        )

        embed.set_footer(text=f"{config.FOOTER_TEXT} • Serwer ID: {guild.id}")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Settings(bot))

