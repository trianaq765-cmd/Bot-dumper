import discord
import os
import io
import re
import time
import json
import logging
import sqlite3
import random
import threading
from collections import defaultdict
from dataclasses import dataclass
from discord.ext import commands

try:
    from keep_alive import keep_alive
except:
    keep_alive = lambda: None

logging.basicConfig(level=logging.INFO, format='%(asctime)s|%(levelname)s|%(message)s')
logger = logging.getLogger(__name__)

# ============ ENVIRONMENT VARIABLES ============
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
KEY_GROQ = os.getenv("GROQ_API_KEY")
KEY_OPENROUTER = os.getenv("OPENROUTER_API_KEY")
KEY_CEREBRAS = os.getenv("CEREBRAS_API_KEY")
KEY_SAMBANOVA = os.getenv("SAMBANOVA_API_KEY")
KEY_COHERE = os.getenv("COHERE_API_KEY")
CF_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
CF_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
KEY_TOGETHER = os.getenv("TOGETHER_API_KEY")
OWNER_IDS = [int(x) for x in os.getenv("OWNER_IDS", "0").split(",") if x.isdigit()]
PREFIX = os.getenv("BOT_PREFIX", ".")

if not DISCORD_TOKEN:
    print("❌ DISCORD_TOKEN not found!")
    exit(1)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# ============ LAZY IMPORTS ============
_groq = _requests = _curl = None

def get_groq():
    global _groq
    if _groq is None and KEY_GROQ:
        from groq import Groq
        _groq = Groq(api_key=KEY_GROQ)
    return _groq

def get_requests():
    global _requests
    if _requests is None:
        import requests
        _requests = requests
    return _requests

def get_curl():
    global _curl
    if _curl is None:
        from curl_cffi import requests as r
        _curl = r
    return _curl

