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

SYSTEM_PROMPT = '''Kamu adalah AI Assistant yang helpful dan friendly. Jawab dalam Bahasa Indonesia kecuali diminta lain.'''

# ============ MODEL CONFIG 2026 ============
OR_MODELS = {
    "llama": "meta-llama/llama-4-scout:free",
    "gemini": "google/gemini-2.5-flash-preview:free",
    "qwen": "qwen/qwen3-235b-a22b:free",
    "deepseek": "deepseek/deepseek-r1:free",
    "mistral": "mistralai/mistral-small-3.1-24b-instruct:free"
}

CF_MODELS = {"llama": "@cf/meta/llama-3.3-70b-instruct-fp8-fast"}

MODEL_NAMES = {
    "auto": "🚀 Auto",
    "groq": "⚡ Groq",
    "cerebras": "🧠 Cerebras",
    "cloudflare": "☁️ Cloudflare",
    "sambanova": "🦣 SambaNova",
    "cohere": "🔷 Cohere",
    "together": "🤝 Together",
    "pollinations": "🌸 Pollinations",
    "or_llama": "🦙 OR-Llama4",
    "or_gemini": "🔵 OR-Gemini",
    "or_qwen": "🟣 OR-Qwen3",
    "or_deepseek": "🌊 OR-DeepSeek"
}

UA_LIST = ["Roblox/WinInet", "Synapse-X/2.0", "Krnl/1.0", "Fluxus/1.0"]

# ============ AI PROVIDERS ============

def call_groq(msgs):
    cl = get_groq()
    if not cl: return None
    try:
        r = cl.chat.completions.create(messages=msgs, model="llama-3.3-70b-versatile", temperature=0.7, max_tokens=2000)
        return r.choices[0].message.content
    except Exception as e:
        logger.error(f"Groq: {e}")
        return None

def call_cerebras(msgs):
    if not KEY_CEREBRAS: return None
    try:
        r = get_requests().post("https://api.cerebras.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {KEY_CEREBRAS}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b", "messages": msgs, "temperature": 0.7, "max_tokens": 2000}, timeout=30)
        if r.status_code == 200: return r.json()["choices"][0]["message"]["content"]
        return None
    except Exception as e:
        logger.error(f"Cerebras: {e}")
        return None

def call_cloudflare(msgs):
    if not CF_ACCOUNT_ID or not CF_API_TOKEN: return None
    try:
        url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{CF_MODELS['llama']}"
        r = get_requests().post(url, headers={"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"},
            json={"messages": msgs, "max_tokens": 2000}, timeout=60)
        if r.status_code == 200:
            data = r.json()
            if data.get("success") and "result" in data:
                resp = data["result"].get("response", "")
                if resp and resp.strip(): return resp.strip()
        return None
    except Exception as e:
        logger.error(f"Cloudflare: {e}")
        return None

def call_openrouter(msgs, mk="llama"):
    if not KEY_OPENROUTER: return None
    try:
        mid = OR_MODELS.get(mk, OR_MODELS["llama"])
        r = get_requests().post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {KEY_OPENROUTER}", "Content-Type": "application/json", "HTTP-Referer": "https://github.com"},
            json={"model": mid, "messages": msgs, "temperature": 0.7, "max_tokens": 2000}, timeout=60)
        if r.status_code == 200:
            data = r.json()
            if "choices" in data and data["choices"]: return data["choices"][0]["message"]["content"]
        logger.error(f"OR {mk}: {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"OR: {e}")
        return None

def call_sambanova(msgs):
    if not KEY_SAMBANOVA: return None
    try:
        r = get_requests().post("https://api.sambanova.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {KEY_SAMBANOVA}", "Content-Type": "application/json"},
            json={"model": "Meta-Llama-3.3-70B-Instruct", "messages": msgs, "temperature": 0.7, "max_tokens": 2000}, timeout=60)
        if r.status_code == 200: return r.json()["choices"][0]["message"]["content"]
        return None
    except Exception as e:
        logger.error(f"SN: {e}")
        return None

