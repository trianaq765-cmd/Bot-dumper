import discord,os,io,re,time,json,logging,sqlite3,random,threading,hashlib,asyncio
from collections import defaultdict
from dataclasses import dataclass
from discord.ext import commands
from discord import ui
from urllib.parse import quote

# ============== OPTIONAL IMPORTS ==============
try:
    from web_panel import start_web_panel, get_key as wp_get_key, config as wp_config
    HAS_WEB_PANEL = True
except:
    start_web_panel = None
    wp_get_key = None
    wp_config = None
    HAS_WEB_PANEL = False

try:
    from keep_alive import keep_alive
except:
    keep_alive = lambda: None

# ============== LOGGING ==============
logging.basicConfig(level=logging.INFO, format='%(asctime)s|%(levelname)s|%(message)s')
logger = logging.getLogger(__name__)

# ============== ENVIRONMENT VARIABLES ==============
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
KEY_GROQ = os.getenv("GROQ_API_KEY")
KEY_OPENROUTER = os.getenv("OPENROUTER_API_KEY")
KEY_CEREBRAS = os.getenv("CEREBRAS_API_KEY")
KEY_SAMBANOVA = os.getenv("SAMBANOVA_API_KEY")
KEY_COHERE = os.getenv("COHERE_API_KEY")
CF_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
CF_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
KEY_TOGETHER = os.getenv("TOGETHER_API_KEY")
KEY_POLLINATIONS = os.getenv("POLLINATIONS_API_KEY")
KEY_TAVILY = os.getenv("TAVILY_API_KEY")
KEY_MISTRAL = os.getenv("MISTRAL_API_KEY")
KEY_REPLICATE = os.getenv("REPLICATE_API_TOKEN")
KEY_HUGGINGFACE = os.getenv("HUGGINGFACE_API_KEY")
KEY_MOONSHOT = os.getenv("MOONSHOT_API_KEY")

# Shield API (Web 1)
SHIELD_URL = os.getenv("SHIELD_URL", "").rstrip("/")
SHIELD_ADMIN_KEY = os.getenv("SHIELD_ADMIN_KEY", "")

# Config Panel (Web 2) - BARU
CONFIG_PANEL_URL = os.getenv("CONFIG_PANEL_URL", "").rstrip("/")
CONFIG_BOT_SECRET = os.getenv("CONFIG_BOT_SECRET", "")

OWNER_IDS = [int(x) for x in os.getenv("OWNER_IDS", "0").split(",") if x.isdigit()]
PREFIX = os.getenv("BOT_PREFIX", ".")

if not DISCORD_TOKEN:
    print("DISCORD_TOKEN Missing")
    exit(1)

# ============== BOT SETUP ==============
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# ============== LAZY IMPORTS ==============
_groq = None
_requests = None
_curl = None
_cloudscraper = None

def get_requests():
    global _requests
    if _requests is None:
        import requests
        _requests = requests
    return _requests

def get_curl():
    global _curl
    if _curl is None:
        try:
            from curl_cffi import requests as r
            _curl = r
        except:
            _curl = None
    return _curl

def get_cloudscraper():
    global _cloudscraper
    if _cloudscraper is None:
        try:
            import cloudscraper
            _cloudscraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
        except:
            _cloudscraper = None
    return _cloudscraper

# ============== CONFIG PANEL INTEGRATION (WEB 2) ==============
_panel_config = {"keys": {}, "models": {}, "settings": {}, "last_fetch": 0}
_panel_lock = threading.Lock()

def fetch_panel_config(force=False):
    """Fetch config from panel, cache for 60 seconds"""
    global _panel_config
    
    if not CONFIG_PANEL_URL or not CONFIG_BOT_SECRET:
        return None
    
    with _panel_lock:
        now = time.time()
        # Return cached if not expired and not forced
        if not force and now - _panel_config.get("last_fetch", 0) < 60:
            return _panel_config if _panel_config.get("last_fetch", 0) > 0 else None
        
        try:
            r = get_requests().get(
                f"{CONFIG_PANEL_URL}/api/bot/config",
                headers={"X-Bot-Secret": CONFIG_BOT_SECRET},
                timeout=10
            )
            if r.status_code == 200:
                data = r.json()
                _panel_config = {
                    "keys": data.get("keys", {}),
                    "models": data.get("models", {}),
                    "settings": data.get("settings", {}),
                    "last_fetch": now
                }
                logger.info(f"Config panel synced: {len(_panel_config['keys'])} keys, {len(_panel_config['models'])} models")
                return _panel_config
            else:
                logger.warning(f"Config panel HTTP {r.status_code}")
        except Exception as e:
            logger.warning(f"Config panel fetch failed: {e}")
    
    return None

def get_api_key(name):
    """Get API key - Priority: Panel > web_panel lama > env"""
    # 1. Try from Config Panel (Web 2)
    config = fetch_panel_config()
    if config and name in config.get("keys", {}):
        return config["keys"][name]
    
    # 2. Fallback to old web_panel (if exists)
    if wp_get_key:
        k = wp_get_key(name)
        if k:
            return k
    
    # 3. Fallback to environment variables
    mapping = {
        "groq": KEY_GROQ,
        "openrouter": KEY_OPENROUTER,
        "cerebras": KEY_CEREBRAS,
        "sambanova": KEY_SAMBANOVA,
        "cohere": KEY_COHERE,
        "cloudflare_token": CF_API_TOKEN,
        "cloudflare_account": CF_ACCOUNT_ID,
        "together": KEY_TOGETHER,
        "tavily": KEY_TAVILY,
        "mistral": KEY_MISTRAL,
        "replicate": KEY_REPLICATE,
        "huggingface": KEY_HUGGINGFACE,
        "moonshot": KEY_MOONSHOT,
        "pollinations": KEY_POLLINATIONS
    }
    return mapping.get(name, "") or os.getenv(name.upper() + "_API_KEY", "")

def get_groq():
    global _groq
    if _groq is None:
        k = get_api_key("groq")
        if k:
            try:
                from groq import Groq
                _groq = Groq(api_key=k)
            except:
                pass
    return _groq

# ============== DEFAULT MODELS (Fallback) ==============
DEFAULT_MODELS = {
    "groq": {"e": "⚡", "n": "Groq", "d": "Llama 3.3 70B", "c": "main", "p": "groq", "m": "llama-3.3-70b-versatile"},
    "cerebras": {"e": "🧠", "n": "Cerebras", "d": "Llama 3.3 70B", "c": "main", "p": "cerebras", "m": "llama-3.3-70b"},
    "sambanova": {"e": "🦣", "n": "SambaNova", "d": "Llama 3.3 70B", "c": "main", "p": "sambanova", "m": "Meta-Llama-3.3-70B-Instruct"},
    "cloudflare": {"e": "☁️", "n": "Cloudflare", "d": "Llama 3.3 70B", "c": "main", "p": "cloudflare", "m": "@cf/meta/llama-3.3-70b-instruct-fp8-fast"},
    "cohere": {"e": "🔷", "n": "Cohere", "d": "Command R+", "c": "main", "p": "cohere", "m": "command-r-plus-08-2024"},
    "mistral": {"e": "Ⓜ️", "n": "Mistral", "d": "Mistral Small", "c": "main", "p": "mistral", "m": "mistral-small-latest"},
    "together": {"e": "🤝", "n": "Together", "d": "Llama 3.3 Turbo", "c": "main", "p": "together", "m": "meta-llama/Llama-3.3-70B-Instruct-Turbo"},
    "moonshot": {"e": "🌙", "n": "Moonshot", "d": "Kimi 128K", "c": "main", "p": "moonshot", "m": "moonshot-v1-8k"},
    "huggingface": {"e": "🤗", "n": "HuggingFace", "d": "Mixtral 8x7B", "c": "main", "p": "huggingface", "m": "mistralai/Mixtral-8x7B-Instruct-v0.1"},
    "replicate": {"e": "🔄", "n": "Replicate", "d": "Llama 405B", "c": "main", "p": "replicate", "m": "meta/meta-llama-3.1-405b-instruct"},
    "tavily": {"e": "🔍", "n": "Tavily", "d": "Search+Web", "c": "main", "p": "tavily", "m": "search"},
    "or_llama": {"e": "🦙", "n": "OR-Llama", "d": "Llama 3.3 70B", "c": "openrouter", "p": "openrouter", "m": "meta-llama/llama-3.3-70b-instruct:free"},
    "or_gemini": {"e": "💎", "n": "OR-Gemini", "d": "Gemini 2.0", "c": "openrouter", "p": "openrouter", "m": "google/gemini-2.0-flash-exp:free"},
    "or_qwen": {"e": "💻", "n": "OR-Qwen", "d": "Qwen 2.5 72B", "c": "openrouter", "p": "openrouter", "m": "qwen/qwen-2.5-72b-instruct:free"},
    "or_deepseek": {"e": "🌊", "n": "OR-DeepSeek", "d": "DeepSeek Chat", "c": "openrouter", "p": "openrouter", "m": "deepseek/deepseek-chat:free"},
    "or_mistral": {"e": "🅼", "n": "OR-Mistral", "d": "Mistral Nemo", "c": "openrouter", "p": "openrouter", "m": "mistralai/mistral-nemo:free"},
    "p_openai": {"e": "🤖", "n": "Poll-OpenAI", "d": "OpenAI Large", "c": "pollinations", "p": "pollinations", "m": "openai-large"},
    "p_claude": {"e": "🎭", "n": "Poll-Claude", "d": "Claude Hybrid", "c": "pollinations", "p": "pollinations", "m": "claude-hybridspace"},
    "p_gemini": {"e": "💎", "n": "Poll-Gemini", "d": "Gemini", "c": "pollinations", "p": "pollinations", "m": "gemini"},
    "p_deepseek": {"e": "🐳", "n": "Poll-DeepSeek", "d": "DeepSeek V3", "c": "pollinations", "p": "pollinations", "m": "deepseek"},
    "p_qwen": {"e": "📟", "n": "Poll-Qwen", "d": "Qwen 72B", "c": "pollinations", "p": "pollinations", "m": "qwen-72b"},
    "p_llama": {"e": "🦙", "n": "Poll-Llama", "d": "Llama 3.3", "c": "pollinations", "p": "pollinations", "m": "llama-3.3-70b"},
    "p_mistral": {"e": "🅼", "n": "Poll-Mistral", "d": "Mistral", "c": "pollinations", "p": "pollinations", "m": "mistral"},
    "poll_free": {"e": "🌸", "n": "Poll-Free", "d": "Free Unlimited", "c": "pollinations", "p": "pollinations", "m": "free"},
}

