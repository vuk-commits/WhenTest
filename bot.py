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

# ---------------- GLOBAL STATE ----------------
cached_result = {"status": "error", "data": "Not scraped yet"}
last_scraped_time = None
last_saved_date = None
last_announced_live = False
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


# ---------------- CHECK IF TEST IS LIVE ----------------
def is_test_live(scraped):
    if scraped["status"] != "ok":
        return False
    
    dt = datetime.fromisoformat(scraped["data"].replace("Z", "+00:00"))
    
    # Ensure dt is timezone-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    now = datetime.now(timezone.utc)
    return now >= dt


# ---------------- LIVE EMBED ----------------
def build_live_embed():
    embed = discord.Embed(title=" No new test date!")
    embed.description = "❔ **There is no new test date, waiting for devs to update it!** ❔"
    embed.color = discord.Color.red()
    
    if last_scraped_time:
        formatted = last_scraped_time.strftime("%Y-%m-%d %H:%M UTC")
        embed.set_footer(text=f"Last updated: {formatted}")
    
    embed.timestamp = datetime.now(timezone.utc)
    return embed


# ---------------- NORMAL EMBED (USER COMMANDS) ----------------
def build_embed(scraped):
    # Check if test is live first
    if is_test_live(scraped):
        return build_live_embed()
    
    embed = discord.Embed(title="When is the next Anvil Empires Test?")

    if scraped["status"] == "ok":
        dt = datetime.fromisoformat(scraped["data"].replace("Z", "+00:00"))
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

    if last_scraped_time:
        formatted = last_scraped_time.strftime("%Y-%m-%d %H:%M UTC")
        embed.set_footer(text=f"Last updated: {formatted}")

    embed.timestamp = datetime.now(timezone.utc)

    return embed


# ---------------- ANNOUNCEMENT EMBED ----------------
def build_announcement_embed(scraped):
    embed = discord.Embed(title="❗Anvil Empires Test has a new date!❗")

    dt = datetime.fromisoformat(scraped["data"].replace("Z", "+00:00"))
    unix = int(dt.timestamp())

    embed.description = (
        f"❗ **New Test Date:**\n"
        f"<t:{unix}:F>\n"
        f"❗ <t:{unix}:R>"
    )

    embed.color = discord.Color.gold()

    if last_scraped_time:
        formatted = last_scraped_time.strftime("%Y-%m-%d %H:%M UTC")
        embed.set_footer(text=f"Last updated: {formatted}")

    embed.timestamp = datetime.now(timezone.utc)

    return embed


# ---------------- AUTO SCRAPER LOOP ----------------
async def background_scraper():
    global cached_result, last_scraped_time, last_saved_date, last_announced_live

    await client.wait_until_ready()

    while not client.is_closed():

        print("Scraping wiki...")

        result = await scrape_next_test()
        cached_result = result
        last_scraped_time = datetime.now(timezone.utc)

        if result["status"] == "ok":
            # Check if test is now live
            if is_test_live(result):
                if not last_announced_live:
                    print("Test is LIVE! Sending live announcement...")
                    last_announced_live = True
                    embed = build_live_embed()

                    for guild_id, channel_id in announcement_channels.items():
                        channel = client.get_channel(int(channel_id))
                        if channel:
                            await channel.send(content="📢 **THE TEST IS LIVE!**", embed=embed)
            else:
                # Test is not yet live, check for new date
                if result["data"] != last_saved_date:
                    print("New date detected. Sending announcement...")
                    last_saved_date = result["data"]
                    last_announced_live = False

                    embed = build_announcement_embed(result)

                    for guild_id, channel_id in announcement_channels.items():
                        channel = client.get_channel(int(channel_id))
                        if channel:
                            await channel.send(embed=embed)

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


# ---------------- SET ANNOUNCEMENT CHANNEL ----------------
@tree.command(name="setannouncementchannel", description="Set the channel for automatic test announcements")
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


# ---------------- READY ----------------
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


client.run(TOKEN)
