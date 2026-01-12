import discord,os,io,re,time,json,logging,sqlite3,random,threading,hashlib,asyncio
from collections import defaultdict
from dataclasses import dataclass
from discord.ext import commands
from discord import ui
from urllib.parse import quote
try:from keep_alive import keep_alive
except:keep_alive=lambda:None
logging.basicConfig(level=logging.INFO,format='%(asctime)s|%(levelname)s|%(message)s')
logger=logging.getLogger(__name__)
DISCORD_TOKEN=os.getenv("DISCORD_TOKEN")
KEY_GROQ=os.getenv("GROQ_API_KEY")
KEY_OPENROUTER=os.getenv("OPENROUTER_API_KEY")
KEY_CEREBRAS=os.getenv("CEREBRAS_API_KEY")
KEY_SAMBANOVA=os.getenv("SAMBANOVA_API_KEY")
KEY_COHERE=os.getenv("COHERE_API_KEY")
CF_ACCOUNT_ID=os.getenv("CLOUDFLARE_ACCOUNT_ID")
CF_API_TOKEN=os.getenv("CLOUDFLARE_API_TOKEN")
KEY_TOGETHER=os.getenv("TOGETHER_API_KEY")
KEY_POLLINATIONS=os.getenv("POLLINATIONS_API_KEY")
KEY_TAVILY=os.getenv("TAVILY_API_KEY")
KEY_MISTRAL=os.getenv("MISTRAL_API_KEY")
KEY_REPLICATE=os.getenv("REPLICATE_API_TOKEN")
KEY_HUGGINGFACE=os.getenv("HUGGINGFACE_API_KEY")
KEY_MOONSHOT=os.getenv("MOONSHOT_API_KEY")
SHIELD_URL=os.getenv("SHIELD_URL","").rstrip("/")
SHIELD_ADMIN_KEY=os.getenv("SHIELD_ADMIN_KEY","")
OWNER_IDS=[int(x)for x in os.getenv("OWNER_IDS","0").split(",")if x.isdigit()]
PREFIX=os.getenv("BOT_PREFIX",".")
if not DISCORD_TOKEN:print("❌ DISCORD_TOKEN Missing");exit(1)
intents=discord.Intents.default();intents.message_content=True
bot=commands.Bot(command_prefix=PREFIX,intents=intents,help_command=None)
_groq=_requests=_curl=_cloudscraper=None
def get_groq():
    global _groq
    if _groq is None and KEY_GROQ:
        try:from groq import Groq;_groq=Groq(api_key=KEY_GROQ)
        except:pass
    return _groq
def get_requests():
    global _requests
    if _requests is None:import requests;_requests=requests
    return _requests
def get_curl():
    global _curl
    if _curl is None:
        try:from curl_cffi import requests as r;_curl=r
        except:_curl=None
    return _curl
def get_cloudscraper():
    global _cloudscraper
    if _cloudscraper is None:
        try:import cloudscraper;_cloudscraper=cloudscraper.create_scraper(browser={'browser':'chrome','platform':'windows','mobile':False})
        except:_cloudscraper=None
    return _cloudscraper
class ShieldAPI:
    def __init__(s,url,key):s.url=url;s.key=key;s.timeout=25
    def _h(s):return{"x-admin-key":s.key,"Content-Type":"application/json"}
    def _get(s,ep):
        if not s.url or not s.key:return{"success":False,"error":"Not configured"}
        try:r=get_requests().get(f"{s.url}{ep}",headers=s._h(),timeout=s.timeout);return r.json()if r.status_code==200 else{"success":False,"error":f"HTTP {r.status_code}"}
        except Exception as e:return{"success":False,"error":str(e)[:50]}
    def _post(s,ep,d=None):
        if not s.url or not s.key:return{"success":False,"error":"Not configured"}
        try:r=get_requests().post(f"{s.url}{ep}",headers=s._h(),json=d or{},timeout=s.timeout);return r.json()if r.status_code in[200,201]else{"success":False,"error":f"HTTP {r.status_code}"}
        except Exception as e:return{"success":False,"error":str(e)[:50]}
    def _del(s,ep):
        if not s.url or not s.key:return{"success":False,"error":"Not configured"}
        try:r=get_requests().delete(f"{s.url}{ep}",headers=s._h(),timeout=s.timeout);return r.json()if r.status_code==200 else{"success":False,"error":f"HTTP {r.status_code}"}
        except Exception as e:return{"success":False,"error":str(e)[:50]}
    def stats(s):return s._get("/api/admin/stats")
    def sessions(s):return s._get("/api/admin/sessions")
    def logs(s):return s._get("/api/admin/logs")
    def bans(s):return s._get("/api/admin/bans")
    def whitelist(s):return s._get("/api/admin/whitelist")
    def suspended(s):return s._get("/api/admin/suspended")
    def script(s):return s._get("/api/admin/script")
    def keepalive(s):
        try:r=get_requests().get(f"{s.url}/api/keepalive",timeout=10);return r.json()if r.status_code==200 else{"success":False,"error":f"HTTP {r.status_code}"}
        except Exception as e:return{"success":False,"error":str(e)[:50]}
    def add_ban(s,hwid=None,ip=None,pid=None,reason="Discord"):return s._post("/api/admin/bans",{"hwid":hwid,"ip":ip,"playerId":pid,"reason":reason})
    def remove_ban(s,bid):return s._del(f"/api/admin/bans/{bid}")
    def add_wl(s,t,v):return s._post("/api/admin/whitelist",{"type":t,"value":v})
    def remove_wl(s,t,v):return s._post("/api/admin/whitelist/remove",{"type":t,"value":v})
    def suspend(s,t,v,r="Discord",d=None):return s._post("/api/admin/suspend",{"type":t,"value":v,"reason":r,"duration":d})
    def unsuspend(s,t,v):return s._post("/api/admin/unsuspend",{"type":t,"value":v})
    def kill(s,sid,r="Discord"):return s._post("/api/admin/kill-session",{"sessionId":sid,"reason":r})
    def clear_sessions(s):return s._post("/api/admin/sessions/clear")
    def clear_logs(s):return s._post("/api/admin/logs/clear")
    def clear_cache(s):return s._post("/api/admin/cache/clear")