IMG_MODELS = {
    "flux": ("🎨", "Flux", "Standard"),
    "flux_pro": ("⚡", "Flux Pro", "Professional"),
    "turbo": ("🚀", "Turbo", "Fast"),
    "dalle": ("🤖", "DALL-E 3", "OpenAI"),
    "sdxl": ("🖼️", "SDXL", "Stable Diffusion")
}

def get_models():
    """Get models - merge panel models with defaults"""
    config = fetch_panel_config()
    if config and config.get("models"):
        merged = DEFAULT_MODELS.copy()
        for mid, mdata in config["models"].items():
            merged[mid] = {
                "e": mdata.get("e", "🤖"),
                "n": mdata.get("n", mid),
                "d": mdata.get("d", ""),
                "c": mdata.get("c", "custom"),
                "p": mdata.get("p", "groq"),
                "m": mdata.get("m", mid),
                "endpoint": mdata.get("endpoint", "")
            }
        return merged
    return DEFAULT_MODELS

def get_panel_setting(key, default=None):
    """Get setting from panel"""
    config = fetch_panel_config()
    if config and key in config.get("settings", {}):
        return config["settings"][key]
    return default

def get_all_model_ids():
    """Get all available model IDs"""
    return list(get_models().keys())

def is_owner(uid):
    return uid in OWNER_IDS

# ============== SHIELD API (WEB 1) ==============
class ShieldAPI:
    def __init__(self, url, key):
        self.url = url
        self.key = key
        self.timeout = 30
    
    def _h(self):
        return {"x-admin-key": self.key, "Content-Type": "application/json", "Accept": "application/json"}
    
    def _get(self, ep):
        if not self.url or not self.key:
            return {"success": False, "error": "Not configured"}
        try:
            r = get_requests().get(f"{self.url}{ep}", headers=self._h(), timeout=self.timeout)
            return r.json() if r.status_code == 200 else {"success": False, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)[:80]}
    
    def _post(self, ep, data=None):
        if not self.url or not self.key:
            return {"success": False, "error": "Not configured"}
        try:
            r = get_requests().post(f"{self.url}{ep}", headers=self._h(), json=data or {}, timeout=self.timeout)
            return r.json() if r.status_code in [200, 201] else {"success": False, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)[:80]}
    
    def _del(self, ep):
        if not self.url or not self.key:
            return {"success": False, "error": "Not configured"}
        try:
            r = get_requests().delete(f"{self.url}{ep}", headers=self._h(), timeout=self.timeout)
            return r.json() if r.status_code == 200 else {"success": False, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)[:80]}
    
    def stats(self):
        return self._get("/api/admin/stats")
    
    def sessions(self):
        return self._get("/api/admin/sessions")
    
    def logs(self):
        return self._get("/api/admin/logs")
    
    def bans(self):
        return self._get("/api/admin/bans")
    
    def whitelist(self):
        return self._get("/api/admin/whitelist")
    
    def suspended(self):
        return self._get("/api/admin/suspended")
    
    def script(self):
        return self._get("/api/admin/script")
    
    def health(self):
        try:
            r = get_requests().get(f"{self.url}/api/keepalive", timeout=10)
            return {"success": r.status_code == 200}
        except:
            return {"success": False}
    
    def add_ban(self, hwid=None, ip=None, pid=None, reason="Via Discord"):
        d = {"reason": reason}
        if hwid:
            d["hwid"] = hwid
        if ip:
            d["ip"] = ip
        if pid:
            d["playerId"] = pid
        return self._post("/api/admin/bans", d)
    
    def rem_ban(self, bid):
        return self._del(f"/api/admin/bans/{bid}")
    
    def add_wl(self, t, v):
        return self._post("/api/admin/whitelist", {"type": t, "value": v})
    
    def rem_wl(self, t, v):
        return self._post("/api/admin/whitelist/remove", {"type": t, "value": v})
    
    def suspend(self, t, v, reason="Via Discord", dur=None):
        d = {"type": t, "value": v, "reason": reason}
        if dur:
            d["duration"] = dur
        return self._post("/api/admin/suspend", d)
    
    def unsuspend(self, t, v):
        return self._post("/api/admin/unsuspend", {"type": t, "value": v})
    
    def kill(self, sid, reason="Via Discord"):
        return self._post("/api/admin/kill-session", {"sessionId": sid, "reason": reason})
    
    def clear_sessions(self):
        return self._post("/api/admin/sessions/clear", {})
    
    def clear_logs(self):
        return self._post("/api/admin/logs/clear", {})
    
    def clear_cache(self):
        return self._post("/api/admin/cache/clear", {})

shield = ShieldAPI(SHIELD_URL, SHIELD_ADMIN_KEY)

