import discord
import os
import io
import random
import logging
from urllib.parse import quote
from discord import app_commands
from discord.ext import commands
from curl_cffi import requests as curl_requests
from groq import Groq
import google.generativeai as genai
import requests
from keep_alive import keep_alive

# ==============================================================================
# 📋 LOGGING SETUP
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ==============================================================================
# 🤖 BOT SETUP
# ==============================================================================
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ==============================================================================
# 🔑 API KEYS (dari Environment Variables)
# ==============================================================================
SCRAPER_KEY = os.getenv("SCRAPER_API_KEY")
KEY_GROQ = os.getenv("GROQ_API_KEY")
KEY_GEMINI = os.getenv("GEMINI_API_KEY")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Validasi Token
if not DISCORD_TOKEN:
    logger.critical("❌ DISCORD_TOKEN tidak ditemukan!")
    exit(1)

# ==============================================================================
# 🧠 SISTEM MULTI-AI (Update 2025)
# ==============================================================================

# Model Terbaru 2025
GROQ_MODELS = [
    "llama-3.3-70b-versatile",      # Terbaru & Terpintar
    "llama-3.1-8b-instant",          # Cepat
    "llama-3.2-90b-vision-preview",  # Vision (jika perlu)
    "mixtral-8x7b-32768",            # Alternatif
]

GEMINI_MODELS = [
    "gemini-2.0-flash",              # Terbaru 2025
    "gemini-1.5-pro",                # Lebih pintar
    "gemini-1.5-flash",              # Lebih cepat
]

def ask_ai_universal(
    prompt: str, 
    system_prompt: str = "Kamu adalah ahli coding Lua Roblox. Jawab dengan jelas dan berikan contoh kode jika perlu."
) -> str:
    """Multi-AI dengan fallback otomatis: Groq -> Gemini -> Pollinations"""
    
    # ═══════════════════════════════════════════════════════════════════
    # 1️⃣ PRIORITY 1: GROQ (Llama 3.3) - Tercepat
    # ═══════════════════════════════════════════════════════════════════
    if KEY_GROQ:
        for model in GROQ_MODELS[:2]:  # Coba 2 model pertama
            try:
                client = Groq(api_key=KEY_GROQ)
                chat = client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system_prompt}, 
                        {"role": "user", "content": prompt}
                    ],
                    model=model,
                    temperature=0.7,
                    max_tokens=4096,
                )
                logger.info(f"✅ Groq [{model}] berhasil")
                return f"⚡ **[Groq - {model}]**\n{chat.choices[0].message.content}"
            except Exception as e:
                logger.warning(f"⚠️ Groq [{model}] error: {e}")
                continue

    # ═══════════════════════════════════════════════════════════════════
    # 2️⃣ PRIORITY 2: GOOGLE GEMINI 2.0 - Terpintar
    # ═══════════════════════════════════════════════════════════════════
    if KEY_GEMINI:
        for model_name in GEMINI_MODELS:
            try:
                genai.configure(api_key=KEY_GEMINI)
                
                # Safety settings (opsional - untuk konten coding)
                safety_settings = [
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                ]
                
                model = genai.GenerativeModel(
                    model_name=model_name,
                    safety_settings=safety_settings,
                    system_instruction=system_prompt
                )
                
                response = model.generate_content(prompt)
                logger.info(f"✅ Gemini [{model_name}] berhasil")
                return f"🧠 **[Gemini - {model_name}]**\n{response.text}"
            except Exception as e:
                logger.warning(f"⚠️ Gemini [{model_name}] error: {e}")
                continue

    # ═══════════════════════════════════════════════════════════════════
    # 3️⃣ PRIORITY 3: POLLINATIONS (Gratis, Tanpa API Key)
    # ═══════════════════════════════════════════════════════════════════
    try:
        full_prompt = f"{system_prompt}\n\nUser: {prompt}"
        encoded_prompt = quote(full_prompt)
        
        # Model Pollinations 2025
        pollinations_models = ["openai", "mistral", "claude"]
        
        for pmodel in pollinations_models:
            try:
                url_poly = f"https://text.pollinations.ai/{encoded_prompt}?model={pmodel}"
                response = requests.get(url_poly, timeout=45)
                
                if response.status_code == 200 and len(response.text) > 10:
                    logger.info(f"✅ Pollinations [{pmodel}] berhasil")
                    return f"🌺 **[Pollinations - {pmodel}]**\n{response.text}"
            except Exception as e:
                logger.warning(f"⚠️ Pollinations [{pmodel}] error: {e}")
                continue
    except Exception as e:
        logger.error(f"❌ Pollinations total error: {e}")

    return "❌ **Semua AI sedang sibuk/down.** Silakan coba lagi dalam beberapa menit."