shield=ShieldAPI(SHIELD_URL,SHIELD_ADMIN_KEY)
class Database:
    def __init__(s,path="bot.db"):
        s.conn=sqlite3.connect(path,check_same_thread=False);s.lock=threading.Lock()
        s.conn.executescript('''CREATE TABLE IF NOT EXISTS user_prefs(uid INTEGER PRIMARY KEY,model TEXT DEFAULT "groq",img_model TEXT DEFAULT "flux");CREATE TABLE IF NOT EXISTS bot_settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE IF NOT EXISTS stats(id INTEGER PRIMARY KEY,cmd TEXT,uid INTEGER,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS blacklist(uid INTEGER PRIMARY KEY);CREATE TABLE IF NOT EXISTS allowed_users(uid INTEGER PRIMARY KEY,allowed_models TEXT DEFAULT "groq");CREATE TABLE IF NOT EXISTS dump_cache(url TEXT PRIMARY KEY,content TEXT,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);''')
        s._init()
    def _init(s):
        with s.lock:
            r=s.conn.execute('SELECT value FROM bot_settings WHERE key="public_default"').fetchone()
            if not r:s.conn.execute('INSERT INTO bot_settings VALUES("public_default","groq")');s.conn.commit()
    def get_setting(s,k):
        with s.lock:r=s.conn.execute('SELECT value FROM bot_settings WHERE key=?',(k,)).fetchone();return r[0]if r else None
    def set_setting(s,k,v):
        with s.lock:s.conn.execute('INSERT OR REPLACE INTO bot_settings VALUES(?,?)',(k,v));s.conn.commit()
    def get_model(s,uid):
        with s.lock:r=s.conn.execute('SELECT model FROM user_prefs WHERE uid=?',(uid,)).fetchone();return r[0]if r else"groq"
    def set_model(s,uid,m):
        with s.lock:s.conn.execute('INSERT OR REPLACE INTO user_prefs(uid,model,img_model) VALUES(?,?,COALESCE((SELECT img_model FROM user_prefs WHERE uid=?),"flux"))',(uid,m,uid));s.conn.commit()
    def get_img_model(s,uid):
        with s.lock:r=s.conn.execute('SELECT img_model FROM user_prefs WHERE uid=?',(uid,)).fetchone();return r[0]if r else"flux"
    def set_img_model(s,uid,m):
        with s.lock:s.conn.execute('INSERT OR REPLACE INTO user_prefs(uid,model,img_model) VALUES(?,COALESCE((SELECT model FROM user_prefs WHERE uid=?),"groq"),?)',(uid,uid,m));s.conn.commit()
    def stat(s,cmd,uid):
        with s.lock:s.conn.execute('INSERT INTO stats(cmd,uid) VALUES(?,?)',(cmd,uid));s.conn.commit()
    def banned(s,uid):
        with s.lock:return s.conn.execute('SELECT 1 FROM blacklist WHERE uid=?',(uid,)).fetchone()is not None
    def add_bl(s,uid):
        with s.lock:s.conn.execute('INSERT OR IGNORE INTO blacklist VALUES(?)',(uid,));s.conn.commit()
    def rem_bl(s,uid):
        with s.lock:s.conn.execute('DELETE FROM blacklist WHERE uid=?',(uid,));s.conn.commit()
    def cache_dump(s,url,c):
        with s.lock:h=hashlib.md5(url.encode()).hexdigest();s.conn.execute('INSERT OR REPLACE INTO dump_cache VALUES(?,?,CURRENT_TIMESTAMP)',(h,c[:500000]));s.conn.commit()
    def get_cache(s,url):
        with s.lock:h=hashlib.md5(url.encode()).hexdigest();r=s.conn.execute('SELECT content FROM dump_cache WHERE url=? AND ts>datetime("now","-1 hour")',(h,)).fetchone();return r[0]if r else None
db=Database()
class RateLimiter:
    def __init__(s):s.cd=defaultdict(lambda:defaultdict(float));s.lock=threading.Lock()
    def check(s,uid,cmd,t=5):
        with s.lock:
            now=time.time()
            if now-s.cd[uid][cmd]<t:return False,t-(now-s.cd[uid][cmd])
            s.cd[uid][cmd]=now;return True,0
rl=RateLimiter()
@dataclass
class Msg:role:str;content:str;ts:float
class Memory:
    def __init__(s):s.data=defaultdict(list);s.lock=threading.Lock()
    def add(s,uid,role,c):
        with s.lock:
            now=time.time();s.data[uid]=[m for m in s.data[uid]if now-m.ts<1800]
            s.data[uid].append(Msg(role,c[:2000],now))
            if len(s.data[uid])>20:s.data[uid]=s.data[uid][-20:]
    def get(s,uid):
        with s.lock:now=time.time();s.data[uid]=[m for m in s.data[uid]if now-m.ts<1800];return[{"role":m.role,"content":m.content}for m in s.data[uid]]
    def clear(s,uid):
        with s.lock:s.data[uid]=[]
