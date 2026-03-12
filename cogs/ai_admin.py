from __future__ import annotations

import logging
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from utils.ai_client import SUPPORTED_TONES, ai_client, mask_api_key
from utils.rate_limiter import cooldown, handle_cooldown_error

log = logging.getLogger("kairos.ai_admin")

PROVIDER_LABELS = {
    "claude": "Claude (Anthropic)",
    "gemini": "Gemini (Google)",
    "openai": "ChatGPT (OpenAI)",
    "openrouter": "OpenRouter",
    "groq": "Groq",
}


class AISetupModal(discord.ui.Modal, title="Kairos AI Setup"):
    model_input: discord.ui.TextInput[AISetupModal] = discord.ui.TextInput(
        label="Model name",
        placeholder="e.g., claude-haiku-4-5, gpt-4.1-mini, gemini-2.0-flash",
        max_length=120,
        required=True,
    )
    api_key_input: discord.ui.TextInput[AISetupModal] = discord.ui.TextInput(
        label="API key",
        placeholder="Paste the API key for the provider you picked",
        max_length=300,
        style=discord.TextStyle.short,
        required=True,
    )

    def __init__(self, provider: str, requester_id: int) -> None:
        super().__init__()
        self.provider = provider
        self.requester_id = requester_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Only the admin who opened this setup can submit it.",
                ephemeral=True,
            )
            return

        if interaction.guild is None:
            await interaction.response.send_message(
                "Please use this command in a server channel.",
                ephemeral=True,
            )
            return

        guild_id = str(interaction.guild.id)
        tone = "balanced"

        existing = await ai_client.get_guild_config(guild_id)
        if existing and isinstance(existing.get("tone"), str):
            existing_tone = existing["tone"].lower().strip()
            if existing_tone in SUPPORTED_TONES:
                tone = existing_tone

        try:
            config = await ai_client.upsert_guild_config(
                guild_id=guild_id,
                provider=self.provider,
                model=str(self.model_input.value),
                api_key=str(self.api_key_input.value),
                set_by=str(interaction.user.id),
                tone=tone,
            )
        except Exception as exc:
            log.exception("Failed to save AI config for guild %s: %s", guild_id, exc)
            await interaction.response.send_message(
                "⚠️ I couldn't save the AI setup. Please check the model name and API key and try again.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="Kairos AI Updated", color=discord.Color.green())
        embed.add_field(name="Provider", value=PROVIDER_LABELS.get(config["provider"], config["provider"]), inline=False)
        embed.add_field(name="Model", value=config["model"], inline=False)
        embed.add_field(name="API Key", value=mask_api_key(config["api_key"]), inline=False)
        embed.add_field(name="Tone", value=config.get("tone", "balanced"), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ProviderSelect(discord.ui.Select["AISetupView"]):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(label="Claude (Anthropic)", value="claude"),
            discord.SelectOption(label="Gemini (Google)", value="gemini"),
            discord.SelectOption(label="ChatGPT (OpenAI)", value="openai"),
            discord.SelectOption(label="OpenRouter", value="openrouter"),
            discord.SelectOption(label="Groq", value="groq"),
        ]
        super().__init__(
            placeholder="Choose an AI provider to set up",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if view is None:
            return
        provider = self.values[0]
        await interaction.response.send_modal(
            AISetupModal(provider=provider, requester_id=view.requester_id)
        )


class AISetupView(discord.ui.View):
    def __init__(self, requester_id: int) -> None:
        super().__init__(timeout=180)
        self.requester_id = requester_id
        self.add_item(ProviderSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "This setup panel was opened by another admin.",
                ephemeral=True,
            )
            return False
        return True


class AIAdmin(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="ai_setup",
        description="Set up the AI provider, model, and API key for this server.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def ai_setup(self, interaction: discord.Interaction) -> None:
        """
        Open the AI provider setup panel for this server.

        Presents a dropdown to select a provider (Claude, Gemini, OpenAI,
        OpenRouter, Groq), then opens a modal to enter the model name and API key.
        Requires Administrator permission.

        Args:
            interaction: The Discord interaction context.
        """
        if interaction.guild is None:
            await interaction.response.send_message(
                "Please use this command in a server channel.",
                ephemeral=True,
            )
            return

        view = AISetupView(requester_id=interaction.user.id)
        await interaction.response.send_message(
            "Choose a provider below, then enter the model name and API key when Kairos asks.",
            view=view,
            ephemeral=True,
        )

    @app_commands.command(
        name="ai_status",
        description="See this server's AI provider, model, and current tone.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def ai_status(self, interaction: discord.Interaction) -> None:
        """Display the current AI provider configuration for this server.

        Shows the provider, model, masked API key, tone, and who configured it.
        Requires Administrator permission.

        Args:
            interaction: The Discord interaction context.
        """
        if interaction.guild is None:
            await interaction.response.send_message(
                "Please use this command in a server channel.",
                ephemeral=True,
            )
            return

        config = await ai_client.get_guild_config(str(interaction.guild.id))
        if not config:
            await interaction.response.send_message(
                "AI isn't set up for this server yet. Run `/ai_setup` to get started.",
                ephemeral=True,
            )
            return

        provider = str(config.get("provider", "unknown"))
        model = str(config.get("model", "(unset)"))
        tone = str(config.get("tone", "balanced"))
        set_by = str(config.get("set_by", "unknown"))
        set_at = str(config.get("set_at", "unknown"))

        embed = discord.Embed(title="Kairos AI Status", color=discord.Color.blurple())
        embed.add_field(name="Provider", value=PROVIDER_LABELS.get(provider, provider), inline=False)
        embed.add_field(name="Model", value=model, inline=False)
        embed.add_field(name="API Key", value=mask_api_key(str(config.get("api_key", ""))), inline=False)
        embed.add_field(name="Tone", value=tone, inline=False)
        embed.add_field(name="Configured By", value=f"<@{set_by}>", inline=True)
        embed.add_field(name="Configured At", value=set_at, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="ai_test",
        description="Run a quick test to check that this server's AI setup works.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @cooldown("ai_test")
    async def ai_test(self, interaction: discord.Interaction) -> None:
        """Send a live test prompt to the configured AI provider and display the response.

        Uses a simple one-sentence Bible encouragement prompt to verify that the
        provider, model, and API key are working correctly. Requires Administrator
        permission.

        Args:
            interaction: The Discord interaction context.
        """
        if interaction.guild is None:
            await interaction.response.send_message(
                "Please use this command in a server channel.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            response_text = await ai_client.generate_response(
                prompt="Say a one-sentence Bible encouragement.",
                guild_id=str(interaction.guild.id),
                user_id=str(interaction.user.id),
            )
        except Exception as exc:
            log.warning("AI test failed for guild %s: %s", interaction.guild.id, exc)
            await interaction.followup.send(
                "⚠️ The AI test failed. Please check the saved provider, model, and API key.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="AI Test Response", description=response_text[:4000], color=discord.Color.green())
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="ai_clear",
        description="Remove this server's saved AI setup.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def ai_clear(self, interaction: discord.Interaction) -> None:
        """Remove the AI provider configuration for this server.

        Clears the stored provider, model, API key, and tone. The bot will stop
        responding to AI-powered commands until `/ai_setup` is run again. Requires
        Administrator permission.

        Args:
            interaction: The Discord interaction context.
        """
        if interaction.guild is None:
            await interaction.response.send_message(
                "Please use this command in a server channel.",
                ephemeral=True,
            )
            return

        removed = await ai_client.clear_guild_config(str(interaction.guild.id))
        if not removed:
            await interaction.response.send_message(
                "There isn't an AI setup saved for this server yet.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "✅ The saved AI setup was removed for this server.",
            ephemeral=True,
        )

    @app_commands.command(
        name="ai_tone",
        description="Choose how Kairos should sound in this server.",
    )
    @app_commands.describe(tone="Pick the tone for Kairos replies in this server")
    @app_commands.checks.has_permissions(administrator=True)
    async def ai_tone(self, interaction: discord.Interaction, tone: Literal["warm", "formal", "balanced"]) -> None:
        """Set the response tone for all AI-generated content in this server.

        Applies to verses, devotions, advice, sermon outlines, and all other
        AI-powered commands. The tone persists across bot restarts. Requires
        Administrator permission.

        Args:
            interaction: The Discord interaction context.
            tone: The desired response tone — "warm", "formal", or "balanced".
        """
        if interaction.guild is None:
            await interaction.response.send_message(
                "Please use this command in a server channel.",
                ephemeral=True,
            )
            return

        try:
            config = await ai_client.set_tone(str(interaction.guild.id), tone=tone)
        except Exception as exc:
            log.exception("Failed to set tone for guild %s: %s", interaction.guild.id, exc)
            await interaction.response.send_message(
                "⚠️ I couldn't update the tone right now. Please try again.",
                ephemeral=True,
            )
            return

        provider = PROVIDER_LABELS.get(str(config.get("provider", "")), str(config.get("provider", "unknown")))
        model = str(config.get("model", "(unset)"))
        await interaction.response.send_message(
            f"✅ Kairos will now use the **{tone}** tone in this server with **{provider}** (`{model}`).",
            ephemeral=True,
        )

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if await handle_cooldown_error(interaction, error):
            return
        if isinstance(error, app_commands.MissingPermissions):
            message = "You need Administrator permission to use this command."
        else:
            log.exception("AI admin command error: %s", error)
            message = "Something went wrong with that AI admin command. Please try again."

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AIAdmin(bot))
