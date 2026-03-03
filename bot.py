import discord
from discord import app_commands
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import asyncio
import random
import os
import json

# ==============================
# ENVIRONMENT / DISCORD SETUP
# ==============================

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

CHANNELS_FILE = "channels.json"

# ==============================
# GLOBAL STATE
# ==============================

cached_result = {"status": "error", "data": "Not scraped yet"}
last_scraped_time = None
last_saved_date = None
announcement_channels = {}

# ==============================
# FILE HELPERS
# ==============================

def load_json(filename, default):
    if not os.path.exists(filename):
        return default
    with open(filename, "r") as f:
        return json.load(f)

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f)

announcement_channels = load_json(CHANNELS_FILE, {})

# ==============================
# SCRAPER
# ==============================

async def scrape_next_test():
    url = "https://anvilempires.wiki.gg/"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.google.com/"
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

# ==============================
# EMBED BUILDERS
# ==============================

def build_announcement_embed(scraped):
    embed = discord.Embed(
        title="❗Anvil Empires Test❗",
        color=discord.Color.gold()
    )

    dt = datetime.fromisoformat(scraped["data"].replace("Z", "+00:00"))
    unix = int(dt.timestamp())

    embed.description = (
        f"❗ **New Test Date:**\n"
        f"<t:{unix}:F>\n"
        f"❗ <t:{unix}:R>"
    )

    if last_scraped_time:
        formatted = last_scraped_time.strftime("%Y-%m-%d %H:%M UTC")
        embed.set_footer(text=f"Last updated: {formatted}")

    embed.timestamp = datetime.now(timezone.utc)
    return embed


def build_status_embed(scraped):
    if scraped["status"] != "ok":
        return discord.Embed(
            title="Anvil Empires Test",
            description="❌ Could not fetch test date.",
            color=discord.Color.red()
        )

    dt = datetime.fromisoformat(scraped["data"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)

    embed = discord.Embed(
        title="Anvil Empires Test",
        color=discord.Color.gold()
    )

    if now >= dt:
        embed.description = "🟢 **Test is LIVE right now!**"
        embed.color = discord.Color.green()
    else:
        unix = int(dt.timestamp())
        embed.description = (
            f"📅 **Next Test:**\n"
            f"<t:{unix}:F>\n"
            f"⏳ <t:{unix}:R>"
        )

    if last_scraped_time:
        formatted = last_scraped_time.strftime("%Y-%m-%d %H:%M UTC")
        embed.set_footer(text=f"Last updated: {formatted}")

    embed.timestamp = datetime.now(timezone.utc)
    return embed

# ==============================
# BACKGROUND SCRAPER
# ==============================

async def background_scraper():
    global cached_result, last_scraped_time, last_saved_date

    await client.wait_until_ready()

    while not client.is_closed():

        print("Scraping wiki...")
        result = await scrape_next_test()

        cached_result = result
        last_scraped_time = datetime.now(timezone.utc)

        if result["status"] == "ok":

            if result["data"] != last_saved_date:

                print("New date detected. Sending announcement...")

                last_saved_date = result["data"]
                embed = build_announcement_embed(result)

                for guild_id, channel_id in announcement_channels.items():
                    channel = client.get_channel(int(channel_id))
                    if channel:
                        await channel.send(embed=embed)

        sleep_time = random.randint(1800, 3600)
        print(f"Next scrape in {sleep_time // 60} minutes")

        await asyncio.sleep(sleep_time)

# ==============================
# SLASH COMMANDS
# ==============================

@tree.command(
    name="setannouncementchannel",
    description="Set the channel for automatic test announcements"
)
@app_commands.describe(channel="Channel where announcements will be posted")
async def setannouncementchannel(interaction: discord.Interaction, channel: discord.TextChannel):

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


@tree.command(
    name="nexttest",
    description="Check when the next Anvil Empires test is"
)
async def nexttest(interaction: discord.Interaction):

    embed = build_status_embed(cached_result)
    await interaction.response.send_message(embed=embed)

# ==============================
# MESSAGE TRIGGER
# ==============================

@client.event
async def on_message(message):

    if message.author.bot:
        return

    content = message.content.lower()

    if "when test" in content or "next test" in content:
        embed = build_status_embed(cached_result)
        await message.channel.send(embed=embed)

# ==============================
# READY EVENT
# ==============================

@client.event
async def on_ready():

    for guild in client.guilds:
        try:
            await tree.sync(guild=guild)
            print(f"Synced commands to {guild.name}")
        except Exception as e:
            print(f"Failed syncing {guild.name}: {e}")

    client.loop.create_task(background_scraper())

    print(f"Logged in as {client.user}")

# ==============================
# START BOT
# ==============================

client.run(TOKEN)