mem=Memory()
SYSTEM_PROMPT='''You are an elite AI assistant with capabilities rivaling the most advanced AI systems (Claude Opus 4.5, GPT-5.2, Gemini 3 Pro). Your cognitive architecture integrates:

**ANALYTICAL FRAMEWORK:**
- Multi-layered reasoning: Surface → Deep → Meta-cognitive analysis
- Systematic decomposition of complex problems into manageable components
- Cross-domain knowledge synthesis with precise contextual application
- Probabilistic thinking with explicit uncertainty quantification

**RESPONSE METHODOLOGY:**
1. COMPREHEND: Parse intent, context, implicit requirements, and edge cases
2. ANALYZE: Apply structured reasoning, consider multiple perspectives
3. SYNTHESIZE: Integrate insights into coherent, actionable responses
4. VALIDATE: Self-check for accuracy, completeness, logical consistency
5. OPTIMIZE: Refine for clarity, conciseness, and maximum utility

**CORE DIRECTIVES:**
- Provide substantive, well-reasoned answers with clear logical progression
- Acknowledge limitations and uncertainties explicitly when present
- Offer nuanced perspectives while maintaining decisive recommendations
- Adapt communication style to user expertise level
- Prioritize accuracy over speed; depth over superficiality

**LANGUAGE PROTOCOL:**
- Default: Bahasa Indonesia (unless user specifies otherwise)
- Technical terms: Preserve original with Indonesian explanation when helpful
- Tone: Professional yet approachable; authoritative yet humble

You think step-by-step, verify your reasoning, and deliver responses that demonstrate genuine intellectual engagement with every query.'''
OR_MODELS={"or_llama":"meta-llama/llama-3.3-70b-instruct:free","or_gemini":"google/gemini-2.0-flash-exp:free","or_qwen":"qwen/qwen-2.5-72b-instruct:free","or_deepseek":"deepseek/deepseek-chat:free","or_mistral":"mistralai/mistral-nemo:free"}
POLL_TEXT={"p_gpt":"openai-large","p_claude":"claude-hybridspace","p_gemini":"gemini","p_deepseek":"deepseek","p_qwen":"qwen-72b","p_llama":"llama-3.3-70b"}
POLL_IMG={"flux":"flux","flux_pro":"flux-pro","turbo":"turbo","dalle":"dall-e-3","sdxl":"sdxl"}
MODELS_STABLE=["groq","cerebras","cloudflare","sambanova","tavily","poll_free"]
MODELS_EXPERIMENTAL=["cohere","mistral","moonshot","huggingface","together","replicate"]
MODELS_OPENROUTER=["or_llama","or_gemini","or_qwen","or_deepseek","or_mistral"]
MODELS_POLLINATIONS=["p_gpt","p_claude","p_gemini","p_deepseek","p_qwen","p_llama"]
ALL_MODELS=MODELS_STABLE+MODELS_EXPERIMENTAL+MODELS_OPENROUTER+MODELS_POLLINATIONS
MODEL_INFO={
    "groq":("⚡","Groq","Llama 3.3 70B Versatile","stable"),
    "cerebras":("🧠","Cerebras","Llama 3.3 70B Fast","stable"),
    "cloudflare":("☁️","Cloudflare","Llama 3.3 70B FP8","stable"),
    "sambanova":("🦣","SambaNova","Llama 3.3 70B Turbo","stable"),
    "tavily":("🔍","Tavily","Search AI + Web","stable"),
    "poll_free":("🌸","Pollinations","Free Unlimited","stable"),
    "cohere":("🔷","Cohere","Command R+ 08-2024","experimental"),
    "mistral":("Ⓜ️","Mistral","Mistral Small Latest","experimental"),
    "moonshot":("🌙","Moonshot","Kimi 128K Context","experimental"),
    "huggingface":("🤗","HuggingFace","Mixtral 8x7B Instruct","experimental"),
    "together":("🤝","Together","Llama 3.3 70B Turbo","experimental"),
    "replicate":("🔄","Replicate","Llama 3.1 405B","experimental"),
    "or_llama":("🦙","OR-Llama","Llama 3.3 70B Free","openrouter"),
    "or_gemini":("🔵","OR-Gemini","Gemini 2.0 Flash Free","openrouter"),
    "or_qwen":("💻","OR-Qwen","Qwen 2.5 72B Free","openrouter"),
    "or_deepseek":("🌊","OR-DeepSeek","DeepSeek Chat Free","openrouter"),
    "or_mistral":("🅼","OR-Mistral","Mistral Nemo Free","openrouter"),
    "p_gpt":("🤖","Poll-GPT","OpenAI Large","pollinations"),
    "p_claude":("🎭","Poll-Claude","Claude Hybrid","pollinations"),
    "p_gemini":("💎","Poll-Gemini","Google Gemini","pollinations"),
    "p_deepseek":("🐳","Poll-DeepSeek","DeepSeek V3","pollinations"),
    "p_qwen":("📟","Poll-Qwen","Qwen 72B","pollinations"),
    "p_llama":("🦙","Poll-Llama","Llama 3.3 70B","pollinations")
}
IMG_INFO={"flux":("🎨","Flux","Fast HQ Standard"),"flux_pro":("⚡","Flux Pro","Professional Quality"),"turbo":("🚀","Turbo","SDXL Turbo Fast"),"dalle":("🤖","DALL-E 3","OpenAI Quality"),"sdxl":("🖼️","SDXL","Stable Diffusion XL")}
def is_owner(uid):return uid in OWNER_IDS
def get_public_default():return db.get_setting("public_default")or"groq"
def call_groq(msgs):
    g=get_groq()
    if not g:return None
    try:r=g.chat.completions.create(messages=msgs,model="llama-3.3-70b-versatile",temperature=0.7,max_tokens=4096);return r.choices[0].message.content
    except Exception as e:logger.error(f"Groq:{e}");return None
def call_cerebras(msgs):
    if not KEY_CEREBRAS:return None
    try:r=get_requests().post("https://api.cerebras.ai/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_CEREBRAS}","Content-Type":"application/json"},json={"model":"llama-3.3-70b","messages":msgs,"max_tokens":4096},timeout=30);return r.json()["choices"][0]["message"]["content"]if r.status_code==200 else None
    except Exception as e:logger.error(f"Cerebras:{e}");return None
def call_cohere(msgs):
    if not KEY_COHERE:return None
    try:
        sys_p="";user_msg="Hi"
        for m in msgs:
            if m["role"]=="system":sys_p=m["content"]
        user_msg=msgs[-1]["content"]if msgs else"Hi"
        d={"model":"command-r-plus-08-2024","message":user_msg}
        if sys_p:d["preamble"]=sys_p
        r=get_requests().post("https://api.cohere.com/v1/chat",headers={"Authorization":f"Bearer {KEY_COHERE}","Content-Type":"application/json","Accept":"application/json"},json=d,timeout=45)
        if r.status_code==200:data=r.json();return data.get("text")or data.get("message")
        logger.error(f"Cohere:{r.status_code}");return None
    except Exception as e:logger.error(f"Cohere:{e}");return None
def call_cloudflare(msgs):
    if not CF_ACCOUNT_ID or not CF_API_TOKEN:return None
    try:
        r=get_requests().post(f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/@cf/meta/llama-3.3-70b-instruct-fp8-fast",headers={"Authorization":f"Bearer {CF_API_TOKEN}","Content-Type":"application/json"},json={"messages":msgs,"max_tokens":4096},timeout=45)
        if r.status_code==200:d=r.json();return d["result"]["response"].strip()if d.get("success")else None
        return None
    except Exception as e:logger.error(f"CF:{e}");return None
def call_sambanova(msgs):
    if not KEY_SAMBANOVA:return None
    try:r=get_requests().post("https://api.sambanova.ai/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_SAMBANOVA}","Content-Type":"application/json"},json={"model":"Meta-Llama-3.3-70B-Instruct","messages":msgs,"max_tokens":4096},timeout=45);return r.json()["choices"][0]["message"]["content"]if r.status_code==200 else None
    except Exception as e:logger.error(f"SN:{e}");return None
def call_together(msgs):
    if not KEY_TOGETHER:return None
    try:r=get_requests().post("https://api.together.xyz/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_TOGETHER}","Content-Type":"application/json"},json={"model":"meta-llama/Llama-3.3-70B-Instruct-Turbo","messages":msgs,"max_tokens":4096},timeout=45);return r.json()["choices"][0]["message"]["content"]if r.status_code==200 else None
    except Exception as e:logger.error(f"Together:{e}");return None
def call_mistral(msgs):
    if not KEY_MISTRAL:return None
    try:
        r=get_requests().post("https://api.mistral.ai/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_MISTRAL}","Content-Type":"application/json","Accept":"application/json"},json={"model":"mistral-small-latest","messages":msgs,"max_tokens":4096},timeout=45)
        if r.status_code==200:return r.json()["choices"][0]["message"]["content"]
        logger.error(f"Mistral:{r.status_code}");return None
    except Exception as e:logger.error(f"Mistral:{e}");return None
def call_moonshot(msgs):
    if not KEY_MOONSHOT:return None
    try:
        r=get_requests().post("https://api.moonshot.cn/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_MOONSHOT}","Content-Type":"application/json"},json={"model":"moonshot-v1-8k","messages":msgs,"max_tokens":4096},timeout=60)
        if r.status_code==200:return r.json()["choices"][0]["message"]["content"]
        logger.error(f"Moonshot:{r.status_code}");return None
    except Exception as e:logger.error(f"Moonshot:{e}");return None
