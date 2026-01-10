import discord
import requests
import os
import io
import random
from discord import app_commands
from discord.ext import commands
from keep_alive import keep_alive

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
SCRAPER_KEY = os.getenv("SCRAPER_API_KEY")

# === HEADER SAKTI (Meniru Executor Roblox Asli) ===
def get_executor_headers():
    # ID Game Populer (Blox Fruits, Pet Sim X, dll) biar dikira main game asli
    fake_place_id = random.choice(["2753915549", "6284583030", "155615604"])
    fake_job_id = os.urandom(16).hex() # Random Job ID
    
    return {
        # User Agent Executor Paling Umum
        "User-Agent": "Roblox/WinInet", 
        
        # Header Khas Roblox (PENTING!)
        "Roblox-Place-Id": fake_place_id,
        "Roblox-Game-Id": fake_job_id,
        "Roblox-Session-Id": os.urandom(20).hex(),
        
        # Header Standar
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        
        # Header Tambahan untuk Delta/Fluxus
        "Fingerprint": os.urandom(32).hex()
    }

@bot.event
async def on_ready():
    print(f'🔥 Bot Siap: {bot.user}')
    await bot.tree.sync()

@bot.tree.command(name="dump", description="Dump script (Mode: Executor Simulation)")
@app_commands.describe(url="URL Script")
async def dump(interaction: discord.Interaction, url: str):
    await interaction.response.defer()

    if not SCRAPER_KEY:
        return await interaction.followup.send("❌ API Key Error")

    try:
        # Konfigurasi ScraperAPI: 
        # Kita minta 'keep_headers=true' agar Header Roblox kita TIDAK DIHAPUS.
        payload = {
            'api_key': SCRAPER_KEY,
            'url': url,
            'keep_headers': 'true', 
            # 'premium': 'true' # Aktifkan kalau punya saldo berbayar
        }

        # Generate Header Executor Palsu
        fake_headers = get_executor_headers()

        response = requests.get(
            'http://api.scraperapi.com', 
            params=payload, 
            headers=fake_headers,
            timeout=30
        )

        if response.status_code == 200:
            content = response.text
            
            # CEK APAKAH INI HTML ATAU SCRIPT ASLI?
            if "<!DOCTYPE html>" in content or "<html" in content[:100]:
                # Masih dapat HTML :(
                # Coba cari bagian script di dalam HTML (Luarmor kadang taruh di blob)
                file_ext = "html" # Gagal, dikasih HTML
                status_text = "⚠️ **Peringatan:** Target mendeteksi bot dan mengirim Halaman Web, bukan Script."
            else:
                # Berhasil dapat Raw Text!
                file_ext = "lua"
                status_text = "✅ **Sukses!** Target mengira ini Executor Asli."

            file_data = io.BytesIO(content.encode("utf-8"))
            
            await interaction.followup.send(
                content=f"{status_text}\nSize: `{len(content)} bytes`",
                file=discord.File(file_data, filename=f"Dump_Result.{file_ext}")
            )
            
        else:
            await interaction.followup.send(f"❌ Gagal: {response.status_code}")

    except Exception as e:
        await interaction.followup.send(f"💀 Error: {str(e)}")

keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))
