import discord
import requests
import os
import io
from discord import app_commands
from discord.ext import commands
from keep_alive import keep_alive

# Setup Bot
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents) # Prefix buat cadangan

# Ambil API Key ScraperAPI dari Environment Render
SCRAPER_KEY = os.getenv("SCRAPER_API_KEY")

# Header Palsu (Meniru Executor Delta Android)
EXECUTOR_HEADERS = {
    "User-Agent": "Delta Android/2.0",
    "Accept-Encoding": "gzip",
    "Connection": "Keep-Alive"
}

@bot.event
async def on_ready():
    print(f'🔥 Bot Masuk sebagai: {bot.user}')
    
    # Sinkronisasi Slash Commands ke Discord
    try:
        synced = await bot.tree.sync()
        print(f"✅ Berhasil sinkronisasi {len(synced)} slash commands!")
    except Exception as e:
        print(f"❌ Gagal sinkronisasi: {e}")

# === SLASH COMMAND: /dump ===
@bot.tree.command(name="dump", description="Ambil script menggunakan Residential IP (Anti-Blokir)")
@app_commands.describe(url="Masukkan URL Script (Raw/Junkie/Pastebin)")
async def dump(interaction: discord.Interaction, url: str):
    
    # 1. Defer: Memberi tahu Discord "Tunggu sebentar" (Agar tidak timeout)
    await interaction.response.defer()

    if not SCRAPER_KEY:
        return await interaction.followup.send("❌ **Error:** API Key Scraper belum disetting di server!")

    try:
        # 2. Setup Request ke ScraperAPI
        payload = {
            'api_key': SCRAPER_KEY,
            'url': url,
            'keep_headers': 'true', # Wajib true agar User-Agent Delta kita tidak dihapus
            # 'premium': 'true'     # Aktifkan ini HANYA jika kamu beli paket berbayar ScraperAPI
        }

        # 3. Kirim Request
        # Kita request ke API Scraper -> Mereka request ke Target -> Balik ke kita
        response = requests.get(
            'http://api.scraperapi.com', 
            params=payload, 
            headers=EXECUTOR_HEADERS, 
            timeout=60 # Timeout panjang karena proxy residential kadang lambat
        )

        # 4. Cek Hasil
        if response.status_code == 200:
            content = response.text
            
            if not content:
                return await interaction.followup.send("⚠️ **File Ditemukan tapi Kosong.**")

            # Simpan ke memori sebagai file virtual
            file_data = io.BytesIO(content.encode("utf-8"))
            
            # Buat Embed Cantik
            embed = discord.Embed(title="✅ Script Dumped!", color=discord.Color.green())
            embed.add_field(name="Target", value=f"`{url}`", inline=False)
            embed.add_field(name="Size", value=f"`{len(content)} bytes`", inline=True)
            embed.add_field(name="Route", value="`Residential Proxy (ScraperAPI)`", inline=True)
            embed.set_footer(text="Powered by Executor Emulator")

            # Kirim File + Embed
            await interaction.followup.send(
                embed=embed,
                file=discord.File(file_data, filename="Dumped_Script.lua")
            )
            
        elif response.status_code == 403:
            await interaction.followup.send(f"🛡️ **Terblokir (403).**\nTarget memiliki proteksi sangat tinggi atau API Key habis.")
            
        elif response.status_code == 404:
            await interaction.followup.send(f"❌ **Tidak Ditemukan (404).**\nCek kembali URL kamu.")
            
        else:
            await interaction.followup.send(f"❌ **Gagal:** Server merespon dengan kode `{response.status_code}`")

    except Exception as e:
        await interaction.followup.send(f"💀 **System Error:** `{str(e)}`")

# Jalankan Web Server (Supaya Render tidak mati)
keep_alive()

# Jalankan Bot
try:
    bot.run(os.getenv("DISCORD_TOKEN"))
except:
    print("❌ Token Discord salah atau tidak ada.")
@bot.event
async def on_ready():
    print(f'🤖 Bot {bot.user} Siap Tempur!')
    print(f'🕵️  Total User-Agents: {len(EXECUTOR_AGENTS)}')

@bot.command()
async def dump(ctx, url: str = None):
    if not url:
        return await ctx.send("❌ **Gunakan:** `!dump <url_script>`")

    # A. PILIH IDENTITAS (User-Agent Acak)
    random_agent = random.choice(EXECUTOR_AGENTS)
    
    # B. PILIH IP (Proxy Acak)
    current_proxy = get_proxy()
    
    # Setup Headers
    headers = {
        "User-Agent": random_agent,
        "Accept-Encoding": "gzip",
        "Connection": "Keep-Alive"
        # Kita hapus "Host" agar requests otomatis menyesuaikan dengan URL target
    }

    # Info status ke Discord
    status_msg = f"🔄 **Dumping...**\n🎭 **Agent:** `{random_agent}`\n"
    if current_proxy:
        status_msg += f"🌍 **IP Route:** `Proxy Aktif`"
    else:
        status_msg += f"🌍 **IP Route:** `Server IP (Raw)`"
    
    msg = await ctx.send(status_msg)

    try:
        # C. EKSEKUSI REQUEST
        response = requests.get(
            url, 
            headers=headers, 
            proxies=current_proxy, 
            timeout=20 # Timeout agak lama karena proxy biasanya lambat
        )

        # D. PENANGANAN HASIL
        if response.status_code == 200:
            content = response.text
            
            if not content:
                return await msg.edit(content="⚠️ **File Kosong!** URL benar tapi tidak ada isi.")

            # Simpan ke memori (Virtual File)
            file_data = io.BytesIO(content.encode("utf-8"))
            
            # Kirim File
            await ctx.send(
                content=f"✅ **Sukses Dump!**\nTarget: `{url}`\nSize: `{len(content)} bytes`",
                file=discord.File(file_data, filename="Dumped_Script.lua")
            )
            await msg.delete() # Hapus pesan loading
        
        elif response.status_code == 403:
            await msg.edit(content=f"🛡️ **Gagal (403 Forbidden)**\nTarget memblokir IP/User-Agent ini.\nCoba lagi untuk ganti IP/Agent.")
            
        else:
            await msg.edit(content=f"❌ **Gagal!** Status Code: `{response.status_code}`")

    except requests.exceptions.ProxyError:
        await msg.edit(content="💀 **Proxy Error!** Proxy yang dipakai mati. Coba lagi (Bot akan pilih proxy lain).")
    except Exception as e:
        await msg.edit(content=f"❌ **Error System:** `{str(e)}`")

# Keep Alive & Run
keep_alive()
try:
    bot.run(os.getenv("DISCORD_TOKEN"))
except:
    print("Token salah/tidak ditemukan.")
