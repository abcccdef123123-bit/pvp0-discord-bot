from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import config


def build_verification_embed() -> discord.Embed:
    embed = discord.Embed(
        title="✅  [ Weryfikacja ] × [ PVP0 ]",
        description=(
            "```\n[ Dostęp do serwera ]\n```\n"
            "Aby uzyskać dostęp do pełnego serwera gildii **PVP0**, kliknij przycisk poniżej.\n\n"
            "```\nKlikając przycisk potwierdzasz, że zapoznałeś się z regulaminem serwera. ✅\n```"
        ),
        color=config.COLOR_VERIFY,
    )
    embed.set_footer(text=config.FOOTER_TEXT)
    return embed


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

        role = interaction.guild.get_role(config.VERIFIED_ROLE_ID)
        if role is None:
            await interaction.response.send_message(
                "Rola weryfikacji nie została znaleziona. Skontaktuj się z administracją.",
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


class VerificationView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(VerifyButton())


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
        await interaction.response.send_message(
            embed=build_verification_embed(),
            view=VerificationView(),
        )

    @panel_weryfikacja.error
    async def panel_weryfikacja_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.errors.MissingPermissions):
            if interaction.response.is_done():
                await interaction.followup.send("❌ Ta komenda jest dostępna tylko dla Administratorów.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Ta komenda jest dostępna tylko dla Administratorów.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Verification(bot))
    bot.add_view(VerificationView())