# ============ DATABASE ============
class Database:
    def __init__(self, path="bot.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS user_prefs(uid INTEGER PRIMARY KEY, model TEXT DEFAULT "auto");
            CREATE TABLE IF NOT EXISTS stats(id INTEGER PRIMARY KEY, cmd TEXT, uid INTEGER, ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS blacklist(uid INTEGER PRIMARY KEY);
        ''')
    
    def get_model(self, uid):
        with self.lock:
            r = self.conn.execute('SELECT model FROM user_prefs WHERE uid=?', (uid,)).fetchone()
            return r[0] if r else "auto"
    
    def set_model(self, uid, model):
        with self.lock:
            self.conn.execute('INSERT OR REPLACE INTO user_prefs VALUES(?,?)', (uid, model))
            self.conn.commit()
    
    def stat(self, cmd, uid):
        with self.lock:
            self.conn.execute('INSERT INTO stats(cmd,uid) VALUES(?,?)', (cmd, uid))
            self.conn.commit()
    
    def banned(self, uid):
        with self.lock:
            return self.conn.execute('SELECT 1 FROM blacklist WHERE uid=?', (uid,)).fetchone() is not None
    
    def add_blacklist(self, uid):
        with self.lock:
            self.conn.execute('INSERT OR IGNORE INTO blacklist VALUES(?)', (uid,))
            self.conn.commit()
    
    def remove_blacklist(self, uid):
        with self.lock:
            self.conn.execute('DELETE FROM blacklist WHERE uid=?', (uid,))
            self.conn.commit()

db = Database()

# ============ RATE LIMITER ============
class RateLimiter:
    def __init__(self):
        self.cd = defaultdict(lambda: defaultdict(float))
        self.lock = threading.Lock()
    
    def check(self, uid, cmd, t=5):
        with self.lock:
            now = time.time()
            if now - self.cd[uid][cmd] < t:
                return False, t - (now - self.cd[uid][cmd])
            self.cd[uid][cmd] = now
            return True, 0

rl = RateLimiter()

# ============ MEMORY ============
@dataclass
class Msg:
    role: str
    content: str
    ts: float

class Memory:
    def __init__(self):
        self.data = defaultdict(list)
        self.lock = threading.Lock()
    
    def add(self, uid, role, content):
        with self.lock:
            now = time.time()
            self.data[uid] = [m for m in self.data[uid] if now - m.ts < 1800]
            self.data[uid].append(Msg(role, content[:1500], now))
            if len(self.data[uid]) > 15:
                self.data[uid] = self.data[uid][-15:]
    
    def get(self, uid):
        with self.lock:
            now = time.time()
            self.data[uid] = [m for m in self.data[uid] if now - m.ts < 1800]
            return [{"role": m.role, "content": m.content} for m in self.data[uid]]
    
    def clear(self, uid):
        with self.lock:
            self.data[uid] = []

mem = Memory()

# ============ SYSTEM PROMPT ============
SYSTEM_PROMPT = '''Kamu adalah AI Assistant yang helpful dan friendly. 
Kamu membantu user dengan berbagai pertanyaan dan tugas.
Jawab dalam Bahasa Indonesia kecuali diminta bahasa lain.
Berikan jawaban yang jelas, informatif, dan mudah dipahami.'''

# ============ MODEL CONFIGURATIONS (Updated 2026) ============
OR_MODELS = {
    "llama": "meta-llama/llama-4-scout:free",
    "gemini": "google/gemini-2.5-flash:free",
    "qwen": "qwen/qwen3-235b-a22b:free",
    "deepseek": "deepseek/deepseek-r1:free",
    "mistral": "mistralai/mistral-small-3.1-24b-instruct:free"
}

CF_MODELS = {
    "llama": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "qwen": "@cf/qwen/qwen2.5-coder-32b-instruct"
}

MODEL_NAMES = {
    "auto": "🚀 Auto (Recommended)",
    "groq": "⚡ Groq (Fast)",
    "cerebras": "🧠 Cerebras",
    "cloudflare": "☁️ Cloudflare",
    "sambanova": "🦣 SambaNova",
    "cohere": "🔷 Cohere",
    "together": "🤝 Together AI",
    "pollinations": "🌸 Pollinations (Free)",
    "or_llama": "🦙 OR Llama-4",
    "or_gemini": "🔵 OR Gemini-2.5",
    "or_qwen": "🟣 OR Qwen3",
    "or_deepseek": "🌊 OR DeepSeek-R1"
}

UA_LIST = ["Roblox/WinInet", "Synapse-X/2.0", "Sentinel/3.0", "Krnl/1.0", "Fluxus/1.0", "ScriptWare/2.0"]

# ============ AI PROVIDERS ============

def call_groq(msgs):
    """Call Groq API"""
    cl = get_groq()
    if not cl:
        logger.warning("Groq: No API key")
        return None
    try:
        r = cl.chat.completions.create(
            messages=msgs,
            model="llama-3.3-70b-versatile",
            temperature=0.7,
            max_tokens=2000
        )
        result = r.choices[0].message.content
        logger.info(f"Groq: Success ({len(result)} chars)")
        return result
    except Exception as e:
        logger.error(f"Groq: {e}")
        return None

def call_cerebras(msgs):
    """Call Cerebras API"""
    if not KEY_CEREBRAS:
        return None
    try:
        r = get_requests().post(
            "https://api.cerebras.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {KEY_CEREBRAS}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.3-70b",
                "messages": msgs,
                "temperature": 0.7,
                "max_tokens": 2000
            },
            timeout=30
        )
        if r.status_code == 200:
            result = r.json()["choices"][0]["message"]["content"]
            logger.info(f"Cerebras: Success")
            return result
        logger.error(f"Cerebras: {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"Cerebras: {e}")
        return None

def call_cloudflare(msgs):
    """Call Cloudflare Workers AI"""
    if not CF_ACCOUNT_ID or not CF_API_TOKEN:
        return None
    try:
        model = CF_MODELS["llama"]
        url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{model}"
        r = get_requests().post(
            url,
            headers={
                "Authorization": f"Bearer {CF_API_TOKEN}",
                "Content-Type": "application/json"
            },
            json={"messages": msgs, "max_tokens": 2000},
            timeout=60
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("success") and "result" in data:
                response = data["result"].get("response", "")
                if response and response.strip():
                    logger.info("Cloudflare: Success")
                    return response.strip()
        logger.error(f"Cloudflare: {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"Cloudflare: {e}")
        return None

def call_openrouter(msgs, mk="llama"):
    """Call OpenRouter API"""
    if not KEY_OPENROUTER:
        return None
    try:
        mid = OR_MODELS.get(mk, OR_MODELS["llama"])
        r = get_requests().post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {KEY_OPENROUTER}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com",
                "X-Title": "Discord Bot"
            },
            json={
                "model": mid,
                "messages": msgs,
                "temperature": 0.7,
                "max_tokens": 2000
            },
            timeout=60
        )
        if r.status_code == 200:
            data = r.json()
            if "choices" in data and data["choices"]:
                result = data["choices"][0]["message"]["content"]
                logger.info(f"OpenRouter {mk}: Success")
                return result
        logger.error(f"OpenRouter {mk}: {r.status_code} - {r.text[:100]}")
        return None
    except Exception as e:
        logger.error(f"OpenRouter: {e}")
        return None

def call_sambanova(msgs):
    """Call SambaNova API"""
    if not KEY_SAMBANOVA:
        return None
    try:
        r = get_requests().post(
            "https://api.sambanova.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {KEY_SAMBANOVA}",
                "Content-Type": "application/json"
            },
            json={
                "model": "Meta-Llama-3.3-70B-Instruct",
                "messages": msgs,
                "temperature": 0.7,
                "max_tokens": 2000
            },
            timeout=60
        )
        if r.status_code == 200:
            result = r.json()["choices"][0]["message"]["content"]
            logger.info("SambaNova: Success")
            return result
        logger.error(f"SambaNova: {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"SambaNova: {e}")
        return None

def call_cohere(msgs):
    """Call Cohere API"""
    if not KEY_COHERE:
        return None
    try:
        preamble = ""
        hist = []
        messages = []
        for m in msgs:
            if m["role"] == "system":
                preamble = m["content"]
            else:
                messages.append(m)
        for m in messages[:-1]:
            role = "USER" if m["role"] == "user" else "CHATBOT"
            hist.append({"role": role, "message": m["content"]})
        user_msg = messages[-1]["content"] if messages else ""
        payload = {"model": "command-r-plus", "message": user_msg, "temperature": 0.7}
        if preamble:
            payload["preamble"] = preamble
        if hist:
            payload["chat_history"] = hist
        r = get_requests().post(
            "https://api.cohere.com/v2/chat",
            headers={
                "Authorization": f"Bearer {KEY_COHERE}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=60
        )
        if r.status_code == 200:
            result = r.json().get("text", "")
            logger.info("Cohere: Success")
            return result
        logger.error(f"Cohere: {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"Cohere: {e}")
        return None

def call_together(msgs):
    """Call Together AI"""
    if not KEY_TOGETHER:
        return None
    try:
        r = get_requests().post(
            "https://api.together.xyz/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {KEY_TOGETHER}",
                "Content-Type": "application/json"
            },
            json={
                "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
                "messages": msgs,
                "temperature": 0.7,
                "max_tokens": 2000
            },
            timeout=60
        )
        if r.status_code == 200:
            result = r.json()["choices"][0]["message"]["content"]
            logger.info("Together: Success")
            return result
        logger.error(f"Together: {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"Together: {e}")
        return None

def call_pollinations(prompt):
    """Call Pollinations AI (FREE - No API Key needed!)"""
    try:
        # Pollinations text API
        r = get_requests().get(
            f"https://text.pollinations.ai/{prompt}",
            headers={"Accept": "text/plain"},
            timeout=60
        )
        if r.status_code == 200 and r.text.strip():
            logger.info("Pollinations: Success")
            return r.text.strip()
        logger.error(f"Pollinations: {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"Pollinations: {e}")
        return None

def call_blackbox(msgs):
    """Call Blackbox AI (FREE)"""
    try:
        # Extract last user message
        user_msg = ""
        for m in reversed(msgs):
            if m["role"] == "user":
                user_msg = m["content"]
                break
        
        r = get_requests().post(
            "https://api.blackbox.ai/api/chat",
            headers={"Content-Type": "application/json"},
            json={
                "messages": msgs,
                "model": "blackboxai",
                "max_tokens": 2000
            },
            timeout=60
        )
        if r.status_code == 200:
            result = r.text.strip()
            if result:
                logger.info("Blackbox: Success")
                return result
        logger.error(f"Blackbox: {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"Blackbox: {e}")
        return None

# ============ AI ROUTER ============

def call_ai(model, msgs, prompt=""):
    """Route to specific AI provider"""
    if model == "groq":
        return call_groq(msgs), "Groq"
    elif model == "cerebras":
        return call_cerebras(msgs), "Cerebras"
    elif model == "cloudflare":
        return call_cloudflare(msgs), "Cloudflare"
    elif model == "sambanova":
        return call_sambanova(msgs), "SambaNova"
    elif model == "cohere":
        return call_cohere(msgs), "Cohere"
    elif model == "together":
        return call_together(msgs), "Together"
    elif model == "pollinations":
        return call_pollinations(prompt), "Pollinations"
    elif model.startswith("or_"):
        mk = model[3:]
        return call_openrouter(msgs, mk), f"OR-{mk.title()}"
    return None, "none"

def ask_ai(prompt, uid=None, model=None):
    """Main AI function with fallback"""
    # Get user's preferred model
    user_model = db.get_model(uid) if uid else "auto"
    
    # Use specified model or user's preference
    if model and model != "auto":
        selected_model = model
    elif user_model != "auto":
        selected_model = user_model
    else:
        selected_model = "auto"
    
    # Build messages
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    if uid:
        h = mem.get(uid)
        if h:
            msgs.extend(h[-6:])
    msgs.append({"role": "user", "content": prompt})
    
    result = None
    used = "none"
    
    if selected_model != "auto":
        # Try selected model first
        result, used = call_ai(selected_model, msgs, prompt)
        
        # Fallback if failed
        if not result:
            logger.info(f"Model {selected_model} failed, trying fallbacks...")
            fallbacks = [
                (lambda: call_groq(msgs), "Groq"),
                (lambda: call_cerebras(msgs), "Cerebras"),
                (lambda: call_cloudflare(msgs), "Cloudflare"),
                (lambda: call_pollinations(prompt), "Pollinations"),
                (lambda: call_openrouter(msgs, "llama"), "OR-Llama")
            ]
            for fn, nm in fallbacks:
                try:
                    result = fn()
                    if result:
                        used = f"{nm}(fb)"
                        break
                except Exception as e:
                    logger.error(f"Fallback {nm}: {e}")
                    continue
    else:
        # Auto mode - try all providers
        providers = [
            (lambda: call_groq(msgs), "Groq"),
            (lambda: call_cerebras(msgs), "Cerebras"),
            (lambda: call_cloudflare(msgs), "Cloudflare"),
            (lambda: call_openrouter(msgs, "llama"), "OR-Llama"),
            (lambda: call_sambanova(msgs), "SambaNova"),
            (lambda: call_pollinations(prompt), "Pollinations"),
            (lambda: call_cohere(msgs), "Cohere")
        ]
        for fn, nm in providers:
            try:
                result = fn()
                if result:
                    used = nm
                    break
            except Exception as e:
                logger.error(f"Auto {nm}: {e}")
                continue
    
    if not result:
        return "❌ Semua AI provider tidak tersedia saat ini. Coba lagi nanti.", "none"
    
    # Save to memory
    if uid:
        mem.add(uid, "user", prompt[:500])
        mem.add(uid, "assistant", result[:500])
    
    return result, used

# ============ HELPERS ============

def split_msg(text, limit=1900):
    """Split long messages"""
    if not text or not str(text).strip():
        return ["(kosong)"]
    text = str(text).strip()[:3800]
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        idx = text.rfind('\n', 0, limit)
        if idx <= 0:
            idx = text.rfind(' ', 0, limit)
        if idx <= 0:
            idx = limit
        chunk = text[:idx].strip()
        if chunk:
            chunks.append(chunk)
        text = text[idx:].lstrip()
    return chunks if chunks else ["(kosong)"]

async def safe_send(ctx, content, used, is_reply=True):
    """Safe send with error handling"""
    try:
        if not content or not content.strip():
            content = "(Response kosong dari AI)"
        
        chunks = split_msg(content)
        first = chunks[0] if chunks else "(kosong)"
        
        embed = discord.Embed(color=0x5865F2)
        embed.set_footer(text=f"🤖 {used}")
        
        if is_reply:
            try:
                await ctx.reply(content=first, embed=embed if len(chunks) == 1 else None, mention_author=False)
            except discord.NotFound:
                await ctx.channel.send(content=first, embed=embed if len(chunks) == 1 else None)
            
            for c in chunks[1:]:
                if c.strip():
                    await ctx.channel.send(c)
        else:
            await ctx.send(content=first, embed=embed if len(chunks) == 1 else None)
            for c in chunks[1:]:
                if c.strip():
                    await ctx.send(c)
        
        return True
    
    except discord.NotFound:
        logger.warning("Message was deleted")
        return False
    except discord.HTTPException as e:
        logger.error(f"Discord HTTP: {e}")
        try:
            await ctx.channel.send(f"❌ Error: {str(e)[:100]}")
        except:
            pass
        return False
    except Exception as e:
        logger.error(f"Send error: {e}")
        return False

# ============ ERROR HANDLER ============

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors"""
    if isinstance(error, commands.CommandNotFound):
        # Ignore unknown commands
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply(f"❌ Argumen kurang! Gunakan `{PREFIX}help` untuk bantuan.", mention_author=False)
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.reply(f"⏳ Tunggu {error.retry_after:.0f} detik", mention_author=False)
    else:
        logger.error(f"Command error: {error}")
        try:
            await ctx.reply(f"❌ Error: {str(error)[:100]}", mention_author=False)
        except:
            pass

# ============ BOT EVENTS ============

@bot.event
async def on_ready():
    logger.info(f'🔥 {bot.user} online | {len(bot.guilds)} servers')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=f"{PREFIX}help"))
    logger.info(f"✅ Bot ready with prefix: {PREFIX}")

@bot.event
async def on_message(msg):
    if msg.author.bot:
        return
    
    # Handle mention
    if bot.user.mentioned_in(msg) and not msg.mention_everyone:
        content = msg.content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '').strip()
        
        if content:
            if db.banned(msg.author.id):
                return await msg.reply("🚫 Kamu diblokir.", mention_author=False)
            
            ok, rem = rl.check(msg.author.id, "mention", 5)
            if not ok:
                return await msg.reply(f"⏳ Tunggu {rem:.0f}s", mention_author=False)
            
            async with msg.channel.typing():
                try:
                    result, used = ask_ai(content, msg.author.id)
                    await safe_send(msg, result, used, True)
                    db.stat("ai", msg.author.id)
                except Exception as e:
                    logger.error(f"Mention error: {e}")
                    await msg.reply("❌ Error terjadi.", mention_author=False)
        else:
            m = db.get_model(msg.author.id)
            await msg.reply(
                f"👋 Hai! Saya AI Assistant.\n"
                f"🤖 Model: **{MODEL_NAMES.get(m, m)}**\n\n"
                f"Ketik pertanyaan setelah mention atau gunakan `{PREFIX}ai`",
                mention_author=False
            )
        return
    
    await bot.process_commands(msg)

# ============ COMMANDS ============

@bot.command(name="ai", aliases=["ask", "chat", "tanya", "a"])
async def cmd_ai(ctx, *, prompt: str = None):
    """Chat dengan AI"""
    if db.banned(ctx.author.id):
        return await ctx.reply("🚫 Kamu diblokir.", mention_author=False)
    
    ok, rem = rl.check(ctx.author.id, "ai", 5)
    if not ok:
        return await ctx.reply(f"⏳ Tunggu {rem:.0f}s", mention_author=False)
    
    if not prompt:
        return await ctx.reply(
            f"❌ Cara pakai: `{PREFIX}ai <pertanyaan>`\n"
            f"Contoh: `{PREFIX}ai apa itu machine learning?`",
            mention_author=False
        )
    
    async with ctx.typing():
        try:
            result, used = ask_ai(prompt, ctx.author.id)
            await safe_send(ctx.message, result, used, True)
            db.stat("ai", ctx.author.id)
        except Exception as e:
            logger.error(f"AI error: {e}")
            await ctx.reply("❌ Error terjadi saat memproses.", mention_author=False)

@bot.command(name="model", aliases=["m", "setmodel", "models"])
async def cmd_model(ctx, *, model: str = None):
    """Lihat atau ganti model AI"""
    valid = list(MODEL_NAMES.keys())
    
    if not model:
        cur = db.get_model(ctx.author.id)
        e = discord.Embed(title="🤖 Model AI", color=0x3498DB)
        e.add_field(name="Model Kamu Saat Ini", value=f"**{MODEL_NAMES.get(cur, cur)}**", inline=False)
        
        model_list = "\n".join([f"`{k}` → {v}" for k, v in MODEL_NAMES.items()])
        e.add_field(name="Model Tersedia", value=model_list, inline=False)
        e.add_field(name="Cara Ganti", value=f"`{PREFIX}model <nama>`\nContoh: `{PREFIX}model groq`", inline=False)
        e.set_footer(text="Model akan digunakan konsisten sampai kamu ganti")
        return await ctx.reply(embed=e, mention_author=False)
    
    model = model.lower().strip()
    if model not in valid:
        return await ctx.reply(
            f"❌ Model `{model}` tidak valid!\n\n"
            f"Pilihan: `{', '.join(valid)}`",
            mention_author=False
        )
    
    db.set_model(ctx.author.id, model)
    await ctx.reply(f"✅ Model diubah ke: **{MODEL_NAMES.get(model, model)}**", mention_author=False)

@bot.command(name="clear", aliases=["reset", "forget", "clr"])
async def cmd_clear(ctx):
    """Hapus memory chat"""
    mem.clear(ctx.author.id)
    await ctx.reply("🧹 Memory percakapan dihapus!", mention_author=False)

@bot.command(name="ping", aliases=["p", "status"])
async def cmd_ping(ctx):
    """Cek status bot"""
    m = db.get_model(ctx.author.id)
    mem_count = len(mem.get(ctx.author.id))
    
    e = discord.Embed(title="🏓 Pong!", color=0x00FF00)
    e.add_field(name="Latency", value=f"`{round(bot.latency * 1000)}ms`")
    e.add_field(name="Model", value=f"`{MODEL_NAMES.get(m, m)}`")
    e.add_field(name="Memory", value=f"`{mem_count} msg`")
    e.add_field(name="Servers", value=f"`{len(bot.guilds)}`")
    e.add_field(name="Prefix", value=f"`{PREFIX}`")
    await ctx.reply(embed=e, mention_author=False)

@bot.command(name="help", aliases=["h", "bantuan", "?"])
async def cmd_help(ctx):
    """Tampilkan bantuan"""
    m = db.get_model(ctx.author.id)
    
    e = discord.Embed(
        title="📚 AI Bot - Bantuan",
        description=f"Model kamu: **{MODEL_NAMES.get(m, m)}**",
        color=0x5865F2
    )
    e.add_field(
        name="🤖 Chat AI",
        value=(
            f"`{PREFIX}ai <teks>` - Tanya AI\n"
            f"`@{bot.user.name} <teks>` - Via mention"
        ),
        inline=False
    )
    e.add_field(
        name="⚙️ Pengaturan",
        value=(
            f"`{PREFIX}model` - Lihat model tersedia\n"
            f"`{PREFIX}model <nama>` - Ganti model\n"
            f"`{PREFIX}clear` - Hapus memory chat"
        ),
        inline=False
    )
    e.add_field(
        name="🔧 Tools",
        value=(
            f"`{PREFIX}dump <url>` - Download script\n"
            f"`{PREFIX}ping` - Status bot\n"
            f"`{PREFIX}testai` - Test AI providers"
        ),
        inline=False
    )
    e.set_footer(text=f"Prefix: {PREFIX}")
    await ctx.reply(embed=e, mention_author=False)

@bot.command(name="dump", aliases=["script", "dl", "download"])
async def cmd_dump(ctx, url: str = None):
    """Download Roblox script"""
    if not url:
        return await ctx.reply(
            f"❌ Cara pakai: `{PREFIX}dump <url>`\n"
            f"Contoh: `{PREFIX}dump https://example.com/script`",
            mention_author=False
        )
    
    ok, rem = rl.check(ctx.author.id, "dump", 8)
    if not ok:
        return await ctx.reply(f"⏳ Tunggu {rem:.0f}s", mention_author=False)
    
    async with ctx.typing():
        try:
            curl = get_curl()
            ua = random.choice(UA_LIST)
            
            headers = {
                "User-Agent": ua,
                "Roblox-Place-Id": "2753915549",
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9"
            }
            
            resp = curl.get(url, impersonate="chrome120", headers=headers, timeout=20)
            content = resp.text
            
            if len(content) > 1024 * 1024:
                content = content[:1024 * 1024]
            
            ext = "lua"
            color = 0x00FF00
            if "<!DOCTYPE" in content[:300] or "<html" in content[:300].lower():
                ext = "html"
                color = 0xFFFF00
            elif content.strip().startswith("{") or content.strip().startswith("["):
                ext = "json"
                color = 0x3498DB
            
            e = discord.Embed(title="🔓 Dump Result", color=color)
            e.add_field(name="📦 Size", value=f"`{len(content):,} bytes`", inline=True)
            e.add_field(name="📄 Type", value=f"`.{ext}`", inline=True)
            e.add_field(name="🌐 UA", value=f"`{ua[:15]}...`", inline=True)
            
            db.stat("dump", ctx.author.id)
            
            file = discord.File(io.BytesIO(content.encode('utf-8', errors='ignore')), filename=f"dump.{ext}")
            await ctx.reply(embed=e, file=file, mention_author=False)
        
        except Exception as e:
            await ctx.reply(f"❌ Error: `{str(e)[:100]}`", mention_author=False)

@bot.command(name="testai", aliases=["test", "check"])
async def cmd_testai(ctx):
    """Test semua AI providers"""
    if ctx.author.id not in OWNER_IDS:
        return await ctx.reply("❌ Owner only!", mention_author=False)
    
    await ctx.reply("🔄 Testing semua AI providers...", mention_author=False)
    
    async with ctx.typing():
        results = []
        test = [{"role": "user", "content": "Say: OK"}]
        
        tests = [
            ("Groq", lambda: call_groq(test)),
            ("Cerebras", lambda: call_cerebras(test)),
            ("Cloudflare", lambda: call_cloudflare(test)),
            ("SambaNova", lambda: call_sambanova(test)),
            ("Together", lambda: call_together(test)),
            ("OR-Llama", lambda: call_openrouter(test, "llama")),
            ("OR-Gemini", lambda: call_openrouter(test, "gemini")),
            ("OR-Qwen", lambda: call_openrouter(test, "qwen")),
            ("OR-DeepSeek", lambda: call_openrouter(test, "deepseek")),
            ("Cohere", lambda: call_cohere(test)),
            ("Pollinations", lambda: call_pollinations("Say OK")),
        ]
        
        for name, fn in tests:
            try:
                r = fn()
                if r:
                    preview = r[:20].replace('\n', ' ').strip()
                    results.append(f"✅ **{name}**: `{preview}...`")
                else:
                    results.append(f"❌ **{name}**: No response")
            except Exception as ex:
                results.append(f"❌ **{name}**: `{str(ex)[:25]}`")
        
        e = discord.Embed(title="🔧 AI Provider Test", description="\n".join(results), color=0x3498DB)
        await ctx.reply(embed=e, mention_author=False)

@bot.command(name="blacklist", aliases=["ban", "block"])
async def cmd_blacklist(ctx, action: str = None, user: discord.User = None):
    """Kelola blacklist"""
    if ctx.author.id not in OWNER_IDS:
        return await ctx.reply("❌ Owner only!", mention_author=False)
    
    if not action or not user:
        return await ctx.reply(f"❌ Gunakan: `{PREFIX}blacklist <add/remove> <@user>`", mention_author=False)
    
    if action.lower() in ["add", "ban"]:
        db.add_blacklist(user.id)
        await ctx.reply(f"✅ {user.mention} ditambahkan ke blacklist.", mention_author=False)
    elif action.lower() in ["remove", "unban"]:
        db.remove_blacklist(user.id)
        await ctx.reply(f"✅ {user.mention} dihapus dari blacklist.", mention_author=False)

@bot.command(name="reload", aliases=["sync"])
async def cmd_reload(ctx):
    """Reload bot"""
    if ctx.author.id not in OWNER_IDS:
        return
    await ctx.reply("✅ Bot is running!", mention_author=False)

# ============ MAIN ============

if __name__ == "__main__":
    keep_alive()
    
    print("=" * 50)
    print("🚀 AI Bot Starting...")
    print("=" * 50)
    print(f"📦 Prefix: {PREFIX}")
    print(f"👑 Owners: {OWNER_IDS}")
    print()
    print("🔑 API Keys Status:")
    print(f"   Groq:        {'✅' if KEY_GROQ else '❌'}")
    print(f"   Cerebras:    {'✅' if KEY_CEREBRAS else '❌'}")
    print(f"   Cloudflare:  {'✅' if CF_ACCOUNT_ID and CF_API_TOKEN else '❌'}")
    print(f"   OpenRouter:  {'✅' if KEY_OPENROUTER else '❌'}")
    print(f"   SambaNova:   {'✅' if KEY_SAMBANOVA else '❌'}")
    print(f"   Cohere:      {'✅' if KEY_COHERE else '❌'}")
    print(f"   Together:    {'✅' if KEY_TOGETHER else '❌'}")
    print(f"   Pollinations: ✅ (Free)")
    print("=" * 50)
    
    try:
        bot.run(DISCORD_TOKEN, log_handler=None)
    except Exception as e:
        print(f"❌ Failed: {e}")
