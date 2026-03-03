import discord
from discord import app_commands
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import asyncio
import random
import re
import os
import json

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

CHANNELS_FILE = "channels.json"

# ---------------- GLOBAL CACHE ----------------
cached_result = {"status": "error", "data": "Not scraped yet"}
last_scraped_time = None
last_announced_date = None
announcement_channels = {}


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


# ---------------- SCRAPER ----------------
async def scrape_next_test():
    url = "https://anvilempires.wiki.gg/"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.google.com/",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=15) as response:
                if response.status != 200:
                    return {"status": "error", "data": f"HTTP {response.status}"}
                text = await response.text()
    except Exception as e:
        return {"status": "error", "data": f"Request failed: {e}"}

    soup = BeautifulSoup(text, "html.parser")
    countdown = soup.find("div", attrs={"data-jst-time": True})

    if not countdown:
        return {"status": "error", "data": "Countdown not found"}

    next_time = countdown.get("data-jst-time")

    if not next_time:
        return {"status": "error", "data": "data-jst-time not found"}

    return {"status": "ok", "data": next_time}


# ---------------- EMBED ----------------
def build_embed(scraped):
    embed = discord.Embed(title="Next Anvil Empires Test")

    if scraped["status"] == "ok":
        try:
            dt = datetime.fromisoformat(scraped["data"].replace("Z", "+00:00"))
        except ValueError:
            embed.description = f"⚠️ Unknown date format:\n{scraped['data']}"
            embed.color = discord.Color.red()
            return embed

        unix = int(dt.timestamp())

        embed.description = (
            f"🛡️ **Next Test Date:**\n"
            f"<t:{unix}:F>\n"
            f"⏳ <t:{unix}:R>"
        )
        embed.color = discord.Color.green()
    else:
        embed.description = f"⚠️ {scraped['data']}"
        embed.color = discord.Color.red()

    # Proper footer formatting (no Discord timestamp markdown)
    if last_scraped_time:
        formatted = last_scraped_time.strftime("%Y-%m-%d %H:%M UTC")
        embed.set_footer(text=f"Last updated: {formatted}")

    # This automatically shows "Today at ..." on the right side
    embed.timestamp = datetime.now(timezone.utc)

    return embed


# ---------------- AUTO SCRAPER LOOP ----------------
async def background_scraper():
    global cached_result, last_scraped_time, last_announced_date

    await client.wait_until_ready()

    while not client.is_closed():

        print("Scraping wiki...")

        result = await scrape_next_test()
        cached_result = result
        last_scraped_time = datetime.now(timezone.utc)

        # Auto announce if date changed
        if result["status"] == "ok":
            if result["data"] != last_announced_date:
                last_announced_date = result["data"]

                embed = build_embed(result)

                for channel_id in announcement_channels.values():
                    channel = client.get_channel(int(channel_id))
                    if channel:
                        await channel.send(
                            content="📢 **Test Date Updated!**",
                            embed=embed
                        )

        print("Scrape finished.")

        sleep_time = random.randint(1800, 3600)
        print(f"Next scrape in {sleep_time // 60} minutes")
        await asyncio.sleep(sleep_time)


# ---------------- CHAT TRIGGER ----------------
@client.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    if re.search(r"\bwhen\b.*\b(test|war)\b", message.content.lower()):
        embed = build_embed(cached_result)
        await message.channel.send(embed=embed)


# ---------------- SLASH COMMAND ----------------
@tree.command(name="nexttest", description="Shows the next test date")
async def nexttest(interaction: discord.Interaction):

    if not interaction.guild:
        await interaction.response.send_message(
            "❌ This command can only be used in a server.",
            ephemeral=True
        )
        return

    embed = build_embed(cached_result)
    await interaction.response.send_message(embed=embed)


# ---------------- ANNOUNCEMENT COMMANDS ----------------
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
    client.loop.create_task(background_scraper())
    print(f"Logged in as {client.user}")


client.run(TOKEN)