# ============== DATABASE ==============
class Database:
    def __init__(self, path="bot.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS user_prefs(uid INTEGER PRIMARY KEY, model TEXT DEFAULT "groq", img_model TEXT DEFAULT "flux");
            CREATE TABLE IF NOT EXISTS bot_settings(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS stats(id INTEGER PRIMARY KEY, cmd TEXT, uid INTEGER, ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS blacklist(uid INTEGER PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS allowed_users(uid INTEGER PRIMARY KEY, allowed_models TEXT DEFAULT "groq");
            CREATE TABLE IF NOT EXISTS dump_cache(url TEXT PRIMARY KEY, content TEXT, ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        ''')
        self._init()
    
    def _init(self):
        with self.lock:
            if not self.conn.execute('SELECT 1 FROM bot_settings WHERE key="public_default"').fetchone():
                self.conn.execute('INSERT INTO bot_settings VALUES("public_default","groq")')
                self.conn.commit()
    
    def get_setting(self, k):
        with self.lock:
            r = self.conn.execute('SELECT value FROM bot_settings WHERE key=?', (k,)).fetchone()
            return r[0] if r else None
    
    def set_setting(self, k, v):
        with self.lock:
            self.conn.execute('INSERT OR REPLACE INTO bot_settings VALUES(?,?)', (k, v))
            self.conn.commit()
    
    def get_model(self, uid):
        with self.lock:
            r = self.conn.execute('SELECT model FROM user_prefs WHERE uid=?', (uid,)).fetchone()
            return r[0] if r else "groq"
    
    def set_model(self, uid, m):
        with self.lock:
            self.conn.execute('INSERT OR REPLACE INTO user_prefs(uid,model,img_model) VALUES(?,?,COALESCE((SELECT img_model FROM user_prefs WHERE uid=?),"flux"))', (uid, m, uid))
            self.conn.commit()
    
    def get_img(self, uid):
        with self.lock:
            r = self.conn.execute('SELECT img_model FROM user_prefs WHERE uid=?', (uid,)).fetchone()
            return r[0] if r else "flux"
    
    def set_img(self, uid, m):
        with self.lock:
            self.conn.execute('INSERT OR REPLACE INTO user_prefs(uid,model,img_model) VALUES(?,COALESCE((SELECT model FROM user_prefs WHERE uid=?),"groq"),?)', (uid, uid, m))
            self.conn.commit()
    
    def get_allowed(self, uid):
        with self.lock:
            r = self.conn.execute('SELECT allowed_models FROM allowed_users WHERE uid=?', (uid,)).fetchone()
            return r[0].split(",") if r else []
    
    def set_allowed(self, uid, models):
        with self.lock:
            self.conn.execute('INSERT OR REPLACE INTO allowed_users VALUES(?,?)', (uid, ",".join(models)))
            self.conn.commit()
    
    def rem_allowed(self, uid):
        with self.lock:
            self.conn.execute('DELETE FROM allowed_users WHERE uid=?', (uid,))
            self.conn.commit()
    
    def stat(self, cmd, uid):
        with self.lock:
            self.conn.execute('INSERT INTO stats(cmd,uid) VALUES(?,?)', (cmd, uid))
            self.conn.commit()
    
    def banned(self, uid):
        with self.lock:
            return self.conn.execute('SELECT 1 FROM blacklist WHERE uid=?', (uid,)).fetchone() is not None
    
    def ban(self, uid):
        with self.lock:
            self.conn.execute('INSERT OR IGNORE INTO blacklist VALUES(?)', (uid,))
            self.conn.commit()
    
    def unban(self, uid):
        with self.lock:
            self.conn.execute('DELETE FROM blacklist WHERE uid=?', (uid,))
            self.conn.commit()
    
    def cache_dump(self, url, c):
        with self.lock:
            h = hashlib.md5(url.encode()).hexdigest()
            self.conn.execute('INSERT OR REPLACE INTO dump_cache VALUES(?,?,CURRENT_TIMESTAMP)', (h, c[:500000]))
            self.conn.commit()
    
    def get_cache(self, url):
        with self.lock:
            h = hashlib.md5(url.encode()).hexdigest()
            r = self.conn.execute('SELECT content FROM dump_cache WHERE url=? AND ts>datetime("now","-1 hour")', (h,)).fetchone()
            return r[0] if r else None
    
    def get_stats(self):
        with self.lock:
            total = self.conn.execute('SELECT COUNT(*) FROM stats').fetchone()[0]
            today = self.conn.execute('SELECT COUNT(*) FROM stats WHERE ts>datetime("now","-1 day")').fetchone()[0]
            users = self.conn.execute('SELECT COUNT(DISTINCT uid) FROM stats').fetchone()[0]
            top = self.conn.execute('SELECT cmd, COUNT(*) as c FROM stats GROUP BY cmd ORDER BY c DESC LIMIT 5').fetchall()
            return {"total": total, "today": today, "users": users, "top": top}

db = Database()

# ============== RATE LIMITER ==============
class RateLimiter:
    def __init__(self):
        self.cd = defaultdict(lambda: defaultdict(float))
        self.lock = threading.Lock()
    
    def check(self, uid, cmd, cd=5):
        # Check panel settings for rate limits
        if cmd == "ai":
            panel_cd = get_panel_setting("rate_limit_ai")
            if panel_cd:
                try:
                    cd = int(panel_cd)
                except:
                    pass
        elif cmd == "img":
            panel_cd = get_panel_setting("rate_limit_img")
            if panel_cd:
                try:
                    cd = int(panel_cd)
                except:
                    pass
        
        with self.lock:
            now = time.time()
            last = self.cd[uid][cmd]
            if now - last < cd:
                return False, cd - (now - last)
            self.cd[uid][cmd] = now
            return True, 0
    
    def cleanup(self):
        with self.lock:
            now = time.time()
            for uid in list(self.cd.keys()):
                self.cd[uid] = {k: v for k, v in self.cd[uid].items() if now - v < 300}
                if not self.cd[uid]:
                    del self.cd[uid]

rl = RateLimiter()

# ============== MEMORY ==============
@dataclass
class ChatMsg:
    role: str
    content: str
    ts: float

class Memory:
    def __init__(self):
        self.conv = defaultdict(list)
        self.lock = threading.Lock()
    
    def add(self, uid, role, content):
        # Get max messages from panel
        max_msgs = 25
        timeout_mins = 30
        
        panel_max = get_panel_setting("max_memory_messages")
        if panel_max:
            try:
                max_msgs = int(panel_max)
            except:
                pass
        
        panel_timeout = get_panel_setting("memory_timeout_minutes")
        if panel_timeout:
            try:
                timeout_mins = int(panel_timeout)
            except:
                pass
        
        timeout_secs = timeout_mins * 60
        
        with self.lock:
            now = time.time()
            self.conv[uid] = [m for m in self.conv[uid] if now - m.ts < timeout_secs]
            self.conv[uid].append(ChatMsg(role, content[:2500], now))
            if len(self.conv[uid]) > max_msgs:
                self.conv[uid] = self.conv[uid][-max_msgs:]
    
    def get(self, uid):
        timeout_mins = 30
        panel_timeout = get_panel_setting("memory_timeout_minutes")
        if panel_timeout:
            try:
                timeout_mins = int(panel_timeout)
            except:
                pass
        timeout_secs = timeout_mins * 60
        
        with self.lock:
            now = time.time()
            self.conv[uid] = [m for m in self.conv[uid] if now - m.ts < timeout_secs]
            return [{"role": m.role, "content": m.content} for m in self.conv[uid]]
    
    def clear(self, uid):
        with self.lock:
            self.conv[uid] = []

mem = Memory()

# ============== DUMPER ==============
class Dumper:
    def __init__(self):
        self.last = None
    
    def dump(self, url, cache=True):
        if cache:
            c = db.get_cache(url)
            if c:
                return {"success": True, "content": c, "method": "cache"}
        
        req = get_requests()
        curl = get_curl()
        cs = get_cloudscraper()
        methods = []
        
        if curl:
            methods.append(("curl", lambda u: curl.get(u, impersonate="chrome120", headers={"User-Agent": "Roblox/WinInet"}, timeout=25)))
        if cs:
            methods.append(("cloudscraper", lambda u: cs.get(u, timeout=25)))
        if req:
            methods.append(("requests", lambda u: req.get(u, headers={"User-Agent": "Roblox/WinInet"}, timeout=25)))
        
        if self.last:
            methods.sort(key=lambda x: x[0] != self.last)
        
        for name, func in methods:
            try:
                r = func(url)
                if r.status_code == 200 and len(r.text) > 10:
                    self.last = name
                    if cache:
                        db.cache_dump(url, r.text)
                    return {"success": True, "content": r.text, "method": name}
            except:
                pass
        
        return {"success": False, "error": "All methods failed"}

dumper = Dumper()

# ============== SYSTEM PROMPT ==============
def get_system_prompt():
    """Get system prompt from panel or default"""
    panel_prompt = get_panel_setting("system_prompt")
    if panel_prompt:
        return panel_prompt
    
    return '''You are an elite AI assistant representing the pinnacle of artificial intelligence - a synthesis of capabilities from Claude Opus 4.5, GPT-5.2, and Gemini 3 Pro Ultra.
REASONING ENGINE: Chain-of-Thought Processing, Multi-Perspective Analysis, Bayesian Inference, Counterfactual Reasoning, Meta-Cognition.
KNOWLEDGE SYNTHESIS: Cross-Domain Integration, Temporal Awareness, Source Triangulation, Abstraction Layering.
RESPONSE METHODOLOGY: PARSE→PLAN→EXECUTE→VERIFY→ENHANCE.
INTERACTION PRINCIPLES: Match complexity to user expertise. Be direct and substantive. Use formatting strategically. Balance confidence with intellectual humility. Prioritize accuracy over speed.
LANGUAGE: Default Bahasa Indonesia, adapt to user preference seamlessly.'''

def get_public_default():
    """Get default model - Priority: Panel > DB"""
    panel_default = get_panel_setting("default_model")
    if panel_default:
        return panel_default
    return db.get_setting("public_default") or "groq"

# ============== AI PROVIDERS ==============
def call_groq(msgs):
    c = get_groq()
    if not c:
        return None
    try:
        models = get_models()
        model_name = models.get("groq", {}).get("m", "llama-3.3-70b-versatile")
        r = c.chat.completions.create(messages=msgs, model=model_name, temperature=0.7, max_tokens=4096)
        return r.choices[0].message.content
    except Exception as e:
        logger.error(f"Groq: {e}")
        return None

def call_cerebras(msgs):
    k = get_api_key("cerebras")
    if not k:
        return None
    try:
        models = get_models()
        model_name = models.get("cerebras", {}).get("m", "llama-3.3-70b")
        r = get_requests().post(
            "https://api.cerebras.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {k}", "Content-Type": "application/json"},
            json={"model": model_name, "messages": msgs, "max_tokens": 4096},
            timeout=30
        )
        return r.json()["choices"][0]["message"]["content"] if r.status_code == 200 else None
    except Exception as e:
        logger.error(f"Cerebras: {e}")
        return None

def call_sambanova(msgs):
    k = get_api_key("sambanova")
    if not k:
        return None
    try:
        models = get_models()
        model_name = models.get("sambanova", {}).get("m", "Meta-Llama-3.3-70B-Instruct")
        r = get_requests().post(
            "https://api.sambanova.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {k}", "Content-Type": "application/json"},
            json={"model": model_name, "messages": msgs, "max_tokens": 4096},
            timeout=45
        )
        return r.json()["choices"][0]["message"]["content"] if r.status_code == 200 else None
    except Exception as e:
        logger.error(f"SambaNova: {e}")
        return None

def call_cloudflare(msgs):
    acc = get_api_key("cloudflare_account")
    tok = get_api_key("cloudflare_token")
    if not acc or not tok:
        return None
    try:
        models = get_models()
        model_name = models.get("cloudflare", {}).get("m", "@cf/meta/llama-3.3-70b-instruct-fp8-fast")
        r = get_requests().post(
            f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{model_name}",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            json={"messages": msgs, "max_tokens": 4096},
            timeout=45
        )
        if r.status_code == 200:
            d = r.json()
            return d["result"]["response"].strip() if d.get("success") else None
    except Exception as e:
        logger.error(f"CF: {e}")
    return None

def call_cohere(msgs):
    k = get_api_key("cohere")
    if not k:
        return None
    try:
        sys_p = ""
        user_m = "Hi"
        for m in msgs:
            if m["role"] == "system":
                sys_p = m["content"]
        if msgs:
            user_m = msgs[-1]["content"]
        
        models = get_models()
        model_name = models.get("cohere", {}).get("m", "command-r-plus-08-2024")
        
        payload = {"model": model_name, "message": user_m}
        if sys_p:
            payload["preamble"] = sys_p
        
        r = get_requests().post(
            "https://api.cohere.com/v1/chat",
            headers={"Authorization": f"Bearer {k}", "Content-Type": "application/json"},
            json=payload,
            timeout=45
        )
        return r.json().get("text") if r.status_code == 200 else None
    except Exception as e:
        logger.error(f"Cohere: {e}")
        return None

def call_mistral(msgs):
    k = get_api_key("mistral")
    if not k:
        return None
    try:
        models = get_models()
        model_name = models.get("mistral", {}).get("m", "mistral-small-latest")
        r = get_requests().post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {k}", "Content-Type": "application/json"},
            json={"model": model_name, "messages": msgs, "max_tokens": 4096},
            timeout=45
        )
        return r.json()["choices"][0]["message"]["content"] if r.status_code == 200 else None
    except Exception as e:
        logger.error(f"Mistral: {e}")
        return None

def call_together(msgs):
    k = get_api_key("together")
    if not k:
        return None
    try:
        models = get_models()
        model_name = models.get("together", {}).get("m", "meta-llama/Llama-3.3-70B-Instruct-Turbo")
        r = get_requests().post(
            "https://api.together.xyz/v1/chat/completions",
            headers={"Authorization": f"Bearer {k}", "Content-Type": "application/json"},
            json={"model": model_name, "messages": msgs, "max_tokens": 4096},
            timeout=45
        )
        return r.json()["choices"][0]["message"]["content"] if r.status_code == 200 else None
    except Exception as e:
        logger.error(f"Together: {e}")
        return None

def call_moonshot(msgs):
    k = get_api_key("moonshot")
    if not k:
        return None
    try:
        models = get_models()
        model_name = models.get("moonshot", {}).get("m", "moonshot-v1-8k")
        r = get_requests().post(
            "https://api.moonshot.cn/v1/chat/completions",
            headers={"Authorization": f"Bearer {k}", "Content-Type": "application/json"},
            json={"model": model_name, "messages": msgs, "max_tokens": 4096},
            timeout=60
        )
        return r.json()["choices"][0]["message"]["content"] if r.status_code == 200 else None
    except Exception as e:
        logger.error(f"Moonshot: {e}")
        return None

def call_huggingface(msgs):
    k = get_api_key("huggingface")
    if not k:
        return None
    try:
        prompt = "\n".join([f"{m['role']}: {m['content']}" for m in msgs[-5:]])
        models = get_models()
        model_name = models.get("huggingface", {}).get("m", "mistralai/Mixtral-8x7B-Instruct-v0.1")
        r = get_requests().post(
            f"https://api-inference.huggingface.co/models/{model_name}",
            headers={"Authorization": f"Bearer {k}"},
            json={"inputs": prompt, "parameters": {"max_new_tokens": 1000, "return_full_text": False}},
            timeout=60
        )
        if r.status_code == 200:
            d = r.json()
            return d[0].get("generated_text", "").strip() if isinstance(d, list) and d else None
    except Exception as e:
        logger.error(f"HF: {e}")
    return None

def call_replicate(msgs):
    k = get_api_key("replicate")
    if not k:
        return None
    try:
        prompt = "\n".join([f"{m['role']}: {m['content']}" for m in msgs[-5:]])
        models = get_models()
        model_name = models.get("replicate", {}).get("m", "meta/meta-llama-3.1-405b-instruct")
        r = get_requests().post(
            f"https://api.replicate.com/v1/models/{model_name}/predictions",
            headers={"Authorization": f"Bearer {k}", "Content-Type": "application/json"},
            json={"input": {"prompt": prompt, "max_tokens": 2000}},
            timeout=15
        )
        if r.status_code in [200, 201]:
            pred = r.json()
            url = f"https://api.replicate.com/v1/predictions/{pred.get('id')}"
            for _ in range(30):
                time.sleep(2)
                ch = get_requests().get(url, headers={"Authorization": f"Bearer {k}"}, timeout=10)
                if ch.status_code == 200:
                    d = ch.json()
                    if d.get("status") == "succeeded":
                        return "".join(d.get("output", []))
                    if d.get("status") in ["failed", "canceled"]:
                        return None
    except Exception as e:
        logger.error(f"Replicate: {e}")
    return None

def call_tavily(msgs):
    k = get_api_key("tavily")
    if not k:
        return None
    try:
        q = msgs[-1]["content"] if msgs else ""
        r = get_requests().post(
            "https://api.tavily.com/search",
            json={"api_key": k, "query": q, "search_depth": "advanced", "max_results": 8},
            timeout=20
        )
        if r.status_code == 200:
            d = r.json()
            results = d.get("results", [])[:5]
            ctx = "\n".join([f"• {x.get('title', '')}: {x.get('content', '')[:150]}" for x in results])
            ans = d.get("answer", "")
            return f"🔍 **Answer:**\n{ans}\n\n**Sources:**\n{ctx}" if ans else f"🔍 **Results:**\n{ctx}" if ctx else None
    except Exception as e:
        logger.error(f"Tavily: {e}")
    return None

def call_openrouter(msgs, model_key):
    k = get_api_key("openrouter")
    if not k:
        return None
    try:
        models = get_models()
        mid = models.get(model_key, {}).get("m", models.get("or_llama", {}).get("m", "meta-llama/llama-3.3-70b-instruct:free"))
        r = get_requests().post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {k}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com",
                "X-Title": "DiscordBot"
            },
            json={"model": mid, "messages": msgs, "max_tokens": 4096},
            timeout=60
        )
        if r.status_code == 200:
            d = r.json()
            return d["choices"][0]["message"]["content"] if "choices" in d else None
    except Exception as e:
        logger.error(f"OR: {e}")
    return None

def call_pollinations(msgs, model_key):
    try:
        models = get_models()
        mid = models.get(model_key, {}).get("m", "openai-large")
        if mid == "free":
            prompt = msgs[-1]["content"] if msgs else ""
            r = get_requests().get(f"https://text.pollinations.ai/{quote(prompt[:3000])}", timeout=60)
        else:
            r = get_requests().post(
                "https://text.pollinations.ai/",
                headers={"Content-Type": "application/json"},
                json={"messages": msgs, "model": mid, "temperature": 0.7},
                timeout=60
            )
        return r.text.strip() if r.status_code == 200 and r.text.strip() else None
    except Exception as e:
        logger.error(f"Poll: {e}")
        return None

def call_ai(model, msgs, prompt=""):
    """Call AI provider based on model"""
    models = get_models()
    m = models.get(model, {})
    p = m.get("p", "groq")
    
    if p == "groq":
        return call_groq(msgs), m.get("n", "Groq")
    elif p == "cerebras":
        return call_cerebras(msgs), m.get("n", "Cerebras")
    elif p == "sambanova":
        return call_sambanova(msgs), m.get("n", "SambaNova")
    elif p == "cloudflare":
        return call_cloudflare(msgs), m.get("n", "Cloudflare")
    elif p == "cohere":
        return call_cohere(msgs), m.get("n", "Cohere")
    elif p == "mistral":
        return call_mistral(msgs), m.get("n", "Mistral")
    elif p == "together":
        return call_together(msgs), m.get("n", "Together")
    elif p == "moonshot":
        return call_moonshot(msgs), m.get("n", "Moonshot")
    elif p == "huggingface":
        return call_huggingface(msgs), m.get("n", "HuggingFace")
    elif p == "replicate":
        return call_replicate(msgs), m.get("n", "Replicate")
    elif p == "openrouter":
        return call_openrouter(msgs, model), m.get("n", "OpenRouter")
    elif p == "pollinations":
        return call_pollinations(msgs, model), m.get("n", "Pollinations")
    elif p == "tavily":
        return call_tavily(msgs), m.get("n", "Tavily")
    
    return None, "Unknown"

# Fallback chain
FALLBACK = [
    ("groq", call_groq),
    ("cerebras", call_cerebras),
    ("sambanova", call_sambanova),
    ("cloudflare", call_cloudflare),
    ("poll_free", lambda m: call_pollinations(m, "poll_free"))
]

def ask_ai(prompt, uid=None, model=None):
    """Main function to ask AI with fallback"""
    sel = model if model else (db.get_model(uid) if is_owner(uid) else get_public_default())
    
    msgs = [{"role": "system", "content": get_system_prompt()}]
    
    if uid:
        h = mem.get(uid)
        if h:
            msgs.extend(h[-10:])
    
    msgs.append({"role": "user", "content": prompt})
    
    result, prov = call_ai(sel, msgs, prompt)
    
    if not result:
        for name, func in FALLBACK:
            if name == sel:
                continue
            try:
                result = func(msgs)
            except:
                continue
            if result:
                prov = name.title()
                break
    
    if not result:
        return "Maaf, semua AI sedang tidak tersedia.", "None"
    
    if uid:
        mem.add(uid, "user", prompt[:1500])
        mem.add(uid, "assistant", result[:1500])
    
    return result, prov

async def gen_image(prompt, model="flux"):
    try:
        mid = {"flux": "flux", "flux_pro": "flux-pro", "turbo": "turbo", "dalle": "dall-e-3", "sdxl": "sdxl"}.get(model, "flux")
        url = f"https://image.pollinations.ai/prompt/{quote(prompt)}?model={mid}&nologo=true&width=1024&height=1024&seed={random.randint(1, 99999)}"
        r = get_requests().get(url, timeout=120)
        return (r.content, None) if r.status_code == 200 and len(r.content) > 1000 else (None, f"HTTP {r.status_code}")
    except Exception as e:
        return None, str(e)[:50]

# ============== DISCORD UI COMPONENTS ==============
class ModelSelect(ui.Select):
    def __init__(self, category, cid):
        models = get_models()
        model_list = [m for m, d in models.items() if d["c"] == category]
        opts = [discord.SelectOption(label=models[m]["n"], value=m, emoji=models[m]["e"], description=models[m]["d"][:50]) for m in model_list[:25]]
        if not opts:
            opts = [discord.SelectOption(label="No models", value="none")]
        super().__init__(placeholder=f"Select {category.title()} Model...", options=opts, custom_id=cid)
    
    async def callback(self, i: discord.Interaction):
        try:
            if not is_owner(i.user.id):
                return await i.response.send_message("❌ Owner only!", ephemeral=True)
            if self.values[0] == "none":
                return await i.response.send_message("❌ No models available", ephemeral=True)
            db.set_model(i.user.id, self.values[0])
            models = get_models()
            m = models.get(self.values[0], {})
            await i.response.send_message(f"✅ Model: {m.get('e', '')} **{m.get('n', '')}**\n> {m.get('d', '')}", ephemeral=True)
        except Exception as e:
            logger.error(f"ModelSelect: {e}")
            await i.response.send_message(f"❌ Error: {e}", ephemeral=True)

class ModelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        models = get_models()
        categories = list(set(m["c"] for m in models.values()))
        for cat in categories[:4]:  # Max 4 categories
            self.add_item(ModelSelect(cat, f"sel_{cat}"))

class ImgSelect(ui.Select):
    def __init__(self):
        opts = [discord.SelectOption(label=v[1], value=k, emoji=v[0], description=v[2]) for k, v in IMG_MODELS.items()]
        super().__init__(placeholder="Select Image Model...", options=opts, custom_id="sel_img")
    
    async def callback(self, i: discord.Interaction):
        try:
            if not is_owner(i.user.id):
                return await i.response.send_message("❌ Owner only!", ephemeral=True)
            db.set_img(i.user.id, self.values[0])
            v = IMG_MODELS.get(self.values[0], ("?", "?", ""))
            await i.response.send_message(f"✅ Image: {v[0]} **{v[1]}**", ephemeral=True)
        except Exception as e:
            await i.response.send_message(f"❌ Error: {e}", ephemeral=True)

class ImgView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ImgSelect())

class DefaultSelect(ui.Select):
    def __init__(self):
        models = get_models()
        fast_models = ["groq", "cerebras", "sambanova", "cloudflare", "poll_free"]
        opts = [discord.SelectOption(label=models[m]["n"], value=m, emoji=models[m]["e"], description="Set default") for m in fast_models if m in models]
        if not opts:
            opts = [discord.SelectOption(label="No models", value="none")]
        super().__init__(placeholder="Set Default Model...", options=opts, custom_id="sel_default")
    
    async def callback(self, i: discord.Interaction):
        try:
            if not is_owner(i.user.id):
                return await i.response.send_message("❌ Owner only!", ephemeral=True)
            db.set_setting("public_default", self.values[0])
            models = get_models()
            m = models.get(self.values[0], {})
            await i.response.send_message(f"✅ Default: {m.get('e', '')} **{m.get('n', '')}**", ephemeral=True)
        except Exception as e:
            await i.response.send_message(f"❌ Error: {e}", ephemeral=True)

class DefaultView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(DefaultSelect())

class ShieldInfoSelect(ui.Select):
    def __init__(self):
        opts = [
            discord.SelectOption(label="Statistics", value="stats", emoji="📊"),
            discord.SelectOption(label="Sessions", value="sessions", emoji="🔄"),
            discord.SelectOption(label="Logs", value="logs", emoji="📋"),
            discord.SelectOption(label="Bans", value="bans", emoji="🚫"),
            discord.SelectOption(label="Whitelist", value="wl", emoji="✅"),
            discord.SelectOption(label="Suspended", value="sus", emoji="⏸️"),
            discord.SelectOption(label="Health", value="health", emoji="💚"),
            discord.SelectOption(label="Bot Stats", value="botstats", emoji="📈"),
            discord.SelectOption(label="Script", value="script", emoji="📜")
        ]
        super().__init__(placeholder="View Data...", options=opts, custom_id="sel_shield_info")
    
    async def callback(self, i: discord.Interaction):
        try:
            if not is_owner(i.user.id):
                return await i.response.send_message("❌ Owner only!", ephemeral=True)
            
            await i.response.defer(ephemeral=True)
            a = self.values[0]
            embed = discord.Embed(color=0x3498DB)
            
            if a == "stats":
                d = shield.stats()
                embed.title = "📊 Shield Statistics"
                if isinstance(d, dict) and d.get("success") is not False:
                    for k, v in d.items():
                        if k not in ["success", "error"]:
                            embed.add_field(name=str(k).replace("_", " ").title(), value=f"`{v}`", inline=True)
                    if len(embed.fields) == 0:
                        embed.description = "No stats available"
                else:
                    embed.description = f"❌ {d.get('error', 'No data')}"
            
            elif a == "sessions":
                d = shield.sessions()
                embed.title = "🔄 Active Sessions"
                if isinstance(d, dict) and "sessions" in d:
                    ss = d["sessions"]
                    if ss:
                        for idx, s in enumerate(ss[:10]):
                            embed.add_field(name=f"#{idx+1}", value=f"ID:`{str(s.get('id', '?'))[:15]}`\nUser:`{s.get('userId', '?')}`", inline=True)
                    else:
                        embed.description = "✅ No active sessions"
                else:
                    embed.description = f"❌ {d.get('error', 'No data')}"
            
            elif a == "logs":
                d = shield.logs()
                embed.title = "📋 Access Logs"
                if isinstance(d, dict) and "logs" in d:
                    ll = d["logs"]
                    if ll:
                        embed.description = "\n".join([f"• `{l.get('time', '?')[:16]}` {l.get('service', '?')} ({l.get('method', '?')})" for l in ll[:10]])
                    else:
                        embed.description = "✅ No logs"
                else:
                    embed.description = f"❌ {d.get('error', 'No data')}"
            
            elif a == "bans":
                d = shield.bans()
                embed.title = "🚫 Ban List"
                if isinstance(d, dict) and "bans" in d:
                    bb = d["bans"]
                    if bb:
                        for idx, b in enumerate(bb[:10]):
                            embed.add_field(name=f"#{b.get('id', idx+1)}", value=f"Type:`{b.get('type', '?')}`\nVal:`{str(b.get('value', '?'))[:15]}`", inline=True)
                    else:
                        embed.description = "✅ No bans"
                else:
                    embed.description = f"❌ {d.get('error', 'No data')}"
            
            elif a == "wl":
                d = shield.whitelist()
                embed.title = "✅ Whitelist"
                if isinstance(d, dict) and "whitelist" in d:
                    ww = d["whitelist"]
                    if ww:
                        for idx, w in enumerate(ww[:10]):
                            embed.add_field(name=f"#{idx+1}", value=f"Type:`{w.get('type', '?')}`\nVal:`{str(w.get('value', '?'))[:15]}`", inline=True)
                    else:
                        embed.description = "ℹ️ Empty"
                else:
                    embed.description = f"❌ {d.get('error', 'No data')}"
            
            elif a == "sus":
                d = shield.suspended()
                embed.title = "⏸️ Suspended"
                if isinstance(d, dict) and "suspended" in d:
                    ss = d["suspended"]
                    if ss:
                        for idx, s in enumerate(ss[:10]):
                            embed.add_field(name=f"#{idx+1}", value=f"Type:`{s.get('type', '?')}`\nVal:`{str(s.get('value', '?'))[:15]}`", inline=True)
                    else:
                        embed.description = "✅ None"
                else:
                    embed.description = f"❌ {d.get('error', 'No data')}"
            
            elif a == "health":
                d = shield.health()
                embed.title = "💚 Shield Status"
                embed.description = "✅ **ONLINE**" if d.get("success") else "❌ **OFFLINE**"
                embed.color = 0x2ECC71 if d.get("success") else 0xE74C3C
            
            elif a == "botstats":
                s = db.get_stats()
                embed.title = "📈 Bot Statistics"
                embed.add_field(name="Total Commands", value=f"`{s['total']}`", inline=True)
                embed.add_field(name="Today", value=f"`{s['today']}`", inline=True)
                embed.add_field(name="Unique Users", value=f"`{s['users']}`", inline=True)
                if s['top']:
                    embed.add_field(name="Top Commands", value="\n".join([f"`{c[0]}`: {c[1]}" for c in s['top']]), inline=False)
            
            elif a == "script":
                d = shield.script()
                if d.get("success") and d.get("script"):
                    f = discord.File(io.BytesIO(d["script"].encode()), "loader.lua")
                    return await i.followup.send("📜 **Loader Script:**", file=f, ephemeral=True)
                else:
                    embed.title = "📜 Script"
                    embed.description = f"❌ {d.get('error', 'Not available')}"
            
            await i.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            try:
                await i.followup.send(f"❌ Error: {e}", ephemeral=True)
            except:
                pass

class ShieldActionSelect(ui.Select):
    def __init__(self):
        opts = [
            discord.SelectOption(label="Clear Sessions", value="clear_s", emoji="🧹"),
            discord.SelectOption(label="Clear Logs", value="clear_l", emoji="🗑️"),
            discord.SelectOption(label="Clear Cache", value="clear_c", emoji="💾")
        ]
        super().__init__(placeholder="Quick Actions...", options=opts, custom_id="sel_shield_action")
    
    async def callback(self, i: discord.Interaction):
        try:
            if not is_owner(i.user.id):
                return await i.response.send_message("❌ Owner only!", ephemeral=True)
            await i.response.defer(ephemeral=True)
            a = self.values[0]
            if a == "clear_s":
                r = shield.clear_sessions()
                msg = "Sessions cleared"
            elif a == "clear_l":
                r = shield.clear_logs()
                msg = "Logs cleared"
            elif a == "clear_c":
                r = shield.clear_cache()
                msg = "Cache cleared"
            else:
                r = {"success": False}
                msg = "Unknown"
            await i.followup.send(f"✅ {msg}!" if r.get("success") is not False else f"❌ Failed: {r.get('error', 'Unknown')}", ephemeral=True)
        except Exception as e:
            await i.followup.send(f"❌ Error: {e}", ephemeral=True)

class ShieldView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ShieldInfoSelect())
        self.add_item(ShieldActionSelect())

class ShieldManageSelect(ui.Select):
    def __init__(self):
        opts = [
            discord.SelectOption(label="Ban Player", value="ban_p", emoji="👤"),
            discord.SelectOption(label="Ban HWID", value="ban_h", emoji="💻"),
            discord.SelectOption(label="Ban IP", value="ban_i", emoji="🌐"),
            discord.SelectOption(label="Unban", value="unban", emoji="🔓"),
            discord.SelectOption(label="Add Whitelist", value="add_wl", emoji="➕"),
            discord.SelectOption(label="Remove Whitelist", value="rem_wl", emoji="➖"),
            discord.SelectOption(label="Suspend", value="sus", emoji="⏸️"),
            discord.SelectOption(label="Unsuspend", value="unsus", emoji="▶️"),
            discord.SelectOption(label="Kill Session", value="kill", emoji="💀")
        ]
        super().__init__(placeholder="Management...", options=opts, custom_id="sel_shield_manage")
    
    async def callback(self, i: discord.Interaction):
        if not is_owner(i.user.id):
            return await i.response.send_message("❌ Owner only!", ephemeral=True)
        
        a = self.values[0]
        titles = {
            "ban_p": "Ban Player", "ban_h": "Ban HWID", "ban_i": "Ban IP",
            "unban": "Unban", "add_wl": "Add Whitelist", "rem_wl": "Remove Whitelist",
            "sus": "Suspend", "unsus": "Unsuspend", "kill": "Kill Session"
        }
        
        class ActionModal(ui.Modal, title=titles.get(a, "Action")):
            val = ui.TextInput(label="Value", placeholder="ID/HWID/IP...", required=True)
            reason = ui.TextInput(label="Reason", placeholder="Optional", required=False, default="Via Discord")
            
            def __init__(s, act):
                super().__init__()
                s.act = act
            
            async def on_submit(s, mi: discord.Interaction):
                v = s.val.value.strip()
                r = s.reason.value.strip() or "Via Discord"
                res = {"success": False}
                
                if s.act == "ban_p":
                    res = shield.add_ban(pid=v, reason=r)
                elif s.act == "ban_h":
                    res = shield.add_ban(hwid=v, reason=r)
                elif s.act == "ban_i":
                    res = shield.add_ban(ip=v, reason=r)
                elif s.act == "unban":
                    res = shield.rem_ban(v)
                elif s.act == "add_wl":
                    p = v.split(":", 1)
                    res = shield.add_wl(p[0] if len(p) > 1 else "userId", p[-1])
                elif s.act == "rem_wl":
                    p = v.split(":", 1)
                    res = shield.rem_wl(p[0] if len(p) > 1 else "userId", p[-1])
                elif s.act == "sus":
                    p = v.split(":", 1)
                    res = shield.suspend(p[0] if len(p) > 1 else "userId", p[-1], r)
                elif s.act == "unsus":
                    p = v.split(":", 1)
                    res = shield.unsuspend(p[0] if len(p) > 1 else "userId", p[-1])
                elif s.act == "kill":
                    res = shield.kill(v, r)
                
                await mi.response.send_message(
                    f"✅ Done: `{v}`" if res.get("success") is not False else f"❌ {res.get('error', 'Failed')}",
                    ephemeral=True
                )
        
        await i.response.send_modal(ActionModal(a))

class ShieldManageView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ShieldManageSelect())

# ============== UTILITIES ==============
def split_msg(txt, lim=1950):
    if not txt:
        return [""]
    chunks = []
    while len(txt) > lim:
        sp = txt.rfind('\n', 0, lim)
        if sp == -1:
            sp = lim
        chunks.append(txt[:sp])
        txt = txt[sp:].lstrip()
    if txt:
        chunks.append(txt)
    return chunks

async def send_resp(ch, content):
    for c in split_msg(content):
        await ch.send(c)

# ============== BOT EVENTS ==============
@bot.event
async def on_ready():
    logger.info(f"Bot ready: {bot.user} | Servers: {len(bot.guilds)}")
    # Initial sync with config panel
    fetch_panel_config()
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=f"{PREFIX}help"))

@bot.event
async def on_command_error(ctx, err):
    if isinstance(err, commands.CommandNotFound):
        return
    logger.error(f"Cmd error: {err}")

@bot.event
async def on_message(msg):
    if msg.author.bot:
        return
    
    if bot.user.mentioned_in(msg) and not msg.mention_everyone:
        content = msg.content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '').strip()
        if content:
            if db.banned(msg.author.id):
                return
            ok, rem = rl.check(msg.author.id, "ai", 5)
            if not ok:
                return await msg.channel.send(f"⏳ Wait {rem:.0f}s", delete_after=3)
            async with msg.channel.typing():
                resp, _ = ask_ai(content, msg.author.id)
                await send_resp(msg.channel, resp)
                db.stat("ai", msg.author.id)
            try:
                await msg.delete()
            except:
                pass
        return
    
    await bot.process_commands(msg)

# ============== COMMANDS ==============
@bot.command(name="ai", aliases=["a", "chat"])
async def cmd_ai(ctx, *, prompt: str = None):
    if db.banned(ctx.author.id):
        return
    if not prompt:
        return await ctx.send(f"Usage: `{PREFIX}ai <question>`", delete_after=10)
    ok, rem = rl.check(ctx.author.id, "ai", 5)
    if not ok:
        return await ctx.send(f"⏳ Wait {rem:.0f}s", delete_after=3)
    async with ctx.typing():
        resp, _ = ask_ai(prompt, ctx.author.id)
        await send_resp(ctx.channel, resp)
        db.stat("ai", ctx.author.id)
    try:
        await ctx.message.delete()
    except:
        pass

@bot.command(name="model", aliases=["m"])
async def cmd_model(ctx):
    if not is_owner(ctx.author.id):
        curr = get_public_default()
        models = get_models()
        m = models.get(curr, {})
        return await ctx.send(f"ℹ️ Model: {m.get('e', '')} **{m.get('n', '')}** (Public)", delete_after=10)
    
    curr = db.get_model(ctx.author.id)
    models = get_models()
    m = models.get(curr, {})
    
    # Count categories
    categories = list(set(md["c"] for md in models.values()))
    cat_text = "\n".join([f"• **{cat.title()}** - {sum(1 for md in models.values() if md['c'] == cat)} models" for cat in categories])
    
    embed = discord.Embed(
        title="🤖 Model Selection",
        description=f"**Current:** {m.get('e', '')} {m.get('n', '')}\n\n**Categories:**\n{cat_text}",
        color=0x5865F2
    )
    await ctx.send(embed=embed, view=ModelView())
    try:
        await ctx.message.delete()
    except:
        pass

@bot.command(name="setdefault", aliases=["sd"])
async def cmd_sd(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!", delete_after=5)
    curr = get_public_default()
    models = get_models()
    m = models.get(curr, {})
    embed = discord.Embed(title="🌍 Set Public Default", description=f"**Current:** {m.get('e', '')} {m.get('n', '')}", color=0x3498DB)
    await ctx.send(embed=embed, view=DefaultView())
    try:
        await ctx.message.delete()
    except:
        pass

@bot.command(name="imagine", aliases=["img", "image"])
async def cmd_img(ctx, *, prompt: str = None):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!", delete_after=5)
    if db.banned(ctx.author.id):
        return
    if not prompt:
        return await ctx.send(f"Usage: `{PREFIX}img <prompt>`", delete_after=5)
    ok, rem = rl.check(ctx.author.id, "img", 15)
    if not ok:
        return await ctx.send(f"⏳ Wait {rem:.0f}s", delete_after=3)
    
    model = db.get_img(ctx.author.id)
    info = IMG_MODELS.get(model, ("🎨", "Flux", ""))
    st = await ctx.send(f"🎨 Generating with {info[0]} **{info[1]}**...")
    
    try:
        data, err = await gen_image(prompt, model)
        if data:
            f = discord.File(io.BytesIO(data), "image.png")
            embed = discord.Embed(title=f"🎨 {prompt[:80]}", color=0x5865F2)
            embed.set_image(url="attachment://image.png")
            embed.set_footer(text=f"{info[0]} {info[1]}")
            await ctx.send(embed=embed, file=f)
            await st.delete()
            db.stat("img", ctx.author.id)
        else:
            await st.edit(content=f"❌ Failed: {err}")
    except Exception as e:
        await st.edit(content=f"❌ Error: {str(e)[:50]}")
    
    try:
        await ctx.message.delete()
    except:
        pass

@bot.command(name="imgmodel", aliases=["im"])
async def cmd_im(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!", delete_after=5)
    curr = db.get_img(ctx.author.id)
    info = IMG_MODELS.get(curr, ("?", "?", ""))
    embed = discord.Embed(title="🎨 Image Model", description=f"**Current:** {info[0]} {info[1]}", color=0x5865F2)
    for k, v in IMG_MODELS.items():
        embed.add_field(name=f"{v[0]} {v[1]}", value=f"{'✅' if k == curr else '⚪'} {v[2]}", inline=True)
    await ctx.send(embed=embed, view=ImgView())
    try:
        await ctx.message.delete()
    except:
        pass

@bot.command(name="dump", aliases=["dl"])
async def cmd_dump(ctx, url: str = None, *, flags: str = ""):
    if db.banned(ctx.author.id):
        return
    if not url:
        return await ctx.send(f"Usage: `{PREFIX}dump <url>`", delete_after=5)
    ok, rem = rl.check(ctx.author.id, "dump", 10)
    if not ok:
        return await ctx.send(f"⏳ Wait {rem:.0f}s", delete_after=3)
    if not url.startswith("http"):
        url = "https://" + url
    
    st = await ctx.send("🔄 Dumping...")
    result = dumper.dump(url, "--nocache" not in flags)
    
    if result["success"]:
        content = result["content"]
        ext = "lua" if "local " in content[:500] else "html" if "<html" in content[:200].lower() else "txt"
        f = discord.File(io.BytesIO(content.encode()), f"dump.{ext}")
        await ctx.send(f"✅ Method: `{result['method']}` | Size: `{len(content):,}` bytes", file=f)
        await st.delete()
        db.stat("dump", ctx.author.id)
    else:
        await st.edit(content=f"❌ {result.get('error', 'Failed')}")

@bot.command(name="shield", aliases=["sh"])
async def cmd_shield(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!", delete_after=5)
    st = shield.health()
    embed = discord.Embed(title="🛡️ Shield Panel", color=0x2ECC71 if st.get("success") else 0xE74C3C)
    embed.add_field(name="Status", value="🟢 ONLINE" if st.get("success") else "🔴 OFFLINE", inline=True)
    embed.add_field(name="URL", value=f"`{SHIELD_URL[:25]}...`" if len(SHIELD_URL) > 25 else f"`{SHIELD_URL or 'Not Set'}`", inline=True)
    await ctx.send(embed=embed, view=ShieldView())

@bot.command(name="shieldm", aliases=["sm"])
async def cmd_sm(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!", delete_after=5)
    embed = discord.Embed(title="⚙️ Shield Management", color=0xE74C3C)
    embed.add_field(name="Format", value="`type:value`\nEx: `hwid:ABC123`", inline=True)
    embed.add_field(name="Types", value="`userId`, `hwid`, `ip`", inline=True)
    await ctx.send(embed=embed, view=ShieldManageView())

@bot.command(name="sync", aliases=["resync"])
async def cmd_sync(ctx):
    """Force sync config from panel"""
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!", delete_after=5)
    
    st = await ctx.send("🔄 Syncing config from panel...")
    
    config = fetch_panel_config(force=True)
    if config and config.get("last_fetch", 0) > 0:
        embed = discord.Embed(title="✅ Config Synced", color=0x2ECC71)
        embed.add_field(name="🔑 API Keys", value=f"`{len(config.get('keys', {}))}` loaded", inline=True)
        embed.add_field(name="🤖 Models", value=f"`{len(config.get('models', {}))}` loaded", inline=True)
        embed.add_field(name="⚙️ Settings", value=f"`{len(config.get('settings', {}))}` loaded", inline=True)
        await st.edit(content=None, embed=embed)
    else:
        await st.edit(content="❌ Failed to sync. Check CONFIG_PANEL_URL and CONFIG_BOT_SECRET")
    
    try:
        await ctx.message.delete()
    except:
        pass

@bot.command(name="clear", aliases=["reset"])
async def cmd_clear(ctx):
    mem.clear(ctx.author.id)
    await ctx.send("🧹 Memory cleared!", delete_after=5)
    try:
        await ctx.message.delete()
    except:
        pass

@bot.command(name="ping", aliases=["p"])
async def cmd_ping(ctx):
    curr = db.get_model(ctx.author.id) if is_owner(ctx.author.id) else get_public_default()
    models = get_models()
    m = models.get(curr, {})
    embed = discord.Embed(title="🏓 Pong!", color=0x2ECC71)
    embed.add_field(name="Latency", value=f"`{round(bot.latency * 1000)}ms`", inline=True)
    embed.add_field(name="Model", value=f"{m.get('e', '')} {m.get('n', '')}", inline=True)
    embed.add_field(name="Role", value=f"`{'Owner' if is_owner(ctx.author.id) else 'Public'}`", inline=True)
    await ctx.send(embed=embed)

@bot.command(name="status")
async def cmd_status(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!", delete_after=5)
    
    embed = discord.Embed(title="📊 Status", color=0x5865F2)
    
    # Config Panel Status (Web 2)
    config = fetch_panel_config()
    panel_ok = config is not None and config.get("last_fetch", 0) > 0
    
    panel_text = f"{'✅ Connected' if panel_ok else '❌ Not Connected'}"
    if panel_ok:
        panel_text += f"\n`{len(config.get('keys', {}))}` keys, `{len(config.get('models', {}))}` models"
    if CONFIG_PANEL_URL:
        panel_text += f"\n`{CONFIG_PANEL_URL[:30]}...`"
    else:
        panel_text = "⚪ Not Configured"
    
    embed.add_field(name="🌐 Config Panel (Web 2)", value=panel_text, inline=False)
    
    # Shield Status (Web 1)
    shield_ok = shield.health().get("success", False)
    embed.add_field(
        name="🛡️ Shield (Web 1)",
        value=f"{'✅ Online' if shield_ok else '❌ Offline'}" + (f"\n`{SHIELD_URL[:30]}...`" if SHIELD_URL else "\n⚪ Not Configured"),
        inline=False
    )
    
    # API Keys (from all sources)
    keys = [
        ("Groq", "groq"), ("Cerebras", "cerebras"), ("SambaNova", "sambanova"),
        ("Cloudflare", "cloudflare_token"), ("Cohere", "cohere"), ("Mistral", "mistral"),
        ("Together", "together"), ("OpenRouter", "openrouter"), ("Tavily", "tavily"),
        ("HuggingFace", "huggingface"), ("Moonshot", "moonshot")
    ]
    st = "\n".join([f"{'✅' if get_api_key(k) else '❌'} {n}" for n, k in keys])
    embed.add_field(name="🔑 API Keys", value=st, inline=True)
    
    # Config
    models = get_models()
    embed.add_field(
        name="⚙️ Config",
        value=f"**Default:** `{get_public_default()}`\n**Prefix:** `{PREFIX}`\n**Models:** `{len(models)}`\n**Servers:** `{len(bot.guilds)}`",
        inline=True
    )
    
    await ctx.send(embed=embed)

@bot.command(name="testai")
async def cmd_testai(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!", delete_after=5)
    
    st = await ctx.send("🔄 Testing all providers...")
    test = [{"role": "user", "content": "Say OK"}]
    results = []
    
    providers = [
        ("Groq", lambda: call_groq(test), get_api_key("groq")),
        ("Cerebras", lambda: call_cerebras(test), get_api_key("cerebras")),
        ("SambaNova", lambda: call_sambanova(test), get_api_key("sambanova")),
        ("CF", lambda: call_cloudflare(test), get_api_key("cloudflare_token")),
        ("Cohere", lambda: call_cohere(test), get_api_key("cohere")),
        ("Mistral", lambda: call_mistral(test), get_api_key("mistral")),
        ("Together", lambda: call_together(test), get_api_key("together")),
        ("OR", lambda: call_openrouter(test, "or_gemini"), get_api_key("openrouter")),
        ("Tavily", lambda: call_tavily(test), get_api_key("tavily")),
        ("Poll", lambda: call_pollinations(test, "poll_free"), True)
    ]
    
    for n, f, k in providers:
        if not k:
            results.append(f"⚪{n}")
            continue
        try:
            r = f()
            results.append(f"✅{n}" if r else f"❌{n}")
        except:
            results.append(f"❌{n}")
    
    embed = discord.Embed(title="🧪 AI Test", description=" | ".join(results), color=0x5865F2)
    await st.edit(content=None, embed=embed)

@bot.command(name="blacklist", aliases=["bl", "ban"])
async def cmd_bl(ctx, action: str = None, user: discord.User = None):
    if not is_owner(ctx.author.id):
        return
    if not action or not user:
        return await ctx.send(f"Usage: `{PREFIX}bl add/rem @user`", delete_after=10)
    if action in ["add", "ban"]:
        db.ban(user.id)
        await ctx.send(f"✅ Banned {user}", delete_after=5)
    elif action in ["rem", "remove", "unban"]:
        db.unban(user.id)
        await ctx.send(f"✅ Unbanned {user}", delete_after=5)

@bot.command(name="allowuser", aliases=["au"])
async def cmd_au(ctx, user: discord.User = None, *, models: str = None):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!", delete_after=5)
    if not user:
        return await ctx.send(f"Usage: `{PREFIX}au @user model1,model2` or `reset`", delete_after=10)
    if not models:
        curr = db.get_allowed(user.id)
        return await ctx.send(f"📋 {user.mention}: `{','.join(curr) or 'None'}`", delete_after=10)
    if models.lower() == "reset":
        db.rem_allowed(user.id)
        return await ctx.send(f"✅ Reset {user.mention}", delete_after=5)
    
    all_models = get_all_model_ids()
    valid = [m.strip() for m in models.split(",") if m.strip() in all_models]
    if not valid:
        return await ctx.send("❌ Invalid models", delete_after=5)
    db.set_allowed(user.id, valid)
    await ctx.send(f"✅ {user.mention}: `{','.join(valid)}`", delete_after=5)

@bot.command(name="stats")
async def cmd_stats(ctx):
    s = db.get_stats()
    embed = discord.Embed(title="📈 Bot Statistics", color=0x5865F2)
    embed.add_field(name="Total", value=f"`{s['total']}`", inline=True)
    embed.add_field(name="Today", value=f"`{s['today']}`", inline=True)
    embed.add_field(name="Users", value=f"`{s['users']}`", inline=True)
    if s['top']:
        embed.add_field(name="Top Commands", value="\n".join([f"`{c[0]}`: {c[1]}" for c in s['top']]), inline=False)
    await ctx.send(embed=embed)

@bot.command(name="help", aliases=["h"])
async def cmd_help(ctx):
    embed = discord.Embed(title="📚 Help", color=0x5865F2)
    embed.add_field(name="💬 AI", value=f"`{PREFIX}ai <text>`\n`@{bot.user.name} <text>`", inline=False)
    
    if is_owner(ctx.author.id):
        embed.add_field(name="🤖 Models", value=f"`{PREFIX}m` - Select\n`{PREFIX}sd` - Set default", inline=True)
        embed.add_field(name="🎨 Image", value=f"`{PREFIX}img <prompt>`\n`{PREFIX}im` - Select", inline=True)
        embed.add_field(name="🛡️ Shield", value=f"`{PREFIX}sh` - Panel\n`{PREFIX}sm` - Manage", inline=True)
        embed.add_field(name="🔄 Sync", value=f"`{PREFIX}sync` - Resync config", inline=True)
        embed.add_field(name="⚙️ Admin", value=f"`{PREFIX}status` `{PREFIX}testai`\n`{PREFIX}bl` `{PREFIX}au` `{PREFIX}stats`", inline=True)
    
    embed.add_field(name="🔧 Utility", value=f"`{PREFIX}dump <url>`\n`{PREFIX}clear` `{PREFIX}ping`", inline=True)
    await ctx.send(embed=embed)

# ============== FLASK HEALTH CHECK ==============
def run_flask():
    from flask import Flask, jsonify
    app = Flask(__name__)
    
    @app.route('/')
    def home():
        return f"Bot {bot.user} is running!" if bot.user else "Bot starting..."
    
    @app.route('/health')
    def health():
        return jsonify({"status": "ok", "bot": str(bot.user) if bot.user else "starting"})
    
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# ============== MAIN ==============
if __name__ == "__main__":
    keep_alive()
    PORT = int(os.getenv("PORT", 8080))
    ADMIN_KEY = os.getenv("WEB_ADMIN_KEY", os.getenv("ADMIN_KEY", "admin123"))
    
    if HAS_WEB_PANEL and start_web_panel:
        start_web_panel(host="0.0.0.0", port=PORT, admin_key=ADMIN_KEY)
        print(f"🌐 Web Panel: http://0.0.0.0:{PORT}?key={ADMIN_KEY}")
    else:
        threading.Thread(target=run_flask, daemon=True).start()
        print(f"🌐 Health Check: http://0.0.0.0:{PORT}")
    
    print("=" * 50)
    print("🚀 Bot Starting...")
    print(f"👑 Owners: {OWNER_IDS}")
    print(f"🌍 Default: {get_public_default()}")
    print(f"🛡️ Shield (Web 1): {'✅' if SHIELD_URL else '❌'}")
    print(f"🌐 Config Panel (Web 2): {'✅' if CONFIG_PANEL_URL else '❌'}")
    print("-" * 50)
    for n, k in [("Groq", "groq"), ("Cerebras", "cerebras"), ("SambaNova", "sambanova"), 
                  ("Cloudflare", "cloudflare_token"), ("OpenRouter", "openrouter"), 
                  ("Cohere", "cohere"), ("Mistral", "mistral"), ("Together", "together"), ("Tavily", "tavily")]:
        print(f"   {'✅' if get_api_key(k) else '❌'} {n}")
    print("=" * 50)
    
    bot.run(DISCORD_TOKEN, log_handler=None)