def call_huggingface(msgs):
    if not KEY_HUGGINGFACE:return None
    try:
        prompt="\n".join([f"{m['role']}:{m['content']}"for m in msgs[-5:]])
        r=get_requests().post("https://api-inference.huggingface.co/models/mistralai/Mixtral-8x7B-Instruct-v0.1",headers={"Authorization":f"Bearer {KEY_HUGGINGFACE}","Content-Type":"application/json"},json={"inputs":prompt,"parameters":{"max_new_tokens":1000,"return_full_text":False}},timeout=60)
        if r.status_code==200:d=r.json();return d[0].get("generated_text","").strip()if isinstance(d,list)and d else None
        logger.error(f"HF:{r.status_code}");return None
    except Exception as e:logger.error(f"HF:{e}");return None
def call_replicate(msgs):
    if not KEY_REPLICATE:return None
    try:
        prompt="\n".join([f"{m['role']}:{m['content']}"for m in msgs[-5:]])
        r=get_requests().post("https://api.replicate.com/v1/models/meta/meta-llama-3.1-405b-instruct/predictions",headers={"Authorization":f"Bearer {KEY_REPLICATE}","Content-Type":"application/json"},json={"input":{"prompt":prompt,"max_tokens":2000}},timeout=15)
        if r.status_code in[200,201]:
            pred=r.json();pred_url=f"https://api.replicate.com/v1/predictions/{pred.get('id')}"
            for _ in range(30):
                time.sleep(2)
                pr=get_requests().get(pred_url,headers={"Authorization":f"Bearer {KEY_REPLICATE}"},timeout=10)
                if pr.status_code==200:
                    pd=pr.json()
                    if pd.get("status")=="succeeded":return"".join(pd.get("output",[]))
                    if pd.get("status")in["failed","canceled"]:return None
        return None
    except Exception as e:logger.error(f"Replicate:{e}");return None
def call_tavily(msgs):
    if not KEY_TAVILY:return None
    try:
        query=msgs[-1]["content"]if msgs else""
        sr=get_requests().post("https://api.tavily.com/search",json={"api_key":KEY_TAVILY,"query":query,"search_depth":"advanced","max_results":8},timeout=20)
        if sr.status_code==200:
            sd=sr.json();results=sd.get("results",[])[:5]
            context="\n".join([f"• **{r.get('title','')}**: {r.get('content','')[:200]}"for r in results])
            answer=sd.get("answer","")
            if answer:return f"🔍 **Search Result:**\n{answer}\n\n**Sources:**\n{context}"
            return f"🔍 **Search Results:**\n{context}"if context else None
        return None
    except Exception as e:logger.error(f"Tavily:{e}");return None
def call_openrouter(msgs,mk):
    if not KEY_OPENROUTER:return None
    try:
        mid=OR_MODELS.get(mk,OR_MODELS["or_llama"])
        r=get_requests().post("https://openrouter.ai/api/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_OPENROUTER}","Content-Type":"application/json","HTTP-Referer":"https://github.com","X-Title":"DiscordBot"},json={"model":mid,"messages":msgs,"max_tokens":4096},timeout=60)
        if r.status_code==200:d=r.json();return d["choices"][0]["message"]["content"]if"choices"in d else None
        logger.error(f"OR:{r.status_code}");return None
    except Exception as e:logger.error(f"OR:{e}");return None
def call_poll_free(prompt):
    try:
        enhanced=f"{SYSTEM_PROMPT}\n\nUser: {prompt}\nAssistant:"
        r=get_requests().get(f"https://text.pollinations.ai/{quote(enhanced[:3000])}",timeout=60)
        return r.text.strip()if r.status_code==200 and r.text.strip()and len(r.text.strip())>5 else None
    except Exception as e:logger.error(f"Poll:{e}");return None
def call_pollinations(msgs,mk):
    try:
        mid=POLL_TEXT.get(mk,"openai-large")
        r=get_requests().post("https://text.pollinations.ai/",headers={"Content-Type":"application/json"},json={"messages":msgs,"model":mid,"temperature":0.7},timeout=60)
        return r.text.strip()if r.status_code==200 and r.text.strip()else None
    except Exception as e:logger.error(f"PollAPI:{e}");return None
def call_ai(model,msgs,prompt=""):
    if model=="groq":return call_groq(msgs),"Groq"
    elif model=="cerebras":return call_cerebras(msgs),"Cerebras"
    elif model=="cohere":return call_cohere(msgs),"Cohere"
    elif model=="cloudflare":return call_cloudflare(msgs),"Cloudflare"
    elif model=="sambanova":return call_sambanova(msgs),"SambaNova"
    elif model=="together":return call_together(msgs),"Together"
    elif model=="mistral":return call_mistral(msgs),"Mistral"
    elif model=="moonshot":return call_moonshot(msgs),"Moonshot"
    elif model=="huggingface":return call_huggingface(msgs),"HuggingFace"
    elif model=="replicate":return call_replicate(msgs),"Replicate"
    elif model=="tavily":return call_tavily(msgs),"Tavily"
    elif model=="poll_free":return call_poll_free(prompt),"Pollinations"
    elif model.startswith("or_"):return call_openrouter(msgs,model),f"OR-{model[3:].title()}"
    elif model.startswith("p_"):return call_pollinations(msgs,model),f"Poll-{model[2:].title()}"
    return None,"Unknown"
FALLBACK_ORDER=[("groq",call_groq,KEY_GROQ),("cerebras",call_cerebras,KEY_CEREBRAS),("cloudflare",call_cloudflare,CF_API_TOKEN),("sambanova",call_sambanova,KEY_SAMBANOVA),("poll_free",lambda m:call_poll_free(m[-1]["content"]if m else""),True)]
def ask_ai(prompt,uid=None,model=None):
    if is_owner(uid):sel=model if model else db.get_model(uid)
    else:sel=get_public_default()
    msgs=[{"role":"system","content":SYSTEM_PROMPT}]
    if uid:
        h=mem.get(uid)
        if h:msgs.extend(h[-8:])
    msgs.append({"role":"user","content":prompt})
    result,used=call_ai(sel,msgs,prompt)
    if not result:
        for name,fn,key in FALLBACK_ORDER:
            if not key or name==sel:continue
            try:
                r=fn(msgs)
                if r:result=r;used=f"{name.title()}(fb)";break
            except:continue
    if not result:return"❌ Semua provider AI sedang tidak tersedia. Silakan coba lagi nanti.","None"
    if uid:mem.add(uid,"user",prompt[:1000]);mem.add(uid,"assistant",result[:1000])
    return result,used
async def gen_image(prompt,model="flux"):
    try:
        mid=POLL_IMG.get(model,"flux")
        url=f"https://image.pollinations.ai/prompt/{quote(prompt)}?model={mid}&nologo=true&width=1024&height=1024&seed={random.randint(1,99999)}"
        r=get_requests().get(url,timeout=120)
        return(r.content,None)if r.status_code==200 and len(r.content)>1000 else(None,f"HTTP {r.status_code}")
    except Exception as e:return None,str(e)[:50]
