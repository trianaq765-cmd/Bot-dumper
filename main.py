import discord
import os
import io
import requests # Kita kembali ke requests biasa karena ScraperAPI yang handle sisanya
from discord.ext import commands
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Ambil API Key dari Environment Render
SCRAPER_KEY = os.getenv("SCRAPER_API_KEY") # Masukkan key kamu di Render

@bot.command()
async def dump(ctx, url: str = None):
    if not url: return await ctx.send("❌ `!dump <url>`")
    
    status_msg = await ctx.send(f"🔄 **Dumping via Residential Proxy Network...**\nTarget: `{url}`")

    try:
        # Konfigurasi payload untuk ScraperAPI
        # 'keep_headers': 'true' -> Agar server target tetap melihat User-Agent palsu kita (Delta/Synapse)
        payload = {
            'api_key': SCRAPER_KEY,
            'url': url,
            'keep_headers': 'true'
        }
        
        # Header Executor Palsu
        headers = {
            "User-Agent": "Delta Android/2.0",
            "Accept-Encoding": "gzip"
        }

        # Tembak ke ScraperAPI -> Mereka tembak ke Target pakai IP Residential -> Balik ke kita
        response = requests.get('http://api.scraperapi.com', params=payload, headers=headers, timeout=60)

        if response.status_code == 200:
            content = response.text
            if not content: return await status_msg.edit(content="⚠️ Kosong.")
            
            file_data = io.BytesIO(content.encode("utf-8"))
            await status_msg.delete()
            await ctx.send(
                content=f"✅ **Sukses!** (IP: Hidden Residential)\nSize: `{len(content)} bytes`",
                file=discord.File(file_data, filename="Dumped.lua")
            )
        else:
            await status_msg.edit(content=f"❌ Gagal: {response.status_code}\nRespon: {response.text[:100]}")

    except Exception as e:
        await status_msg.edit(content=f"💀 Error: {str(e)}")

keep_alive()
try:
    bot.run(os.getenv("DISCORD_TOKEN"))
except:
    print("Token Error")    
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
