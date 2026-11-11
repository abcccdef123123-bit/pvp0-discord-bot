from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config


class VerifyButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="Zweryfikuj się",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id="pvp0:verify",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        assert interaction.guild and isinstance(interaction.user, discord.Member)

        role = None
        if config.VERIFIED_ROLE_ID:
            role = interaction.guild.get_role(config.VERIFIED_ROLE_ID)
        if role is None:
            for r in interaction.guild.roles:
                if r.name.lower() in ("zweryfikowany", "weryfikacja", "gracz", "member", "członek", "czlonek"):
                    role = r
                    break

        if role is None:
            await interaction.response.send_message(
                "Rola weryfikacji nie została znaleziona. Ustaw ją komendą `/ustaw rola` lub utwórz rolę 'Zweryfikowany'.",
                ephemeral=True,
            )
            return

        if role in interaction.user.roles:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Już jesteś zweryfikowany",
                    description="Masz już dostęp do pełnego serwera gildii **PVP0**.",
                    color=config.COLOR_VERIFY,
                ),
                ephemeral=True,
            )
            return

        try:
            await interaction.user.add_roles(role, reason="Weryfikacja PVP0")
        except discord.Forbidden:
            await interaction.response.send_message(
                "Nie mogę nadać roli — sprawdź hierarchię ról bota.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ Weryfikacja zakończona",
                description=(
                    f"{interaction.user.mention}, witamy na serwerze gildii **PVP0**.\n"
                    "Miłej gry i dobrych dropów."
                ),
                color=config.COLOR_SUCCESS,
            ).set_footer(text=config.FOOTER_TEXT),
            ephemeral=True,
        )


class VerificationView(discord.ui.LayoutView):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        button = VerifyButton()
        header_section = discord.ui.Section(
            discord.ui.TextDisplay("### **✅ [ Weryfikacja ] × [ PVP0 ]**"),
            accessory=button,
        )
        gallery = discord.ui.MediaGallery(discord.MediaGalleryItem("attachment://pvp0.gif"))
        container = discord.ui.Container(
            header_section,
            gallery,
            discord.ui.TextDisplay(f"-# {config.FOOTER_TEXT}"),
            accent_colour=config.COLOR_VERIFY,
        )
        self.add_item(container)


class Verification(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="panel-weryfikacja",
        description="Wyślij panel weryfikacji PVP0 na ten kanał.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def panel_weryfikacja(self, interaction: discord.Interaction) -> None:
        if not (isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator):
            await interaction.response.send_message(
                "❌ Ta komenda jest dostępna tylko dla Administratorów.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        file = discord.File(config.BANNER_PATH, filename="pvp0.gif")
        await interaction.followup.send(
            view=VerificationView(),
            file=file,
        )

    @panel_weryfikacja.error
    async def panel_weryfikacja_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.errors.MissingPermissions):
            if interaction.response.is_done():
                await interaction.followup.send("❌ Ta komenda jest dostępna tylko dla Administratorów.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Ta komenda jest dostępna tylko dla Administratorów.", ephemeral=True)

    @app_commands.command(
        name="panel_weryfikacja",
        description="Wyślij panel weryfikacji PVP0 na ten kanał.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def panel_weryfikacja_alias(self, interaction: discord.Interaction) -> None:
        await self.panel_weryfikacja(interaction)

    @panel_weryfikacja_alias.error
    async def panel_weryfikacja_alias_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        await self.panel_weryfikacja_error(interaction, error)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Verification(bot))
    bot.add_view(VerificationView())