class ModelSelect1(ui.Select):
    def __init__(s,user_id):
        s.user_id=user_id
        opts=[]
        for m in MODELS_STABLE:
            if m in MODEL_INFO:
                info=MODEL_INFO[m]
                opts.append(discord.SelectOption(label=info[1],value=m,emoji=info[0],description=info[2][:50]))
        super().__init__(placeholder="⚡ Pilih Model Stable...",options=opts,min_values=1,max_values=1)
    async def callback(s,interaction:discord.Interaction):
        if interaction.user.id!=s.user_id:return await interaction.response.send_message("❌ Ini bukan menu kamu!",ephemeral=True)
        selected=s.values[0]
        db.set_model(interaction.user.id,selected)
        info=MODEL_INFO.get(selected,("","?","",""))
        await interaction.response.send_message(f"✅ Model diubah ke: {info[0]} **{info[1]}**\n> {info[2]}",ephemeral=True)
class ModelView1(ui.View):
    def __init__(s,user_id):
        super().__init__(timeout=180)
        s.user_id=user_id
        s.add_item(ModelSelect1(user_id))
    async def interaction_check(s,interaction:discord.Interaction)->bool:
        return interaction.user.id==s.user_id
class ModelSelect2(ui.Select):
    def __init__(s,user_id):
        s.user_id=user_id
        opts=[]
        for m in MODELS_EXPERIMENTAL:
            if m in MODEL_INFO:
                info=MODEL_INFO[m]
                opts.append(discord.SelectOption(label=info[1],value=m,emoji=info[0],description=info[2][:50]))
        super().__init__(placeholder="🧪 Pilih Model Experimental...",options=opts,min_values=1,max_values=1)
    async def callback(s,interaction:discord.Interaction):
        if interaction.user.id!=s.user_id:return await interaction.response.send_message("❌ Ini bukan menu kamu!",ephemeral=True)
        selected=s.values[0]
        db.set_model(interaction.user.id,selected)
        info=MODEL_INFO.get(selected,("","?","",""))
        await interaction.response.send_message(f"✅ Model diubah ke: {info[0]} **{info[1]}**\n> {info[2]}",ephemeral=True)
class ModelView2(ui.View):
    def __init__(s,user_id):
        super().__init__(timeout=180)
        s.user_id=user_id
        s.add_item(ModelSelect2(user_id))
    async def interaction_check(s,interaction:discord.Interaction)->bool:
        return interaction.user.id==s.user_id
class ModelSelect3OR(ui.Select):
    def __init__(s,user_id):
        s.user_id=user_id
        opts=[]
        for m in MODELS_OPENROUTER:
            if m in MODEL_INFO:
                info=MODEL_INFO[m]
                opts.append(discord.SelectOption(label=info[1],value=m,emoji=info[0],description=info[2][:50]))
        super().__init__(placeholder="🌐 OpenRouter Models...",options=opts,min_values=1,max_values=1)
    async def callback(s,interaction:discord.Interaction):
        if interaction.user.id!=s.user_id:return await interaction.response.send_message("❌ Ini bukan menu kamu!",ephemeral=True)
        selected=s.values[0]
        db.set_model(interaction.user.id,selected)
        info=MODEL_INFO.get(selected,("","?","",""))
        await interaction.response.send_message(f"✅ Model diubah ke: {info[0]} **{info[1]}**\n> {info[2]}",ephemeral=True)
class ModelSelect3Poll(ui.Select):
    def __init__(s,user_id):
        s.user_id=user_id
        opts=[]
        for m in MODELS_POLLINATIONS:
            if m in MODEL_INFO:
                info=MODEL_INFO[m]
                opts.append(discord.SelectOption(label=info[1],value=m,emoji=info[0],description=info[2][:50]))
        super().__init__(placeholder="🌸 Pollinations Models...",options=opts,min_values=1,max_values=1)
    async def callback(s,interaction:discord.Interaction):
        if interaction.user.id!=s.user_id:return await interaction.response.send_message("❌ Ini bukan menu kamu!",ephemeral=True)
        selected=s.values[0]
        db.set_model(interaction.user.id,selected)
        info=MODEL_INFO.get(selected,("","?","",""))
        await interaction.response.send_message(f"✅ Model diubah ke: {info[0]} **{info[1]}**\n> {info[2]}",ephemeral=True)
class ModelView3(ui.View):
    def __init__(s,user_id):
        super().__init__(timeout=180)
        s.user_id=user_id
        s.add_item(ModelSelect3OR(user_id))
        s.add_item(ModelSelect3Poll(user_id))
    async def interaction_check(s,interaction:discord.Interaction)->bool:
        return interaction.user.id==s.user_id
class ImgSelect(ui.Select):
    def __init__(s,user_id):
        s.user_id=user_id
        opts=[discord.SelectOption(label=v[1],value=k,emoji=v[0],description=v[2])for k,v in IMG_INFO.items()]
        super().__init__(placeholder="🎨 Pilih Image Model...",options=opts,min_values=1,max_values=1)
    async def callback(s,interaction:discord.Interaction):
        if interaction.user.id!=s.user_id:return await interaction.response.send_message("❌ Ini bukan menu kamu!",ephemeral=True)
        selected=s.values[0]
        db.set_img_model(interaction.user.id,selected)
        info=IMG_INFO.get(selected,("","?",""))
        await interaction.response.send_message(f"✅ Image model: {info[0]} **{info[1]}**",ephemeral=True)
class ImgView(ui.View):
    def __init__(s,user_id):
        super().__init__(timeout=180)
        s.user_id=user_id
        s.add_item(ImgSelect(user_id))
    async def interaction_check(s,interaction:discord.Interaction)->bool:
        return interaction.user.id==s.user_id
class DefaultSelect(ui.Select):
    def __init__(s,user_id):
        s.user_id=user_id
        opts=[]
        for m in MODELS_STABLE:
            if m in MODEL_INFO:
                info=MODEL_INFO[m]
                opts.append(discord.SelectOption(label=info[1],value=m,emoji=info[0],description=f"Set {info[1]} as public default"))
        super().__init__(placeholder="🌍 Set Public Default...",options=opts,min_values=1,max_values=1)
    async def callback(s,interaction:discord.Interaction):
        if not is_owner(interaction.user.id):return await interaction.response.send_message("❌ Owner only!",ephemeral=True)
        selected=s.values[0]
        db.set_setting("public_default",selected)
        info=MODEL_INFO.get(selected,("","?","",""))
        await interaction.response.send_message(f"✅ Public default diubah ke: {info[0]} **{info[1]}**\nSemua user public sekarang menggunakan model ini.",ephemeral=True)
class DefaultView(ui.View):
    def __init__(s,user_id):
        super().__init__(timeout=180)
        s.user_id=user_id
        s.add_item(DefaultSelect(user_id))
    async def interaction_check(s,interaction:discord.Interaction)->bool:
        return is_owner(interaction.user.id)