def call_cohere(msgs):
    if not KEY_COHERE: return None
    try:
        preamble, hist, messages = "", [], []
        for m in msgs:
            if m["role"] == "system": preamble = m["content"]
            else: messages.append(m)
        for m in messages[:-1]:
            hist.append({"role": "USER" if m["role"] == "user" else "CHATBOT", "message": m["content"]})
        user_msg = messages[-1]["content"] if messages else ""
        payload = {"model": "command-r-plus", "message": user_msg, "temperature": 0.7}
        if preamble: payload["preamble"] = preamble
        if hist: payload["chat_history"] = hist
        r = get_requests().post("https://api.cohere.com/v2/chat",
            headers={"Authorization": f"Bearer {KEY_COHERE}", "Content-Type": "application/json"}, json=payload, timeout=60)
        if r.status_code == 200: return r.json().get("text", "")
        return None
    except Exception as e:
        logger.error(f"Cohere: {e}")
        return None

def call_together(msgs):
    if not KEY_TOGETHER: return None
    try:
        r = get_requests().post("https://api.together.xyz/v1/chat/completions",
            headers={"Authorization": f"Bearer {KEY_TOGETHER}", "Content-Type": "application/json"},
            json={"model": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "messages": msgs, "temperature": 0.7, "max_tokens": 2000}, timeout=60)
        if r.status_code == 200: return r.json()["choices"][0]["message"]["content"]
        return None
    except Exception as e:
        logger.error(f"Together: {e}")
        return None

def call_pollinations(prompt):
    try:
        r = get_requests().get(f"https://text.pollinations.ai/{prompt}", timeout=60)
        if r.status_code == 200 and r.text.strip(): return r.text.strip()
        return None
    except Exception as e:
        logger.error(f"Pollinations: {e}")
        return None

# ============ AI ROUTER ============

def call_ai(model, msgs, prompt=""):
    if model == "groq": return call_groq(msgs), "Groq"
    elif model == "cerebras": return call_cerebras(msgs), "Cerebras"
    elif model == "cloudflare": return call_cloudflare(msgs), "Cloudflare"
    elif model == "sambanova": return call_sambanova(msgs), "SambaNova"
    elif model == "cohere": return call_cohere(msgs), "Cohere"
    elif model == "together": return call_together(msgs), "Together"
    elif model == "pollinations": return call_pollinations(prompt), "Pollinations"
    elif model.startswith("or_"):
        mk = model[3:]
        return call_openrouter(msgs, mk), f"OR-{mk.title()}"
    return None, "none"

def ask_ai(prompt, uid=None, model=None):
    user_model = db.get_model(uid) if uid else "auto"
    selected = model if model and model != "auto" else (user_model if user_model != "auto" else "auto")
    
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    if uid:
        h = mem.get(uid)
        if h: msgs.extend(h[-6:])
    msgs.append({"role": "user", "content": prompt})
    
    result, used = None, "none"
    
    if selected != "auto":
        result, used = call_ai(selected, msgs, prompt)
        if not result:
            for fn, nm in [(lambda: call_groq(msgs), "Groq"), (lambda: call_cerebras(msgs), "Cerebras"),
                           (lambda: call_cloudflare(msgs), "Cloudflare"), (lambda: call_pollinations(prompt), "Pollinations")]:
                try:
                    result = fn()
                    if result: used = f"{nm}(fb)"; break
                except: continue
    else:
        for fn, nm in [(lambda: call_groq(msgs), "Groq"), (lambda: call_cerebras(msgs), "Cerebras"),
                       (lambda: call_cloudflare(msgs), "Cloudflare"), (lambda: call_openrouter(msgs, "llama"), "OR"),
                       (lambda: call_sambanova(msgs), "SN"), (lambda: call_pollinations(prompt), "Poll")]:
            try:
                result = fn()
                if result: used = nm; break
            except: continue
    
    if not result: return "❌ Semua AI tidak tersedia.", "none"
    if uid:
        mem.add(uid, "user", prompt[:500])
        mem.add(uid, "assistant", result[:500])
    return result, used

# ============ HELPERS ============

def split_msg(text, limit=1900):
    if not text or not str(text).strip(): return ["(kosong)"]
    text = str(text).strip()[:3800]
    if len(text) <= limit: return [text]
    chunks = []
    while text:
        if len(text) <= limit: chunks.append(text); break
        idx = text.rfind('\n', 0, limit)
        if idx <= 0: idx = text.rfind(' ', 0, limit)
        if idx <= 0: idx = limit
        chunks.append(text[:idx].strip())
        text = text[idx:].lstrip()
    return chunks if chunks else ["(kosong)"]