def split_message(text: str, limit: int = 1900) -> list:
    """Split pesan panjang agar tidak melebihi limit Discord"""
    if len(text) <= limit:
        return [text]
    
    chunks = []
    current_chunk = ""
    
    for line in text.split('\n'):
        if len(current_chunk) + len(line) + 1 > limit:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk += ('\n' if current_chunk else '') + line
    
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks if chunks else [text[:limit]]


# ==============================================================================
# 🛡️ SISTEM DUMPER (ScraperAPI + Header Spoofing)
# ==============================================================================
def get_executor_headers() -> dict:
    """Generate header yang meniru Roblox Executor"""
    fake_place_ids = [
        "2753915549", "155615604", "4442272183", 
        "6872265039", "189707", "920587237"
    ]
    fake_job_ids = [
        f"RBX-{random.randint(10000000, 99999999)}",
    ]
    
    return {
        "User-Agent": random.choice([
            "Roblox/WinInet",
            "RobloxStudio/WinInet",
            "Roblox/CFNetwork",
        ]),
        "Roblox-Place-Id": random.choice(fake_place_ids),
        "Roblox-Job-Id": fake_job_ids[0],
        "Accept": "application/octet-stream",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }


def validate_url(url: str) -> bool:
    """Validasi URL untuk keamanan"""
    blocked_domains = ["localhost", "127.0.0.1", "0.0.0.0", "internal"]
    
    for domain in blocked_domains:
        if domain in url.lower():
            return False
    
    return url.startswith(("http://", "https://"))


# ==============================================================================
# 📡 BOT EVENTS
# ==============================================================================
@bot.event
async def on_ready():
    logger.info(f'🔥 Bot Online: {bot.user} (ID: {bot.user.id})')
    logger.info(f'📊 Servers: {len(bot.guilds)}')
    
    # Set status bot
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="/tanya untuk bantuan AI"
        )
    )
    
    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        logger.info(f"✅ Synced {len(synced)} slash commands")
    except Exception as e:
        logger.error(f"❌ Sync error: {e}")


@bot.event
async def on_guild_join(guild):
    logger.info(f"📥 Joined: {guild.name} (ID: {guild.id})")


# ==============================================================================
# 🎮 SLASH COMMANDS
# ==============================================================================

# ──────────────────────────────────────────────────────────────────────────────
# 1️⃣ COMMAND: /dump
# ──────────────────────────────────────────────────────────────────────────────
@bot.tree.command(name="dump", description="🔓 Dump script dari URL (Junkie/Luarmor/Pastebin/dll)")
@app_commands.describe(
    url="URL script yang ingin di-dump",
    raw="Gunakan mode raw tanpa proxy (default: False)"
)
async def dump(interaction: discord.Interaction, url: str, raw: bool = False):
    await interaction.response.defer()
    
    # Validasi URL
    if not validate_url(url):
        return await interaction.followup.send("❌ **URL tidak valid atau diblokir!**")
    
    try:
        if raw or not SCRAPER_KEY:
            # Mode RAW (curl_cffi)
            res = curl_requests.get(
                url, 
                impersonate="chrome120",  # Update ke Chrome terbaru
                headers=get_executor_headers(),
                timeout=30
            )
            content = res.text
            method = "Raw (curl_cffi)"
        else:
            # Mode ScraperAPI
            payload = {
                'api_key': SCRAPER_KEY,
                'url': url,
                'keep_headers': 'true',
                'render': 'false',
                'country_code': 'us',
            }
            
            response = requests.get(
                'http://api.scraperapi.com',
                params=payload,
                headers=get_executor_headers(),
                timeout=90
            )
            content = response.text
            method = "ScraperAPI"

        # Deteksi tipe konten
        file_ext = "lua"
        status_emoji = "✅"
        msg = f"**Dump Berhasil!** (via {method})"
        
        if "<!DOCTYPE html>" in content[:500] or "<html" in content[:100]:
            file_ext = "html"
            status_emoji = "⚠️"
            msg = f"**Peringatan:** Target mengirim HTML (via {method})"
        elif content.strip().startswith("{") or content.strip().startswith("["):
            file_ext = "json"
        
        # Kirim file
        file_data = io.BytesIO(content.encode("utf-8"))
        
        embed = discord.Embed(
            title=f"{status_emoji} Dump Result",
            color=discord.Color.green() if file_ext == "lua" else discord.Color.yellow()
        )
        embed.add_field(name="📎 URL", value=f"`{url[:50]}...`" if len(url) > 50 else f"`{url}`", inline=False)
        embed.add_field(name="📦 Size", value=f"`{len(content):,} bytes`", inline=True)
        embed.add_field(name="📄 Type", value=f"`.{file_ext}`", inline=True)
        embed.add_field(name="🔧 Method", value=method, inline=True)
        embed.set_footer(text=f"Requested by {interaction.user}")
        
        await interaction.followup.send(
            embed=embed,
            file=discord.File(file_data, filename=f"dumped_{random.randint(1000,9999)}.{file_ext}")
        )
        
    except requests.exceptions.Timeout:
        await interaction.followup.send("⏱️ **Timeout!** Server tidak merespons dalam 90 detik.")
    except Exception as e:
        logger.error(f"Dump error: {e}")
        await interaction.followup.send(f"💀 **Error:** `{str(e)[:200]}`")


