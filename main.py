import discord
import requests
import os
import io
import random
from discord.ext import commands
from keep_alive import keep_alive

# ================= KONFIGURASI =================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# 1. DAFTAR USER-AGENT EXECUTOR (Identitas Palsu)
EXECUTOR_AGENTS = [
    "Roblox/WinInet",                       # Standar PC
    "Delta Android/2.0",                    # Delta Mobile
    "Fluxus Android/2.0",                   # Fluxus Mobile
    "Arceus X/3.0",                         # Arceus X
    "Synapse X/v2.19.8b",                   # Synapse PC
    "Krnl/Client",                          # Krnl PC
    "Hydrogen/1.0 Android",                 # Hydrogen
    "Codex/Android/2.1",                    # Codex
    "Sentinel/v3",                          # Sentinel
    "ScriptWare/iOS/1.0"                    # Script-Ware
]

# 2. LOAD PROXIES (IP Palsu)
def get_proxy():
    if not os.path.exists("proxies.txt"):
        return None
    
    with open("proxies.txt", "r") as f:
        proxies = [line.strip() for line in f if line.strip()]
    
    if not proxies:
        return None
        
    # Ambil 1 proxy secara acak
    proxy_ip = random.choice(proxies)
    return {
        "http": f"http://{proxy_ip}",
        "https": f"http://{proxy_ip}"
    }

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