class ShieldSelect(ui.Select):
    def __init__(s):
        opts=[discord.SelectOption(label="Stats",value="stats",emoji="📊"),discord.SelectOption(label="Sessions",value="sessions",emoji="🔄"),discord.SelectOption(label="Logs",value="logs",emoji="📋"),discord.SelectOption(label="Bans",value="bans",emoji="🚫"),discord.SelectOption(label="Script",value="script",emoji="📜"),discord.SelectOption(label="KeepAlive",value="ka",emoji="⚡"),discord.SelectOption(label="Clear Sessions",value="cs",emoji="🧹"),discord.SelectOption(label="Clear Logs",value="cl",emoji="🗑️")]
        super().__init__(placeholder="🛡️ Shield Action...",options=opts)
    async def callback(s,i:discord.Interaction):
        if not is_owner(i.user.id):return await i.response.send_message("❌ Owner only",ephemeral=True)
        v=s.values[0];await i.response.defer(ephemeral=True)
        if v=="stats":r=shield.stats();await i.followup.send(f"```json\n{json.dumps(r,indent=2)[:1900]}```",ephemeral=True)
        elif v=="sessions":r=shield.sessions();await i.followup.send(f"```json\n{json.dumps(r,indent=2)[:1900]}```",ephemeral=True)
        elif v=="logs":r=shield.logs();await i.followup.send(f"```json\n{json.dumps(r,indent=2)[:1900]}```",ephemeral=True)
        elif v=="bans":r=shield.bans();await i.followup.send(f"```json\n{json.dumps(r,indent=2)[:1900]}```",ephemeral=True)
        elif v=="script":
            r=shield.script()
            if r.get("success"):await i.followup.send(file=discord.File(io.BytesIO(r["script"].encode()),"script.lua"),ephemeral=True)
            else:await i.followup.send(f"❌ {r.get('error')}",ephemeral=True)
        elif v=="ka":r=shield.keepalive();await i.followup.send(f"✅ {r.get('status')}"if r.get("status")=="alive"else f"❌ {r}",ephemeral=True)
        elif v=="cs":r=shield.clear_sessions();await i.followup.send(f"{'✅ Sessions cleared'if r.get('success')else'❌ '+r.get('error','')}",ephemeral=True)
        elif v=="cl":r=shield.clear_logs();await i.followup.send(f"{'✅ Logs cleared'if r.get('success')else'❌ '+r.get('error','')}",ephemeral=True)
class ShieldView(ui.View):
    def __init__(s):super().__init__(timeout=180);s.add_item(ShieldSelect())
class Dumper:
    def __init__(s):s.last=None
    def dump(s,url,cache=True):
        if cache:
            c=db.get_cache(url)
            if c:return{"success":True,"content":c,"method":"cache"}
        req=get_requests();curl=get_curl();cs=get_cloudscraper();methods=[]
        if curl:methods.append(("curl",lambda u:curl.get(u,impersonate="chrome120",headers={"User-Agent":"Roblox/WinInet"},timeout=25)))
        if cs:methods.append(("cf",lambda u:cs.get(u,timeout=25)))
        if req:methods.append(("req",lambda u:req.get(u,headers={"User-Agent":"Roblox/WinInet"},timeout=25)))
        if s.last:methods.sort(key=lambda x:x[0]!=s.last)
        for n,f in methods:
            try:
                r=f(url)
                if r.status_code==200 and len(r.text)>10:s.last=n;db.cache_dump(url,r.text)if cache else None;return{"success":True,"content":r.text,"method":n}
            except:pass
        return{"success":False,"error":"All methods failed"}
dumper=Dumper()
def split_msg(t,limit=1900):return[t[i:i+limit]for i in range(0,len(t),limit)]if t else[""]
async def send_ai_response(channel,user,content,model_used):
    chunks=split_msg(content)
    for i,chunk in enumerate(chunks):
        embed=discord.Embed(description=chunk,color=0x5865F2)
        if i==0:
            embed.set_author(name=user.display_name,icon_url=user.display_avatar.url if user.display_avatar else None)
        if i==len(chunks)-1:
            embed.set_footer(text=f"🤖 {model_used}")
        await channel.send(embed=embed)
@bot.event
async def on_ready():
    logger.info(f'🔥 {bot.user} ready | Servers: {len(bot.guilds)}')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening,name=f"{PREFIX}help"))
@bot.event
async def on_command_error(ctx,e):
    if isinstance(e,commands.CommandNotFound):return
    logger.error(f"CmdError: {e}")
@bot.event
async def on_message(msg):
    if msg.author.bot:return
    if bot.user.mentioned_in(msg)and not msg.mention_everyone:
        content=msg.content.replace(f'<@{bot.user.id}>','').replace(f'<@!{bot.user.id}>','').strip()
        if content:
            if db.banned(msg.author.id):return
            ok,remaining=rl.check(msg.author.id,"ai",5)
            if not ok:
                warn=await msg.channel.send(f"⏳ Tunggu {remaining:.0f} detik...",delete_after=3)
                return
            async with msg.channel.typing():
                response,model_used=ask_ai(content,msg.author.id)
                await send_ai_response(msg.channel,msg.author,response,model_used)
                db.stat("ai",msg.author.id)
            try:await msg.delete()
            except:pass
        else:
            current_model=db.get_model(msg.author.id)if is_owner(msg.author.id)else get_public_default()
            info=MODEL_INFO.get(current_model,("❓","Unknown","",""))
            embed=discord.Embed(title="👋 Halo!",description=f"Mention saya dengan pertanyaan untuk chat.\n\n**Model aktif:** {info[0]} {info[1]}\n**Status:** {'👑 Owner' if is_owner(msg.author.id) else '👤 Public'}",color=0x5865F2)
            await msg.channel.send(embed=embed,delete_after=15)
        return
    await bot.process_commands(msg)
@bot.command(name="ai",aliases=["a","chat"])
async def cmd_ai(ctx,*,prompt:str=None):
    if db.banned(ctx.author.id):return
    if not prompt:
        embed=discord.Embed(title="💬 AI Chat",description=f"**Penggunaan:**\n`{PREFIX}ai <pertanyaan>`\n`@{bot.user.name} <pertanyaan>`",color=0x5865F2)
        return await ctx.send(embed=embed,delete_after=10)
    ok,remaining=rl.check(ctx.author.id,"ai",5)
    if not ok:return await ctx.send(f"⏳ Tunggu {remaining:.0f} detik...",delete_after=3)
    user_msg=ctx.message
    async with ctx.typing():
        response,model_used=ask_ai(prompt,ctx.author.id)
        await send_ai_response(ctx.channel,ctx.author,response,model_used)
        db.stat("ai",ctx.author.id)
    try:await user_msg.delete()
    except:pass
