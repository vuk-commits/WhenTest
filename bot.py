import discord
from discord import app_commands
from discord.ext import tasks
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import time
import re
import json
import os

TOKEN = os.getenv("TOKEN")  # safer than hardcoding

GLOBAL_COOLDOWN = 60  # 10 minutes
CACHE_DURATION = 60

CHANNELS_FILE = "channels.json"
COOLDOWN_FILE = "cooldown.json"

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

cached_result = None
cached_timestamp = 0
last_announced_time = None


# ---------------- FILE HELPERS ----------------
def load_json(filename, default):
    if not os.path.exists(filename):
        return default
    with open(filename, "r") as f:
        return json.load(f)


def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f)


announcement_channels = load_json(CHANNELS_FILE, {})
cooldowns = load_json(COOLDOWN_FILE, {})


# ---------------- SCRAPER ----------------
def scrape_next_test():
    url = "https://anvilempires.wiki.gg/"
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    countdown = soup.find("div", attrs={"data-jst-time": True})

    if not countdown:
        return {"status": "error", "data": "Countdown not found"}

    text_over = countdown.get("data-jst-text-over", "")
    next_time = countdown.get("data-jst-time")

    if "LIVE" in text_over.upper():
        return {"status": "live", "data": None}

    if not next_time:
        return {"status": "error", "data": "Time not found"}

    return {"status": "scheduled", "data": next_time}


# ---------------- EMBED ----------------
def build_embed(scraped):
    embed = discord.Embed(title="Anvil Empires Test Status")

    if scraped["status"] == "live":
        embed.description = "🔥 **TEST IS CURRENTLY LIVE!**"
        embed.color = discord.Color.red()

    elif scraped["status"] == "scheduled":
        dt = datetime.strptime(scraped["data"], "%Y-%m-%d %H:%M")
        unix = int(dt.timestamp())

        embed.description = (
            f"🛡️ **Next Test Starts:**\n"
            f"<t:{unix}:F>\n"
            f"⏳ <t:{unix}:R>"
        )
        embed.color = discord.Color.green()

    else:
        embed.description = f"⚠️ {scraped['data']}"
        embed.color = discord.Color.yellow()

    embed.timestamp = datetime.utcnow()
    embed.set_footer(text="Data from anvilempires.wiki.gg")

    return embed


# ---------------- CACHE ----------------
def get_next_test():
    global cached_result, cached_timestamp

    now = time.time()
    if cached_result and (now - cached_timestamp < CACHE_DURATION):
        return cached_result

    scraped = scrape_next_test()
    cached_result = scraped
    cached_timestamp = now
    return scraped


# ---------------- PER-SERVER COOLDOWN ----------------
def check_cooldown(guild_id):
    now = time.time()
    guild_id = str(guild_id)

    last_time = cooldowns.get(guild_id, 0)

    if now - last_time < GLOBAL_COOLDOWN:
        remaining = int(GLOBAL_COOLDOWN - (now - last_time))
        return remaining

    cooldowns[guild_id] = now
    save_json(COOLDOWN_FILE, cooldowns)
    return 0


# ---------------- AUTO ANNOUNCER ----------------
@tasks.loop(minutes=10)
async def auto_check():
    global last_announced_time

    scraped = scrape_next_test()

    if scraped["status"] == "scheduled":
        if scraped["data"] != last_announced_time:
            last_announced_time = scraped["data"]
            embed = build_embed(scraped)

            for channel_id in announcement_channels.values():
                channel = client.get_channel(int(channel_id))
                if channel:
                    await channel.send(
                        content="📢 **Test Date Updated!**",
                        embed=embed
                    )

    elif scraped["status"] == "live":
        if last_announced_time != "live":
            last_announced_time = "live"
            embed = build_embed(scraped)

            for channel_id in announcement_channels.values():
                channel = client.get_channel(int(channel_id))
                if channel:
                    await channel.send(
                        content="📢 **The test is now LIVE!**",
                        embed=embed
                    )


# ---------------- CHAT TRIGGER ----------------
@client.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    if re.search(r"\bwhen\b.*\b(test|war)\b", message.content.lower()):
        remaining = check_cooldown(message.guild.id)

        if remaining > 0:
            mins, secs = divmod(remaining, 60)
            await message.channel.send(
                f"⏳ Command on cooldown. Try again in {mins}m {secs}s.",
                delete_after=3  # automatically delete after 5 seconds
            )
            return

        embed = build_embed(get_next_test())
        await message.channel.send(embed=embed)


# ---------------- SLASH COMMANDS ----------------
@tree.command(name="nexttest", description="Shows the next test date")
async def nexttest(interaction: discord.Interaction):

    remaining = check_cooldown(interaction.guild.id)

    if remaining > 0:
        mins, secs = divmod(remaining, 60)
        await interaction.response.send_message(
            f"⏳ Command on cooldown. Try again in {mins}m {secs}s.",
            ephemeral=True
        )
        return

    embed = build_embed(get_next_test())
    await interaction.response.send_message(embed=embed)


@tree.command(name="setannouncement", description="Set announcement channel")
@app_commands.describe(channel="Channel to post updates in")
async def setannouncement(interaction: discord.Interaction, channel: discord.TextChannel):

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Administrator permission required.",
            ephemeral=True
        )
        return

    announcement_channels[str(interaction.guild.id)] = channel.id
    save_json(CHANNELS_FILE, announcement_channels)

    await interaction.response.send_message(
        f"✅ Announcement channel set to {channel.mention}",
        ephemeral=True
    )


@tree.command(name="removeannouncement", description="Remove announcement channel")
async def removeannouncement(interaction: discord.Interaction):

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Administrator permission required.",
            ephemeral=True
        )
        return

    guild_id = str(interaction.guild.id)

    if guild_id in announcement_channels:
        del announcement_channels[guild_id]
        save_json(CHANNELS_FILE, announcement_channels)
        await interaction.response.send_message(
            "✅ Announcement channel removed.",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "⚠️ No announcement channel set.",
            ephemeral=True
        )


# ---------------- READY ----------------
@client.event
async def on_ready():
    await tree.sync()
    auto_check.start()
    print(f"Logged in as {client.user}")


client.run(TOKEN)