async def send_ai_response(channel, user, content, used):
    """Send response langsung ke channel, bukan reply"""
    try:
        if not content or not content.strip():
            content = "(Response kosong)"
        
        chunks = split_msg(content)
        embed = discord.Embed(color=0x5865F2)
        embed.set_footer(text=f"🤖 {used} | {user.display_name}")
        
        # Kirim ke channel langsung, bukan reply
        await channel.send(content=chunks[0], embed=embed if len(chunks) == 1 else None)
        for c in chunks[1:]:
            if c.strip():
                await channel.send(c)
        return True
    except Exception as e:
        logger.error(f"Send error: {e}")
        return False

# ============ EVENTS ============

@bot.event
async def on_ready():
    logger.info(f'🔥 {bot.user} | {len(bot.guilds)} servers')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=f"{PREFIX}help"))

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return  # Abaikan command tidak dikenal
    logger.error(f"Command error: {error}")

@bot.event
async def on_message(msg):
    if msg.author.bot: return
    
    # Handle mention
    if bot.user.mentioned_in(msg) and not msg.mention_everyone:
        content = msg.content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '').strip()
        if content:
            if db.banned(msg.author.id): return
            ok, rem = rl.check(msg.author.id, "mention", 5)
            if not ok:
                await msg.channel.send(f"⏳ {msg.author.mention} tunggu {rem:.0f}s")
                return
            async with msg.channel.typing():
                result, used = ask_ai(content, msg.author.id)
                await send_ai_response(msg.channel, msg.author, result, used)
                db.stat("ai", msg.author.id)
        else:
            m = db.get_model(msg.author.id)
            await msg.channel.send(f"👋 {msg.author.mention} Model: **{MODEL_NAMES.get(m, m)}**\nKetik pertanyaan setelah mention!")
        return
    
    await bot.process_commands(msg)

# ============ COMMANDS ============

@bot.command(name="ai", aliases=["ask", "a", "tanya"])
async def cmd_ai(ctx, *, prompt: str = None):
    if db.banned(ctx.author.id): return
    ok, rem = rl.check(ctx.author.id, "ai", 5)
    if not ok:
        return await ctx.send(f"⏳ {ctx.author.mention} tunggu {rem:.0f}s")
    if not prompt:
        return await ctx.send(f"❌ Gunakan: `{PREFIX}ai <pertanyaan>`")
    
    async with ctx.typing():
        result, used = ask_ai(prompt, ctx.author.id)
        await send_ai_response(ctx.channel, ctx.author, result, used)
        db.stat("ai", ctx.author.id)

@bot.command(name="model", aliases=["m"])
async def cmd_model(ctx, *, model: str = None):
    if not model:
        cur = db.get_model(ctx.author.id)
        e = discord.Embed(title="🤖 Model AI", color=0x3498DB)
        e.add_field(name="Model Kamu", value=f"**{MODEL_NAMES.get(cur, cur)}**", inline=False)
        e.add_field(name="Tersedia", value="\n".join([f"`{k}` → {v}" for k, v in MODEL_NAMES.items()]), inline=False)
        e.set_footer(text=f"Ganti: {PREFIX}model <nama>")
        return await ctx.send(embed=e)
    
    model = model.lower().strip()
    if model not in MODEL_NAMES:
        return await ctx.send(f"❌ Model tidak valid! Pilihan: `{', '.join(MODEL_NAMES.keys())}`")
    
    db.set_model(ctx.author.id, model)
    await ctx.send(f"✅ {ctx.author.mention} Model: **{MODEL_NAMES.get(model, model)}**")

@bot.command(name="clear", aliases=["reset"])
async def cmd_clear(ctx):
    mem.clear(ctx.author.id)
    await ctx.send(f"🧹 {ctx.author.mention} Memory dihapus!")

@bot.command(name="ping", aliases=["p"])
async def cmd_ping(ctx):
    m = db.get_model(ctx.author.id)
    e = discord.Embed(title="🏓 Pong!", color=0x00FF00)
    e.add_field(name="Latency", value=f"`{round(bot.latency*1000)}ms`")
    e.add_field(name="Model", value=f"`{MODEL_NAMES.get(m,m)}`")
    e.add_field(name="Prefix", value=f"`{PREFIX}`")
    await ctx.send(embed=e)