@bot.command(name="model1",aliases=["m1"])
async def cmd_model1(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Command ini hanya untuk Owner!",delete_after=5)
    current=db.get_model(ctx.author.id)
    info=MODEL_INFO.get(current,("❓","Unknown","",""))
    embed=discord.Embed(title="⚡ Model Stable",description=f"**Model saat ini:** {info[0]} {info[1]}\n\nPilih model yang stabil dan selalu tersedia:",color=0x00FF00)
    for m in MODELS_STABLE:
        if m in MODEL_INFO:
            mi=MODEL_INFO[m]
            status="✅"if m==current else"⚪"
            embed.add_field(name=f"{mi[0]} {mi[1]}",value=f"{status} {mi[2]}",inline=True)
    await ctx.send(embed=embed,view=ModelView1(ctx.author.id))
@bot.command(name="model2",aliases=["m2"])
async def cmd_model2(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Command ini hanya untuk Owner!",delete_after=5)
    current=db.get_model(ctx.author.id)
    info=MODEL_INFO.get(current,("❓","Unknown","",""))
    embed=discord.Embed(title="🧪 Model Experimental",description=f"**Model saat ini:** {info[0]} {info[1]}\n\n⚠️ Model ini mungkin tidak stabil atau sedang down:",color=0xFFA500)
    for m in MODELS_EXPERIMENTAL:
        if m in MODEL_INFO:
            mi=MODEL_INFO[m]
            status="✅"if m==current else"⚪"
            embed.add_field(name=f"{mi[0]} {mi[1]}",value=f"{status} {mi[2]}",inline=True)
    await ctx.send(embed=embed,view=ModelView2(ctx.author.id))
@bot.command(name="model3",aliases=["m3"])
async def cmd_model3(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Command ini hanya untuk Owner!",delete_after=5)
    current=db.get_model(ctx.author.id)
    info=MODEL_INFO.get(current,("❓","Unknown","",""))
    embed=discord.Embed(title="🌐 OpenRouter & Pollinations",description=f"**Model saat ini:** {info[0]} {info[1]}\n\nModel dari OpenRouter (gratis) dan Pollinations:",color=0x9B59B6)
    embed.add_field(name="🌐 OpenRouter",value="\n".join([f"{MODEL_INFO[m][0]} {MODEL_INFO[m][1]}"for m in MODELS_OPENROUTER if m in MODEL_INFO]),inline=True)
    embed.add_field(name="🌸 Pollinations",value="\n".join([f"{MODEL_INFO[m][0]} {MODEL_INFO[m][1]}"for m in MODELS_POLLINATIONS if m in MODEL_INFO]),inline=True)
    await ctx.send(embed=embed,view=ModelView3(ctx.author.id))
@bot.command(name="setdefault",aliases=["sd"])
async def cmd_setdefault(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Command ini hanya untuk Owner!",delete_after=5)
    current=get_public_default()
    info=MODEL_INFO.get(current,("❓","Unknown","",""))
    embed=discord.Embed(title="🌍 Set Default Public Model",description=f"**Default saat ini:** {info[0]} {info[1]}\n\nPilih model default untuk semua user public:",color=0x3498DB)
    embed.add_field(name="ℹ️ Info",value="User public hanya bisa menggunakan model default yang kamu set. Ini menghemat limit API.",inline=False)
    await ctx.send(embed=embed,view=DefaultView(ctx.author.id))
@bot.command(name="imagine",aliases=["img","image"])
async def cmd_imagine(ctx,*,prompt:str=None):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Fitur image generation hanya untuk Owner!",delete_after=5)
    if db.banned(ctx.author.id):return
    if not prompt:
        return await ctx.send(f"❌ Penggunaan: `{PREFIX}img <prompt>`",delete_after=5)
    ok,remaining=rl.check(ctx.author.id,"img",15)
    if not ok:return await ctx.send(f"⏳ Tunggu {remaining:.0f} detik...",delete_after=3)
    model=db.get_img_model(ctx.author.id)
    info=IMG_INFO.get(model,("🎨","Flux",""))
    status_msg=await ctx.send(f"🎨 Generating dengan {info[0]} **{info[1]}**...")
    try:
        img_data,error=await gen_image(prompt,model)
        if img_data:
            file=discord.File(io.BytesIO(img_data),"generated.png")
            embed=discord.Embed(title=f"🎨 {prompt[:100]}",color=0x5865F2)
            embed.set_image(url="attachment://generated.png")
            embed.set_footer(text=f"{info[0]} {info[1]} | {ctx.author.display_name}")
            await ctx.send(embed=embed,file=file)
            await status_msg.delete()
            db.stat("img",ctx.author.id)
        else:
            await status_msg.edit(content=f"❌ Gagal generate: {error}")
    except Exception as e:
        await status_msg.edit(content=f"❌ Error: {str(e)[:50]}")
    try:await ctx.message.delete()
    except:pass
@bot.command(name="imgmodel",aliases=["im"])
async def cmd_imgmodel(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Command ini hanya untuk Owner!",delete_after=5)
    current=db.get_img_model(ctx.author.id)
    info=IMG_INFO.get(current,("❓","Unknown",""))
    embed=discord.Embed(title="🎨 Image Model Selection",description=f"**Model saat ini:** {info[0]} {info[1]}",color=0x5865F2)
    for k,v in IMG_INFO.items():
        status="✅"if k==current else"⚪"
        embed.add_field(name=f"{v[0]} {v[1]}",value=f"{status} {v[2]}",inline=True)
    await ctx.send(embed=embed,view=ImgView(ctx.author.id))
@bot.command(name="shield",aliases=["sh"])
async def cmd_shield(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only",delete_after=5)
    embed=discord.Embed(title="🛡️ Shield Control Panel",description=f"**URL:** `{SHIELD_URL or 'Not configured'}`",color=0xE74C3C)
    await ctx.send(embed=embed,view=ShieldView())
@bot.command(name="dump",aliases=["dl"])
async def cmd_dump(ctx,url:str=None,*,flags:str=""):
    if db.banned(ctx.author.id):return
    if not url:return await ctx.send(f"❌ Penggunaan: `{PREFIX}dump <url>`",delete_after=5)
    ok,remaining=rl.check(ctx.author.id,"dump",10)
    if not ok:return await ctx.send(f"⏳ Tunggu {remaining:.0f} detik...",delete_after=3)
    if not url.startswith("http"):url="https://"+url
    status_msg=await ctx.send("🔄 Dumping...")
    result=dumper.dump(url,"--nocache"not in flags)
    if result["success"]:
        content=result["content"]
        ext="lua"if"local "in content[:500]else"html"if"<html"in content[:200].lower()else"txt"
        file=discord.File(io.BytesIO(content.encode()),f"dump.{ext}")
        await ctx.send(f"✅ `{result['method']}` | `{len(content):,}` bytes",file=file)
        await status_msg.delete()
        db.stat("dump",ctx.author.id)
    else:
        await status_msg.edit(content=f"❌ {result.get('error','Unknown error')}")
@bot.command(name="clear",aliases=["reset"])
async def cmd_clear(ctx):
    mem.clear(ctx.author.id)
    await ctx.send("🧹 Memory percakapan dihapus!",delete_after=5)
    try:await ctx.message.delete()
    except:pass
@bot.command(name="ping",aliases=["p"])
async def cmd_ping(ctx):
    current_model=db.get_model(ctx.author.id)if is_owner(ctx.author.id)else get_public_default()
    info=MODEL_INFO.get(current_model,("❓","Unknown","",""))
    embed=discord.Embed(title="🏓 Pong!",color=0x00FF00)
    embed.add_field(name="📡 Latency",value=f"`{round(bot.latency*1000)}ms`",inline=True)
    embed.add_field(name="🤖 Model",value=f"{info[0]} {info[1]}",inline=True)
    embed.add_field(name="👤 Status",value=f"`{'Owner' if is_owner(ctx.author.id) else 'Public'}`",inline=True)
    embed.add_field(name="🌍 Public Default",value=f"`{get_public_default()}`",inline=True)
    await ctx.send(embed=embed)
@bot.command(name="status")
async def cmd_status(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only",delete_after=5)
    embed=discord.Embed(title="📊 Bot Status",color=0x5865F2)
    keys_status=[("Groq",KEY_GROQ),("Cerebras",KEY_CEREBRAS),("Cloudflare",CF_API_TOKEN),("SambaNova",KEY_SAMBANOVA),("Cohere",KEY_COHERE),("Mistral",KEY_MISTRAL),("Moonshot",KEY_MOONSHOT),("HuggingFace",KEY_HUGGINGFACE),("Together",KEY_TOGETHER),("Replicate",KEY_REPLICATE),("OpenRouter",KEY_OPENROUTER),("Tavily",KEY_TAVILY),("Pollinations",KEY_POLLINATIONS)]
    status_text=""
    for name,key in keys_status:
        status_text+=f"{'✅'if key else'❌'} {name}\n"
    embed.add_field(name="🔑 API Keys",value=status_text,inline=True)
    embed.add_field(name="⚙️ Settings",value=f"**Default:** `{get_public_default()}`\n**Prefix:** `{PREFIX}`\n**Servers:** `{len(bot.guilds)}`",inline=True)
    await ctx.send(embed=embed)
@bot.command(name="testai")
async def cmd_testai(ctx):
    if not is_owner(ctx.author.id):return await ctx.send("❌ Owner only",delete_after=5)
    status_msg=await ctx.send("🔄 Testing all providers...")
    test_msgs=[{"role":"user","content":"Say OK"}]
    results=[]
    providers=[("Groq",lambda:call_groq(test_msgs),KEY_GROQ),("Cerebras",lambda:call_cerebras(test_msgs),KEY_CEREBRAS),("Cloudflare",lambda:call_cloudflare(test_msgs),CF_API_TOKEN),("SambaNova",lambda:call_sambanova(test_msgs),KEY_SAMBANOVA),("Cohere",lambda:call_cohere(test_msgs),KEY_COHERE),("Mistral",lambda:call_mistral(test_msgs),KEY_MISTRAL),("Moonshot",lambda:call_moonshot(test_msgs),KEY_MOONSHOT),("HuggingFace",lambda:call_huggingface(test_msgs),KEY_HUGGINGFACE),("Together",lambda:call_together(test_msgs),KEY_TOGETHER),("OpenRouter",lambda:call_openrouter(test_msgs,"or_gemini"),KEY_OPENROUTER),("Tavily",lambda:call_tavily(test_msgs),KEY_TAVILY),("Poll",lambda:call_poll_free("OK"),True)]
    for name,fn,key in providers:
        if not key:results.append(f"⚪ {name}");continue
        try:
            r=fn()
            results.append(f"✅ {name}"if r else f"❌ {name}")
        except Exception as e:
            results.append(f"❌ {name}")
            logger.error(f"Test {name}: {e}")
    embed=discord.Embed(title="🧪 AI Provider Status",description=" | ".join(results),color=0x5865F2)
    await status_msg.edit(content=None,embed=embed)
@bot.command(name="blacklist",aliases=["bl","ban"])
async def cmd_blacklist(ctx,action:str=None,user:discord.User=None):
    if not is_owner(ctx.author.id):return
    if not action or not user:
        return await ctx.send(f"**Penggunaan:**\n`{PREFIX}bl add @user` - Ban user\n`{PREFIX}bl rem @user` - Unban user",delete_after=10)
    if action in["add","ban"]:
        db.add_bl(user.id)
        await ctx.send(f"✅ **{user}** telah di-ban dari bot",delete_after=5)
    elif action in["rem","remove","unban"]:
        db.rem_bl(user.id)
        await ctx.send(f"✅ **{user}** telah di-unban",delete_after=5)
@bot.command(name="help",aliases=["h"])
async def cmd_help(ctx):
    embed=discord.Embed(title="📚 Command Help",color=0x5865F2)
    embed.add_field(name="💬 AI Chat",value=f"`{PREFIX}ai <text>` - Chat dengan AI\n`@{bot.user.name} <text>` - Mention chat",inline=False)
    if is_owner(ctx.author.id):
        embed.add_field(name="🤖 Model Selection (Owner)",value=f"`{PREFIX}m1` - Model Stable\n`{PREFIX}m2` - Model Experimental\n`{PREFIX}m3` - OpenRouter & Pollinations",inline=True)
        embed.add_field(name="🎨 Image (Owner)",value=f"`{PREFIX}img <prompt>` - Generate image\n`{PREFIX}im` - Select image model",inline=True)
        embed.add_field(name="⚙️ Admin (Owner)",value=f"`{PREFIX}sd` - Set public default\n`{PREFIX}status` - Bot status\n`{PREFIX}testai` - Test providers\n`{PREFIX}bl` - Blacklist\n`{PREFIX}sh` - Shield panel",inline=True)
    embed.add_field(name="🔧 Utility",value=f"`{PREFIX}dump <url>` - Dump URL\n`{PREFIX}clear` - Clear memory\n`{PREFIX}ping` - Check latency",inline=False)
    current=db.get_model(ctx.author.id)if is_owner(ctx.author.id)else get_public_default()
    info=MODEL_INFO.get(current,("❓","Unknown","",""))
    embed.set_footer(text=f"Model: {info[0]} {info[1]} | {'👑 Owner' if is_owner(ctx.author.id) else '👤 Public'}")
    await ctx.send(embed=embed)
if __name__=="__main__":
    keep_alive()
    print("="*50)
    print("🚀 Bot Starting...")
    print(f"👑 Owners: {OWNER_IDS}")
    print(f"🌍 Public Default: {db.get_setting('public_default')or'groq'}")
    print(f"🛡️ Shield: {'✅ Configured'if SHIELD_URL else'❌ Not configured'}")
    print("-"*50)
    keys=[("Groq",KEY_GROQ),("Cerebras",KEY_CEREBRAS),("Cloudflare",CF_API_TOKEN),("SambaNova",KEY_SAMBANOVA),("Cohere",KEY_COHERE),("Mistral",KEY_MISTRAL),("Moonshot",KEY_MOONSHOT),("HuggingFace",KEY_HUGGINGFACE),("Together",KEY_TOGETHER),("Replicate",KEY_REPLICATE),("OpenRouter",KEY_OPENROUTER),("Tavily",KEY_TAVILY),("Pollinations",KEY_POLLINATIONS)]
    for name,key in keys:print(f"   {'✅'if key else'❌'} {name}")
    print("="*50)
    bot.run(DISCORD_TOKEN,log_handler=None)
