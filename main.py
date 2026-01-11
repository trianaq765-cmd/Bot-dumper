import discord
import os
import io
import random
import requests
from discord import app_commands
from discord.ext import commands
from curl_cffi import requests as curl_requests # Untuk download cepat
from groq import Groq
import google.generativeai as genai
from keep_alive import keep_alive

# Setup Bot
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# === AMBIL API KEY DARI RENDER ===
SCRAPER_KEY = os.getenv("SCRAPER_API_KEY")
KEY_GROQ = os.getenv("GROQ_API_KEY")
KEY_GEMINI = os.getenv("GEMINI_API_KEY")

# ==============================================================================
# 🧠 SISTEM MULTI-AI (Groq -> Gemini -> Pollinations)
# ==============================================================================
def ask_ai_universal(prompt, system_prompt="Kamu adalah ahli coding Lua Roblox. Jawab singkat dan jelas."):
    
    # 1. PRIORITY 1: GROQ (Llama 3) - Paling Cepat
    if KEY_GROQ:
        try:
            client = Groq(api_key=KEY_GROQ)
            chat = client.chat.completions.create(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                model="llama3-8b-8192",
            )
            return f"⚡ **[Groq]**\n{chat.choices[0].message.content}"
        except:
            pass # Lanjut ke Gemini jika error

    # 2. PRIORITY 2: GOOGLE GEMINI - Paling Pintar
    if KEY_GEMINI:
        try:
            genai.configure(api_key=KEY_GEMINI)
            model = genai.GenerativeModel('gemini-pro')
            response = model.generate_content(f"{system_prompt}\n\n{prompt}")
            return f"🧠 **[Gemini]**\n{response.text}"
        except:
            pass # Lanjut ke Pollinations jika error

    # 3. PRIORITY 3: POLLINATIONS (Tanpa API Key - Darurat)
    try:
        url_poly = f"https://text.pollinations.ai/{system_prompt} {prompt}?model=openai"
        response = requests.get(url_poly, timeout=30)
        if response.status_code == 200:
            return f"🌺 **[Pollinations]**\n{response.text}"
    except:
        pass

    return "❌ **Semua AI sibuk/down.** Coba lagi nanti."

def split_message(text, limit=1900):
    return [text[i:i+limit] for i in range(0, len(text), limit)]

# ==============================================================================
# 🛡️ SISTEM DUMPER (ScraperAPI + Header Spoofing)
# ==============================================================================
def get_executor_headers():
    # Meniru Executor Roblox agar tidak dikasih HTML oleh Luarmor
    fake_place_id = random.choice(["2753915549", "155615604", "4442272183"])
    return {
        "User-Agent": "Roblox/WinInet",
        "Roblox-Place-Id": fake_place_id,
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive"
    }

@bot.event
async def on_ready():
    print(f'🔥 Bot Siap: {bot.user}')
    try:
        await bot.tree.sync()
        print("✅ Slash Commands Synced")
    except Exception as e:
        print(e)

# 1. COMMAND DUMP
@bot.tree.command(name="dump", description="Ambil script dari Junkie/Luarmor/Pastebin")
@app_commands.describe(url="URL Script")
async def dump(interaction: discord.Interaction, url: str):
    await interaction.response.defer()

    if not SCRAPER_KEY:
        return await interaction.followup.send("❌ **Error:** API Key Scraper belum disetting!")

    try:
        # Gunakan ScraperAPI dengan Residential IP
        payload = {
            'api_key': SCRAPER_KEY,
            'url': url,
            'keep_headers': 'true', # Jangan hapus header Roblox kita
        }

        response = requests.get(
            'http://api.scraperapi.com', 
            params=payload, 
            headers=get_executor_headers(), # Header Executor
            timeout=60
        )

        if response.status_code == 200:
            content = response.text
            
            # Cek apakah dapat HTML (Gagal) atau Script (Sukses)
            file_ext = "lua"
            msg = "✅ **Dump Berhasil!**"
            
            if "<!DOCTYPE html>" in content or "<html" in content[:100]:
                file_ext = "html"
                msg = "⚠️ **Peringatan:** Target mendeteksi bot dan mengirim HTML."

            file_data = io.BytesIO(content.encode("utf-8"))
            
            await interaction.followup.send(
                content=f"{msg}\n📦 Size: `{len(content)} bytes`",
                file=discord.File(file_data, filename=f"Dumped.{file_ext}")
            )
        else:
            await interaction.followup.send(f"❌ Gagal: `{response.status_code}`")

    except Exception as e:
        await interaction.followup.send(f"💀 Error: `{str(e)}`")

# 2. COMMAND TANYA AI
@bot.tree.command(name="tanya", description="Tanya AI tentang coding")
async def tanya(interaction: discord.Interaction, pertanyaan: str):
    await interaction.response.defer()
    jawaban = ask_ai_universal(pertanyaan)
    
    chunks = split_message(jawaban)
    await interaction.followup.send(f"🤖 **Q:** {pertanyaan}\n\n{chunks[0]}")
    for c in chunks[1:]: await interaction.channel.send(c)

# 3. COMMAND EXPLAIN (DUMP + AI)
@bot.tree.command(name="explain", description="AI akan membaca script dari URL dan menjelaskannya")
async def explain(interaction: discord.Interaction, url: str):
    await interaction.response.defer()
    
    try:
        # Download cepat pakai curl_cffi (tanpa proxy mahal)
        res = curl_requests.get(url, impersonate="chrome110", timeout=10)
        script_content = res.text[:6000] # Ambil 6000 karakter pertama
        
        prompt = f"Analisa script Lua Roblox ini. Apa kegunaannya? Apakah aman?:\n\n{script_content}"
        jawaban = ask_ai_universal(prompt, system_prompt="Kamu adalah Security Analyst.")
        
        chunks = split_message(jawaban)
        await interaction.followup.send(f"🔍 **Analisa:** `{url}`\n\n{chunks[0]}")
        for c in chunks[1:]: await interaction.channel.send(c)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Gagal analisa: `{str(e)}`")

# Start Server & Bot
keep_alive()
try:
    bot.run(os.getenv("DISCORD_TOKEN"))
except:
    print("❌ Token Discord Salah!")