@bot.command(name="help", aliases=["h"])
async def cmd_help(ctx):
    e = discord.Embed(title="📚 AI Bot Help", color=0x5865F2)
    e.add_field(name="🤖 Chat", value=f"`{PREFIX}ai <teks>`\n`@bot <teks>`", inline=False)
    e.add_field(name="⚙️ Setting", value=f"`{PREFIX}model` - Lihat/ganti\n`{PREFIX}clear` - Hapus memory", inline=False)
    e.add_field(name="🔧 Tools", value=f"`{PREFIX}dump <url>`\n`{PREFIX}testai`", inline=False)
    await ctx.send(embed=e)

@bot.command(name="dump", aliases=["dl"])
async def cmd_dump(ctx, url: str = None):
    if not url:
        return await ctx.send(f"❌ Gunakan: `{PREFIX}dump <url>`")
    ok, rem = rl.check(ctx.author.id, "dump", 8)
    if not ok:
        return await ctx.send(f"⏳ Tunggu {rem:.0f}s")
    
    async with ctx.typing():
        try:
            curl = get_curl()
            ua = random.choice(UA_LIST)
            resp = curl.get(url, impersonate="chrome120", headers={"User-Agent": ua, "Roblox-Place-Id": "2753915549"}, timeout=20)
            content = resp.text[:1024*1024]
            
            ext = "lua"
            if "<!DOCTYPE" in content[:300]: ext = "html"
            elif content.strip().startswith("{"): ext = "json"
            
            e = discord.Embed(title="🔓 Dump", color=0x00FF00)
            e.add_field(name="Size", value=f"`{len(content):,}b`")
            e.add_field(name="Type", value=f"`.{ext}`")
            
            db.stat("dump", ctx.author.id)
            await ctx.send(embed=e, file=discord.File(io.BytesIO(content.encode()), f"dump.{ext}"))
        except Exception as e:
            await ctx.send(f"❌ Error: `{str(e)[:100]}`")

@bot.command(name="testai")
async def cmd_testai(ctx):
    if ctx.author.id not in OWNER_IDS:
        return await ctx.send("❌ Owner only!")
    
    await ctx.send("🔄 Testing AI providers...")
    
    async with ctx.typing():
        results = []
        test = [{"role": "user", "content": "Say: OK"}]
        
        for name, fn in [
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
            ("Pollinations", lambda: call_pollinations("Say OK"))
        ]:
            try:
                r = fn()
                if r:
                    results.append(f"✅ **{name}**: `{r[:15]}...`")
                else:
                    results.append(f"❌ **{name}**: No response")
            except Exception as ex:
                results.append(f"❌ **{name}**: `{str(ex)[:20]}`")
        
        e = discord.Embed(title="🔧 AI Test Results", description="\n".join(results), color=0x3498DB)
        await ctx.send(embed=e)

@bot.command(name="blacklist")
async def cmd_blacklist(ctx, action: str = None, user: discord.User = None):
    if ctx.author.id not in OWNER_IDS: return
    if not action or not user:
        return await ctx.send(f"❌ `{PREFIX}blacklist <add/remove> @user`")
    if action.lower() in ["add", "ban"]:
        db.add_blacklist(user.id)
        await ctx.send(f"✅ {user.mention} diblokir")
    elif action.lower() in ["remove", "unban"]:
        db.remove_blacklist(user.id)
        await ctx.send(f"✅ {user.mention} diunblock")

# ============ MAIN ============

if __name__ == "__main__":
    keep_alive()
    print("=" * 50)
    print("🚀 AI Bot Starting...")
    print(f"📦 Prefix: {PREFIX}")
    print(f"👑 Owners: {OWNER_IDS}")
    print("🔑 API Keys:")
    for name, key in [("Groq", KEY_GROQ), ("Cerebras", KEY_CEREBRAS), ("Cloudflare", CF_API_TOKEN),
                       ("OpenRouter", KEY_OPENROUTER), ("SambaNova", KEY_SAMBANOVA), ("Cohere", KEY_COHERE), ("Together", KEY_TOGETHER)]:
        print(f"   {name}: {'✅' if key else '❌'}")
    print("   Pollinations: ✅ (Free)")
    print("=" * 50)
    bot.run(DISCORD_TOKEN, log_handler=None)
