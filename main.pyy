import discord
import os
import io
import random
from discord import app_commands
from discord.ext import commands
from curl_cffi import requests # Library Sakti
from keep_alive import keep_alive

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# List User Agent Executor
UA_LIST = [
    "Roblox/WinInet",
    "Synapse-X/2.0",
    "Sentinel/3.0",
    "Krnl/1.0"
]

@bot.event
async def on_ready():
    print(f'🔥 Bot Siap: {bot.user}')
    await bot.tree.sync()

@bot.tree.command(name="dump", description="Dump Luarmor/Protected Script")
@app_commands.describe(url="URL Script")
async def dump(interaction: discord.Interaction, url: str):
    await interaction.response.defer()

    try:
        # === TEKNIK IMPERSONATE ===
        # Kita pakai browser chrome110 untuk TLS Handshake (Biar lolos firewall)
        # Tapi kita timpa User-Agent nya jadi Roblox (Biar lolos Luarmor)
        
        chosen_ua = random.choice(UA_LIST)
        
        headers = {
            "User-Agent": chosen_ua,
            "Roblox-Place-Id": "2753915549", # Blox Fruits Place ID (Pancingan)
            "Roblox-Game-Id": "9876543210",
            "Accept": "*/*",
            "Connection": "keep-alive"
        }

        # Request Langsung (Tanpa ScraperAPI dulu, biar JA3 fingerprint kita asli)
        response = requests.get(
            url,
            impersonate="chrome110", # Ini kunci bypass Cloudflare/Luarmor
            headers=headers,
            timeout=15
        )

        content = response.text
        file_ext = "lua"
        
        # Cek apakah masih HTML?
        if "<!DOCTYPE html>" in content or "<html" in content[:50]:
            # Jika masih HTML, berarti Luarmor memaksa Javascript Challenge
            # Kita coba cari URL script asli di dalam HTML (biasanya di variabel JS)
            import re
            
            # Cari pola link script di dalam HTML
            # Luarmor sering menyembunyikan link asli di variabel "loadURL" atau "script"
            found_links = re.findall(r'https?://[^\s"\'<>]+', content)
            
            potential_script = [l for l in found_links if "raw" in l or "get" in l or "api" in l]
            
            if potential_script:
                msg = f"⚠️ **Luarmor HTML Detected.**\nTapi saya menemukan link potensial di dalamnya:\n" + "\n".join([f"`{x}`" for x in potential_script[:3]])
                file_ext = "html"
            else:
                msg = "❌ **Gagal.** Luarmor masih mengirimkan halaman Web (JS Challenge aktif)."
                file_ext = "html"
        else:
            msg = f"✅ **LUARMOR TEMBUS!**\nUser-Agent: `{chosen_ua}`"

        file_data = io.BytesIO(content.encode("utf-8"))
        
        await interaction.followup.send(
            content=f"{msg}\nSize: `{len(content)} bytes`",
            file=discord.File(file_data, filename=f"Result.{file_ext}")
        )

    except Exception as e:
        await interaction.followup.send(f"💀 Error: {str(e)}")

keep_alive()
try:
    bot.run(os.getenv("DISCORD_TOKEN"))
except:
    print("Token Error")
