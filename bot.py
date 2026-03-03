import discord
from discord import app_commands
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import asyncio
import random
import re
import os

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ---------------- GLOBAL CACHE ----------------
cached_result = {"status": "error", "data": "Not scraped yet"}
last_scraped_time = None


# ---------------- SCRAPER ----------------
def scrape_next_test():
    url = "https://anvilempires.wiki.gg/"

    # ✅ YOUR ORIGINAL HEADERS (ANTI-403 SAFE)
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
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        return {"status": "error", "data": f"Request failed: {e}"}

    soup = BeautifulSoup(response.text, "html.parser")
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

    if last_scraped_time:
        embed.set_footer(text=f"Last updated: {last_scraped_time} UTC")

    embed.timestamp = datetime.utcnow()
    return embed


# ---------------- RANDOM AUTO SCRAPER ----------------
async def background_scraper():
    global cached_result, last_scraped_time

    await client.wait_until_ready()

    # ✅ First scrape immediately on startup
    print("Initial scrape...")
    result = scrape_next_test()
    cached_result = result
    last_scraped_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

    while not client.is_closed():
        # Sleep random 30–60 minutes
        sleep_time = random.randint(1800, 3600)
        print(f"Next scrape in {sleep_time // 60} minutes")
        await asyncio.sleep(sleep_time)

        print("Scraping wiki...")
        result = scrape_next_test()
        cached_result = result
        last_scraped_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        print("Scrape finished.")


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


# ---------------- READY ----------------
@client.event
async def on_ready():
    await tree.sync()
    client.loop.create_task(background_scraper())
    print(f"Logged in as {client.user}")


client.run(TOKEN)