# ──────────────────────────────────────────────────────────────────────────────
# 2️⃣ COMMAND: /tanya
# ──────────────────────────────────────────────────────────────────────────────
@bot.tree.command(name="tanya", description="🤖 Tanya AI tentang coding (Lua, Python, dll)")
@app_commands.describe(
    pertanyaan="Pertanyaan kamu",
    mode="Pilih jenis jawaban"
)
@app_commands.choices(mode=[
    app_commands.Choice(name="🎮 Roblox/Lua", value="roblox"),
    app_commands.Choice(name="🐍 Python", value="python"),
    app_commands.Choice(name="🌐 Web Dev", value="web"),
    app_commands.Choice(name="💬 General", value="general"),
])
async def tanya(
    interaction: discord.Interaction, 
    pertanyaan: str, 
    mode: str = "general"
):
    await interaction.response.defer()
    
    # System prompt berdasarkan mode
    system_prompts = {
        "roblox": "Kamu adalah ahli Roblox Studio dan Lua scripting. Jawab dalam Bahasa Indonesia dengan contoh kode yang jelas.",
        "python": "Kamu adalah ahli Python programming. Jawab dalam Bahasa Indonesia dengan contoh kode yang jelas dan best practices.",
        "web": "Kamu adalah ahli Web Development (HTML, CSS, JavaScript, React, dll). Jawab dalam Bahasa Indonesia.",
        "general": "Kamu adalah asisten AI yang helpful. Jawab dalam Bahasa Indonesia dengan jelas dan ringkas.",
    }
    
    mode_icons = {
        "roblox": "🎮",
        "python": "🐍", 
        "web": "🌐",
        "general": "💬"
    }
    
    jawaban = ask_ai_universal(pertanyaan, system_prompts.get(mode, system_prompts["general"]))
    chunks = split_message(jawaban)
    
    # Kirim jawaban
    embed = discord.Embed(
        title=f"{mode_icons.get(mode, '🤖')} Pertanyaan",
        description=pertanyaan,
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Asked by {interaction.user}")
    
    await interaction.followup.send(embed=embed, content=chunks[0])
    
    for chunk in chunks[1:]:
        await interaction.channel.send(chunk)


# ──────────────────────────────────────────────────────────────────────────────
# 3️⃣ COMMAND: /explain
# ──────────────────────────────────────────────────────────────────────────────
@bot.tree.command(name="explain", description="🔍 AI akan menganalisis script dari URL")
@app_commands.describe(
    url="URL script yang ingin dianalisis",
    detail="Level detail analisis"
)
@app_commands.choices(detail=[
    app_commands.Choice(name="📝 Ringkas", value="short"),
    app_commands.Choice(name="📋 Detail", value="detail"),
    app_commands.Choice(name="🛡️ Security Audit", value="security"),
])
async def explain(
    interaction: discord.Interaction, 
    url: str, 
    detail: str = "short"
):
    await interaction.response.defer()
    
    if not validate_url(url):
        return await interaction.followup.send("❌ **URL tidak valid!**")
    
    try:
        # Download script
        res = curl_requests.get(
            url, 
            impersonate="chrome120", 
            timeout=15,
            headers={"Accept": "text/plain, */*"}
        )
        
        # Limit karakter berdasarkan detail level
        char_limits = {"short": 4000, "detail": 8000, "security": 6000}
        script_content = res.text[:char_limits.get(detail, 4000)]
        
        # System prompt berdasarkan mode
        prompts = {
            "short": "Jelaskan script ini secara SINGKAT dalam Bahasa Indonesia. Apa fungsinya? Max 3 paragraf.",
            "detail": "Analisa script ini secara DETAIL dalam Bahasa Indonesia. Jelaskan setiap fungsi utama dan alur kerjanya.",
            "security": "Kamu adalah Security Analyst. Analisa script ini untuk: 1) Backdoor/Malware 2) Data stealing 3) Remote execution 4) Obfuscation berbahaya. Berikan rating keamanan 1-10.",
        }
        
        prompt = f"{prompts[detail]}\n\n```lua\n{script_content}\n```"
        jawaban = ask_ai_universal(prompt, system_prompt="Kamu adalah Script Analyst profesional.")
        
        chunks = split_message(jawaban)
        
        # Embed
        detail_icons = {"short": "📝", "detail": "📋", "security": "🛡️"}
        embed = discord.Embed(
            title=f"{detail_icons.get(detail, '🔍')} Script Analysis",
            color=discord.Color.purple()
        )
        embed.add_field(name="🔗 URL", value=f"`{url[:60]}...`" if len(url) > 60 else f"`{url}`", inline=False)
        embed.add_field(name="📊 Script Size", value=f"`{len(res.text):,} chars`", inline=True)
        embed.add_field(name="🔬 Mode", value=detail.title(), inline=True)
        
        await interaction.followup.send(embed=embed, content=chunks[0])
        
        for chunk in chunks[1:]:
            await interaction.channel.send(chunk)
            
    except Exception as e:
        logger.error(f"Explain error: {e}")
        await interaction.followup.send(f"❌ **Gagal menganalisa:** `{str(e)[:200]}`")


# ──────────────────────────────────────────────────────────────────────────────
# 4️⃣ COMMAND: /ping
# ──────────────────────────────────────────────────────────────────────────────
@bot.tree.command(name="ping", description="🏓 Cek latency bot")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    
    if latency < 100:
        status = "🟢 Excellent"
    elif latency < 200:
        status = "🟡 Good"
    else:
        status = "🔴 High"
    
    embed = discord.Embed(
        title="🏓 Pong!",
        color=discord.Color.green()
    )
    embed.add_field(name="Latency", value=f"`{latency}ms`", inline=True)
    embed.add_field(name="Status", value=status, inline=True)
    
    await interaction.response.send_message(embed=embed)


# ──────────────────────────────────────────────────────────────────────────────
# 5️⃣ COMMAND: /help
# ──────────────────────────────────────────────────────────────────────────────
@bot.tree.command(name="help", description="📚 Lihat semua command yang tersedia")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📚 Daftar Commands",
        description="Bot AI Multi-Purpose untuk Roblox Development",
        color=discord.Color.gold()
    )
    
    commands_info = [
        ("🔓 /dump `<url>` `[raw]`", "Dump script dari URL apapun"),
        ("🤖 /tanya `<pertanyaan>` `[mode]`", "Tanya AI tentang coding"),
        ("🔍 /explain `<url>` `[detail]`", "Analisis script dari URL"),
        ("🏓 /ping", "Cek latency bot"),
        ("📚 /help", "Tampilkan bantuan ini"),
    ]
    
    for name, desc in commands_info:
        embed.add_field(name=name, value=desc, inline=False)
    
    embed.add_field(
        name="🧠 AI Models (2025)",
        value="• Groq: Llama 3.3 70B\n• Google: Gemini 2.0 Flash\n• Fallback: Pollinations",
        inline=False
    )
    
    embed.set_footer(text="Made with ❤️ | Update 2025")
    
    await interaction.response.send_message(embed=embed)


# ==============================================================================
# 🚀 START BOT
# ==============================================================================
if __name__ == "__main__":
    keep_alive()
    
    logger.info("🚀 Starting bot...")
    logger.info(f"📦 Groq API: {'✅' if KEY_GROQ else '❌'}")
    logger.info(f"📦 Gemini API: {'✅' if KEY_GEMINI else '❌'}")
    logger.info(f"📦 Scraper API: {'✅' if SCRAPER_KEY else '❌'}")
    
    try:
        bot.run(DISCORD_TOKEN, log_handler=None)
    except discord.LoginFailure:
        logger.critical("❌ Token Discord tidak valid!")
    except Exception as e:
        logger.critical(f"❌ Fatal error: {e}")
