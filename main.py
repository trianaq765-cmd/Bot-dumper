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
if not DISCORD_TOKEN:print("DISCORD_TOKEN Missing");exit(1)
intents=discord.Intents.default()
intents.message_content=True
bot=commands.Bot(command_prefix=PREFIX,intents=intents,help_command=None)
_groq=None
_requests=None
_curl=None
_cloudscraper=None
def get_groq():
    global _groq
    if _groq is None and KEY_GROQ:
        try:
            from groq import Groq
            _groq=Groq(api_key=KEY_GROQ)
        except:pass
    return _groq
def get_requests():
    global _requests
    if _requests is None:
        import requests
        _requests=requests
    return _requests
def get_curl():
    global _curl
    if _curl is None:
        try:
            from curl_cffi import requests as r
            _curl=r
        except:_curl=None
    return _curl
def get_cloudscraper():
    global _cloudscraper
    if _cloudscraper is None:
        try:
            import cloudscraper
            _cloudscraper=cloudscraper.create_scraper(browser={'browser':'chrome','platform':'windows','mobile':False})
        except:_cloudscraper=None
    return _cloudscraper
class ShieldAPI:
    def __init__(self,url,key):
        self.url=url
        self.key=key
        self.timeout=30
    def _headers(self):
        return{"x-admin-key":self.key,"Content-Type":"application/json","Accept":"application/json"}
    def _get(self,endpoint):
        if not self.url or not self.key:
            return{"success":False,"error":"Shield not configured"}
        try:
            resp=get_requests().get(f"{self.url}{endpoint}",headers=self._headers(),timeout=self.timeout)
            if resp.status_code==200:
                return resp.json()
            return{"success":False,"error":f"HTTP {resp.status_code}"}
        except Exception as e:
            return{"success":False,"error":str(e)[:100]}
    def _post(self,endpoint,data=None):
        if not self.url or not self.key:
            return{"success":False,"error":"Shield not configured"}
        try:
            resp=get_requests().post(f"{self.url}{endpoint}",headers=self._headers(),json=data or{},timeout=self.timeout)
            if resp.status_code in[200,201]:
                try:
                    return resp.json()
                except:
                    return{"success":True,"message":"OK"}
            return{"success":False,"error":f"HTTP {resp.status_code}"}
        except Exception as e:
            return{"success":False,"error":str(e)[:100]}
    def _delete(self,endpoint):
        if not self.url or not self.key:
            return{"success":False,"error":"Shield not configured"}
        try:
            resp=get_requests().delete(f"{self.url}{endpoint}",headers=self._headers(),timeout=self.timeout)
            if resp.status_code==200:
                try:
                    return resp.json()
                except:
                    return{"success":True,"message":"Deleted"}
            return{"success":False,"error":f"HTTP {resp.status_code}"}
        except Exception as e:
            return{"success":False,"error":str(e)[:100]}
    def get_stats(self):
        return self._get("/api/admin/stats")
    def get_sessions(self):
        return self._get("/api/admin/sessions")
    def get_logs(self):
        return self._get("/api/admin/logs")
    def get_bans(self):
        return self._get("/api/admin/bans")
    def get_whitelist(self):
        return self._get("/api/admin/whitelist")
    def get_suspended(self):
        return self._get("/api/admin/suspended")
    def get_script(self):
        return self._get("/api/admin/script")
    def keepalive(self):
        try:
            resp=get_requests().get(f"{self.url}/api/keepalive",timeout=10)
            if resp.status_code==200:
                return{"success":True,"status":"alive"}
            return{"success":False,"status":"down"}
        except:
            return{"success":False,"status":"unreachable"}
    def add_ban(self,hwid=None,ip=None,player_id=None,reason="Via Discord"):
        data={"reason":reason}
        if hwid:data["hwid"]=hwid
        if ip:data["ip"]=ip
        if player_id:data["playerId"]=player_id
        return self._post("/api/admin/bans",data)
    def remove_ban(self,ban_id):
        return self._delete(f"/api/admin/bans/{ban_id}")
    def add_whitelist(self,wl_type,value):
        return self._post("/api/admin/whitelist",{"type":wl_type,"value":value})
    def remove_whitelist(self,wl_type,value):
        return self._post("/api/admin/whitelist/remove",{"type":wl_type,"value":value})
    def suspend_user(self,sus_type,value,reason="Via Discord",duration=None):
        data={"type":sus_type,"value":value,"reason":reason}
        if duration:data["duration"]=duration
        return self._post("/api/admin/suspend",data)
    def unsuspend_user(self,sus_type,value):
        return self._post("/api/admin/unsuspend",{"type":sus_type,"value":value})
    def kill_session(self,session_id,reason="Via Discord"):
        return self._post("/api/admin/kill-session",{"sessionId":session_id,"reason":reason})
    def clear_sessions(self):
        return self._post("/api/admin/sessions/clear",{})
    def clear_logs(self):
        return self._post("/api/admin/logs/clear",{})
    def clear_cache(self):
        return self._post("/api/admin/cache/clear",{})
shield=ShieldAPI(SHIELD_URL,SHIELD_ADMIN_KEY)
class Database:
    def __init__(self,path="bot.db"):
        self.conn=sqlite3.connect(path,check_same_thread=False)
        self.lock=threading.Lock()
        self.conn.executescript('''CREATE TABLE IF NOT EXISTS user_prefs(uid INTEGER PRIMARY KEY,model TEXT DEFAULT "groq",img_model TEXT DEFAULT "flux");CREATE TABLE IF NOT EXISTS bot_settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE IF NOT EXISTS stats(id INTEGER PRIMARY KEY,cmd TEXT,uid INTEGER,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS blacklist(uid INTEGER PRIMARY KEY);CREATE TABLE IF NOT EXISTS allowed_users(uid INTEGER PRIMARY KEY,allowed_models TEXT DEFAULT "groq");CREATE TABLE IF NOT EXISTS dump_cache(url TEXT PRIMARY KEY,content TEXT,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);''')
        self._init_settings()
    def _init_settings(self):
        with self.lock:
            r=self.conn.execute('SELECT value FROM bot_settings WHERE key="public_default"').fetchone()
            if not r:
                self.conn.execute('INSERT INTO bot_settings VALUES("public_default","groq")')
                self.conn.commit()
    def get_setting(self,k):
        with self.lock:
            r=self.conn.execute('SELECT value FROM bot_settings WHERE key=?',(k,)).fetchone()
            return r[0]if r else None
    def set_setting(self,k,v):
        with self.lock:
            self.conn.execute('INSERT OR REPLACE INTO bot_settings VALUES(?,?)',(k,v))
            self.conn.commit()
    def get_model(self,uid):
        with self.lock:
            r=self.conn.execute('SELECT model FROM user_prefs WHERE uid=?',(uid,)).fetchone()
            return r[0]if r else"groq"
    def set_model(self,uid,m):
        with self.lock:
            self.conn.execute('INSERT OR REPLACE INTO user_prefs(uid,model,img_model) VALUES(?,?,COALESCE((SELECT img_model FROM user_prefs WHERE uid=?),"flux"))',(uid,m,uid))
            self.conn.commit()
    def get_img_model(self,uid):
        with self.lock:
            r=self.conn.execute('SELECT img_model FROM user_prefs WHERE uid=?',(uid,)).fetchone()
            return r[0]if r else"flux"
    def set_img_model(self,uid,m):
        with self.lock:
            self.conn.execute('INSERT OR REPLACE INTO user_prefs(uid,model,img_model) VALUES(?,COALESCE((SELECT model FROM user_prefs WHERE uid=?),"groq"),?)',(uid,uid,m))
            self.conn.commit()
    def get_user_allowed(self,uid):
        with self.lock:
            r=self.conn.execute('SELECT allowed_models FROM allowed_users WHERE uid=?',(uid,)).fetchone()
            return r[0].split(",")if r else[]
    def set_user_allowed(self,uid,m):
        with self.lock:
            self.conn.execute('INSERT OR REPLACE INTO allowed_users VALUES(?,?)',(uid,",".join(m)))
            self.conn.commit()
    def rem_user_allowed(self,uid):
        with self.lock:
            self.conn.execute('DELETE FROM allowed_users WHERE uid=?',(uid,))
            self.conn.commit()
    def stat(self,cmd,uid):
        with self.lock:
            self.conn.execute('INSERT INTO stats(cmd,uid) VALUES(?,?)',(cmd,uid))
            self.conn.commit()
    def banned(self,uid):
        with self.lock:
            return self.conn.execute('SELECT 1 FROM blacklist WHERE uid=?',(uid,)).fetchone()is not None
    def add_bl(self,uid):
        with self.lock:
            self.conn.execute('INSERT OR IGNORE INTO blacklist VALUES(?)',(uid,))
            self.conn.commit()
    def rem_bl(self,uid):
        with self.lock:
            self.conn.execute('DELETE FROM blacklist WHERE uid=?',(uid,))
            self.conn.commit()
    def cache_dump(self,url,c):
        with self.lock:
            h=hashlib.md5(url.encode()).hexdigest()
            self.conn.execute('INSERT OR REPLACE INTO dump_cache VALUES(?,?,CURRENT_TIMESTAMP)',(h,c[:500000]))
            self.conn.commit()
    def get_cache(self,url):
        with self.lock:
            h=hashlib.md5(url.encode()).hexdigest()
            r=self.conn.execute('SELECT content FROM dump_cache WHERE url=? AND ts>datetime("now","-1 hour")',(h,)).fetchone()
            return r[0]if r else None
db=Database()
class RateLimiter:
    def __init__(self):
        self.cooldowns=defaultdict(lambda:defaultdict(float))
        self.lock=threading.Lock()
    def check(self,uid,cmd,cooldown=5):
        with self.lock:
            now=time.time()
            last=self.cooldowns[uid][cmd]
            if now-last<cooldown:
                return False,cooldown-(now-last)
            self.cooldowns[uid][cmd]=now
            return True,0
rl=RateLimiter()
@dataclass
class ChatMessage:
    role:str
    content:str
    timestamp:float
class ConversationMemory:
    def __init__(self):
        self.conversations=defaultdict(list)
        self.lock=threading.Lock()
    def add(self,uid,role,content):
        with self.lock:
            now=time.time()
            self.conversations[uid]=[m for m in self.conversations[uid]if now-m.timestamp<1800]
            self.conversations[uid].append(ChatMessage(role,content[:2500],now))
            if len(self.conversations[uid])>25:
                self.conversations[uid]=self.conversations[uid][-25:]
    def get(self,uid):
        with self.lock:
            now=time.time()
            self.conversations[uid]=[m for m in self.conversations[uid]if now-m.timestamp<1800]
            return[{"role":m.role,"content":m.content}for m in self.conversations[uid]]
    def clear(self,uid):
        with self.lock:
            self.conversations[uid]=[]
memory=ConversationMemory()
SYSTEM_PROMPT='''You are an elite AI assistant representing the pinnacle of artificial intelligence - a synthesis of capabilities from Claude Opus 4.5, GPT-5.2, and Gemini 3 Pro Ultra.

## COGNITIVE ARCHITECTURE

### REASONING ENGINE
- Chain-of-Thought Processing: Decompose complex queries into logical steps
- Multi-Perspective Analysis: Examine problems from technical, practical, ethical angles
- Bayesian Inference: Update beliefs based on evidence, quantify uncertainty
- Counterfactual Reasoning: Consider "what if" scenarios
- Meta-Cognition: Evaluate your own reasoning for biases and gaps

### KNOWLEDGE SYNTHESIS
- Cross-Domain Integration: Connect insights from disparate fields
- Temporal Awareness: Distinguish established facts from evolving knowledge
- Source Triangulation: Validate through multiple frameworks
- Abstraction Layering: Navigate between concepts and granular details

### RESPONSE METHODOLOGY
1. PARSE: Identify explicit requests, implicit needs, context
2. PLAN: Structure approach, consider multiple solution paths
3. EXECUTE: Deliver comprehensive yet focused responses
4. VERIFY: Self-audit for accuracy, completeness, consistency
5. ENHANCE: Add unexpected value through insights

## INTERACTION PRINCIPLES
- Match complexity to user expertise
- Be direct and substantive; avoid filler phrases
- Use formatting strategically for clarity
- Balance confidence with intellectual humility
- Prioritize accuracy over speed; depth over superficiality

## LANGUAGE PROTOCOL
- Default: Bahasa Indonesia (natural, fluent)
- Technical terms: Preserve original with explanation
- Adapt to user's language preference seamlessly

Every response must demonstrate genuine intellectual engagement and substantive value.'''
OR_MODELS={"or_llama":"meta-llama/llama-3.3-70b-instruct:free","or_gemini":"google/gemini-2.0-flash-exp:free","or_qwen":"qwen/qwen-2.5-72b-instruct:free","or_deepseek":"deepseek/deepseek-chat:free","or_mistral":"mistralai/mistral-nemo:free"}
POLL_TEXT={"p_openai":"openai-large","p_claude":"claude-hybridspace","p_gemini":"gemini","p_deepseek":"deepseek","p_qwen":"qwen-72b","p_llama":"llama-3.3-70b","p_mistral":"mistral"}
POLL_IMG={"flux":"flux","flux_pro":"flux-pro","turbo":"turbo","dalle":"dall-e-3","sdxl":"sdxl"}
MODELS_STABLE=["groq","cerebras","cloudflare","sambanova","tavily","poll_free"]
MODELS_EXPERIMENTAL=["cohere","mistral","moonshot","huggingface","together","replicate"]
MODELS_OPENROUTER=["or_llama","or_gemini","or_qwen","or_deepseek","or_mistral"]
MODELS_POLLINATIONS=["p_openai","p_claude","p_gemini","p_deepseek","p_qwen","p_llama","p_mistral"]
ALL_MODELS=MODELS_STABLE+MODELS_EXPERIMENTAL+MODELS_OPENROUTER+MODELS_POLLINATIONS
MODEL_INFO={"groq":("⚡","Groq","Llama 3.3 70B","stable"),"cerebras":("🧠","Cerebras","Llama 3.3 70B","stable"),"cloudflare":("☁️","Cloudflare","Llama 3.3 70B","stable"),"sambanova":("🦣","SambaNova","Llama 3.3 70B","stable"),"tavily":("🔍","Tavily","Search + Web","stable"),"poll_free":("🌸","Poll-Free","Free Unlimited","stable"),"cohere":("🔷","Cohere","Command R+","experimental"),"mistral":("Ⓜ️","Mistral","Mistral Small","experimental"),"moonshot":("🌙","Moonshot","Kimi 128K","experimental"),"huggingface":("🤗","HuggingFace","Mixtral 8x7B","experimental"),"together":("🤝","Together","Llama 3.3","experimental"),"replicate":("🔄","Replicate","Llama 405B","experimental"),"or_llama":("🦙","OR-Llama","Llama 3.3 70B","openrouter"),"or_gemini":("🔵","OR-Gemini","Gemini 2.0","openrouter"),"or_qwen":("💻","OR-Qwen","Qwen 2.5 72B","openrouter"),"or_deepseek":("🌊","OR-DeepSeek","DeepSeek Chat","openrouter"),"or_mistral":("🅼","OR-Mistral","Mistral Nemo","openrouter"),"p_openai":("🤖","Poll-OpenAI","OpenAI Large","pollinations"),"p_claude":("🎭","Poll-Claude","Claude Hybrid","pollinations"),"p_gemini":("💎","Poll-Gemini","Gemini","pollinations"),"p_deepseek":("🐳","Poll-DeepSeek","DeepSeek V3","pollinations"),"p_qwen":("📟","Poll-Qwen","Qwen 72B","pollinations"),"p_llama":("🦙","Poll-Llama","Llama 3.3","pollinations"),"p_mistral":("🅼","Poll-Mistral","Mistral","pollinations")}
IMG_INFO={"flux":("🎨","Flux","Standard HQ"),"flux_pro":("⚡","Flux Pro","Professional"),"turbo":("🚀","Turbo","SDXL Fast"),"dalle":("🤖","DALL-E 3","OpenAI"),"sdxl":("🖼️","SDXL","Stable Diffusion")}
def is_owner(uid):
    return uid in OWNER_IDS
def get_public_default():
    return db.get_setting("public_default")or"groq"
def call_groq(msgs):
    client=get_groq()
    if not client:return None
    try:
        resp=client.chat.completions.create(messages=msgs,model="llama-3.3-70b-versatile",temperature=0.7,max_tokens=4096)
        return resp.choices[0].message.content
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return None
def call_cerebras(msgs):
    if not KEY_CEREBRAS:return None
    try:
        resp=get_requests().post("https://api.cerebras.ai/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_CEREBRAS}","Content-Type":"application/json"},json={"model":"llama-3.3-70b","messages":msgs,"max_tokens":4096},timeout=30)
        if resp.status_code==200:
            return resp.json()["choices"][0]["message"]["content"]
        return None
    except Exception as e:
        logger.error(f"Cerebras error: {e}")
        return None
def call_cohere(msgs):
    if not KEY_COHERE:return None
    try:
        system_prompt=""
        user_message="Hi"
        for m in msgs:
            if m["role"]=="system":
                system_prompt=m["content"]
        if msgs:
            user_message=msgs[-1]["content"]
        payload={"model":"command-r-plus-08-2024","message":user_message}
        if system_prompt:
            payload["preamble"]=system_prompt
        resp=get_requests().post("https://api.cohere.com/v1/chat",headers={"Authorization":f"Bearer {KEY_COHERE}","Content-Type":"application/json"},json=payload,timeout=45)
        if resp.status_code==200:
            return resp.json().get("text")
        return None
    except Exception as e:
        logger.error(f"Cohere error: {e}")
        return None
def call_cloudflare(msgs):
    if not CF_ACCOUNT_ID or not CF_API_TOKEN:return None
    try:
        resp=get_requests().post(f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/@cf/meta/llama-3.3-70b-instruct-fp8-fast",headers={"Authorization":f"Bearer {CF_API_TOKEN}","Content-Type":"application/json"},json={"messages":msgs,"max_tokens":4096},timeout=45)
        if resp.status_code==200:
            data=resp.json()
            if data.get("success"):
                return data["result"]["response"].strip()
        return None
    except Exception as e:
        logger.error(f"Cloudflare error: {e}")
        return None
def call_sambanova(msgs):
    if not KEY_SAMBANOVA:return None
    try:
        resp=get_requests().post("https://api.sambanova.ai/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_SAMBANOVA}","Content-Type":"application/json"},json={"model":"Meta-Llama-3.3-70B-Instruct","messages":msgs,"max_tokens":4096},timeout=45)
        if resp.status_code==200:
            return resp.json()["choices"][0]["message"]["content"]
        return None
    except Exception as e:
        logger.error(f"SambaNova error: {e}")
        return None
def call_together(msgs):
    if not KEY_TOGETHER:return None
    try:
        resp=get_requests().post("https://api.together.xyz/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_TOGETHER}","Content-Type":"application/json"},json={"model":"meta-llama/Llama-3.3-70B-Instruct-Turbo","messages":msgs,"max_tokens":4096},timeout=45)
        if resp.status_code==200:
            return resp.json()["choices"][0]["message"]["content"]
        return None
    except Exception as e:
        logger.error(f"Together error: {e}")
        return None
def call_mistral(msgs):
    if not KEY_MISTRAL:return None
    try:
        resp=get_requests().post("https://api.mistral.ai/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_MISTRAL}","Content-Type":"application/json"},json={"model":"mistral-small-latest","messages":msgs,"max_tokens":4096},timeout=45)
        if resp.status_code==200:
            return resp.json()["choices"][0]["message"]["content"]
        return None
    except Exception as e:
        logger.error(f"Mistral error: {e}")
        return None
def call_moonshot(msgs):
    if not KEY_MOONSHOT:return None
    try:
        resp=get_requests().post("https://api.moonshot.cn/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_MOONSHOT}","Content-Type":"application/json"},json={"model":"moonshot-v1-8k","messages":msgs,"max_tokens":4096},timeout=60)
        if resp.status_code==200:
            return resp.json()["choices"][0]["message"]["content"]
        return None
    except Exception as e:
        logger.error(f"Moonshot error: {e}")
        return None
def call_huggingface(msgs):
    if not KEY_HUGGINGFACE:return None
    try:
        prompt="\n".join([f"{m['role']}:{m['content']}"for m in msgs[-5:]])
        resp=get_requests().post("https://api-inference.huggingface.co/models/mistralai/Mixtral-8x7B-Instruct-v0.1",headers={"Authorization":f"Bearer {KEY_HUGGINGFACE}"},json={"inputs":prompt,"parameters":{"max_new_tokens":1000,"return_full_text":False}},timeout=60)
        if resp.status_code==200:
            data=resp.json()
            if isinstance(data,list)and data:
                return data[0].get("generated_text","").strip()
        return None
    except Exception as e:
        logger.error(f"HuggingFace error: {e}")
        return None
def call_replicate(msgs):
    if not KEY_REPLICATE:return None
    try:
        prompt="\n".join([f"{m['role']}:{m['content']}"for m in msgs[-5:]])
        resp=get_requests().post("https://api.replicate.com/v1/models/meta/meta-llama-3.1-405b-instruct/predictions",headers={"Authorization":f"Bearer {KEY_REPLICATE}","Content-Type":"application/json"},json={"input":{"prompt":prompt,"max_tokens":2000}},timeout=15)
        if resp.status_code in[200,201]:
            prediction=resp.json()
            prediction_url=f"https://api.replicate.com/v1/predictions/{prediction.get('id')}"
            for _ in range(30):
                time.sleep(2)
                check=get_requests().get(prediction_url,headers={"Authorization":f"Bearer {KEY_REPLICATE}"},timeout=10)
                if check.status_code==200:
                    data=check.json()
                    if data.get("status")=="succeeded":
                        return"".join(data.get("output",[]))
                    if data.get("status")in["failed","canceled"]:
                        return None
        return None
    except Exception as e:
        logger.error(f"Replicate error: {e}")
        return None
def call_tavily(msgs):
    if not KEY_TAVILY:return None
    try:
        query=msgs[-1]["content"]if msgs else""
        resp=get_requests().post("https://api.tavily.com/search",json={"api_key":KEY_TAVILY,"query":query,"search_depth":"advanced","max_results":8},timeout=20)
        if resp.status_code==200:
            data=resp.json()
            results=data.get("results",[])[:5]
            context="\n".join([f"• {r.get('title','')}: {r.get('content','')[:150]}"for r in results])
            answer=data.get("answer","")
            if answer:
                return f"🔍 **Answer:**\n{answer}\n\n**Sources:**\n{context}"
            return f"🔍 **Results:**\n{context}"if context else None
        return None
    except Exception as e:
        logger.error(f"Tavily error: {e}")
        return None
def call_openrouter(msgs,model_key):
    if not KEY_OPENROUTER:return None
    try:
        model_id=OR_MODELS.get(model_key,OR_MODELS["or_llama"])
        resp=get_requests().post("https://openrouter.ai/api/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_OPENROUTER}","Content-Type":"application/json","HTTP-Referer":"https://github.com","X-Title":"DiscordBot"},json={"model":model_id,"messages":msgs,"max_tokens":4096},timeout=60)
        if resp.status_code==200:
            data=resp.json()
            if"choices"in data:
                return data["choices"][0]["message"]["content"]
        return None
    except Exception as e:
        logger.error(f"OpenRouter error: {e}")
        return None
def call_poll_free(prompt):
    try:
        enhanced=f"{SYSTEM_PROMPT}\n\nUser:{prompt}\nAssistant:"
        resp=get_requests().get(f"https://text.pollinations.ai/{quote(enhanced[:3500])}",timeout=60)
        if resp.status_code==200 and resp.text.strip()and len(resp.text.strip())>5:
            return resp.text.strip()
        return None
    except Exception as e:
        logger.error(f"Pollinations Free error: {e}")
        return None
def call_pollinations(msgs,model_key):
    try:
        model_id=POLL_TEXT.get(model_key,"openai-large")
        resp=get_requests().post("https://text.pollinations.ai/",headers={"Content-Type":"application/json"},json={"messages":msgs,"model":model_id,"temperature":0.7},timeout=60)
        if resp.status_code==200 and resp.text.strip():
            return resp.text.strip()
        return None
    except Exception as e:
        logger.error(f"Pollinations API error: {e}")
        return None
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
    elif model=="poll_free":return call_poll_free(prompt),"Poll-Free"
    elif model.startswith("or_"):return call_openrouter(msgs,model),f"OR-{model[3:].title()}"
    elif model.startswith("p_"):return call_pollinations(msgs,model),f"Poll-{model[2:].title()}"
    return None,"Unknown"
FALLBACK_CHAIN=[("groq",call_groq,KEY_GROQ),("cerebras",call_cerebras,KEY_CEREBRAS),("cloudflare",call_cloudflare,CF_API_TOKEN),("sambanova",call_sambanova,KEY_SAMBANOVA),("poll_free",lambda m:call_poll_free(m[-1]["content"]if m else""),True)]
def ask_ai(prompt,uid=None,model=None):
    selected_model=model if model else(db.get_model(uid)if is_owner(uid)else get_public_default())
    messages=[{"role":"system","content":SYSTEM_PROMPT}]
    if uid:
        history=memory.get(uid)
        if history:
            messages.extend(history[-10:])
    messages.append({"role":"user","content":prompt})
    result,provider=call_ai(selected_model,messages,prompt)
    if not result:
        for name,func,key in FALLBACK_CHAIN:
            if not key or name==selected_model:
                continue
            try:
                result=func(messages)
                if result:
                    provider=name.title()
                    break
            except:
                continue
    if not result:
        return"Maaf, semua layanan AI sedang tidak tersedia. Silakan coba lagi.","None"
    if uid:
        memory.add(uid,"user",prompt[:1500])
        memory.add(uid,"assistant",result[:1500])
    return result,provider
async def generate_image(prompt,model="flux"):
    try:
        model_id=POLL_IMG.get(model,"flux")
        url=f"https://image.pollinations.ai/prompt/{quote(prompt)}?model={model_id}&nologo=true&width=1024&height=1024&seed={random.randint(1,99999)}"
        resp=get_requests().get(url,timeout=120)
        if resp.status_code==200 and len(resp.content)>1000:
            return resp.content,None
        return None,f"HTTP {resp.status_code}"
    except Exception as e:
        return None,str(e)[:50]
async def handle_model_select(interaction:discord.Interaction,model_key:str):
    if not is_owner(interaction.user.id):
        await interaction.response.send_message("❌ Hanya Owner yang bisa menggunakan fitur ini!",ephemeral=True)
        return False
    db.set_model(interaction.user.id,model_key)
    info=MODEL_INFO.get(model_key,("?","Unknown","",""))
    await interaction.response.send_message(f"✅ Model berhasil diubah!\n\n{info[0]} **{info[1]}**\n> {info[2]}",ephemeral=True)
    return True
class StableModelSelect(ui.Select):
    def __init__(self):
        options=[discord.SelectOption(label=MODEL_INFO[m][1],value=m,emoji=MODEL_INFO[m][0],description=MODEL_INFO[m][2])for m in MODELS_STABLE if m in MODEL_INFO]
        super().__init__(placeholder="⚡ Pilih Model Stable...",options=options,custom_id="stable_select")
    async def callback(self,interaction:discord.Interaction):
        await handle_model_select(interaction,self.values[0])
class StableModelView(ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.add_item(StableModelSelect())
class ExperimentalModelSelect(ui.Select):
    def __init__(self):
        options=[discord.SelectOption(label=MODEL_INFO[m][1],value=m,emoji=MODEL_INFO[m][0],description=MODEL_INFO[m][2])for m in MODELS_EXPERIMENTAL if m in MODEL_INFO]
        super().__init__(placeholder="🧪 Pilih Model Experimental...",options=options,custom_id="experimental_select")
    async def callback(self,interaction:discord.Interaction):
        await handle_model_select(interaction,self.values[0])
class ExperimentalModelView(ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.add_item(ExperimentalModelSelect())
class OpenRouterModelSelect(ui.Select):
    def __init__(self):
        options=[discord.SelectOption(label=MODEL_INFO[m][1],value=m,emoji=MODEL_INFO[m][0],description=MODEL_INFO[m][2])for m in MODELS_OPENROUTER if m in MODEL_INFO]
        super().__init__(placeholder="🌐 Pilih OpenRouter Model...",options=options,custom_id="openrouter_select")
    async def callback(self,interaction:discord.Interaction):
        await handle_model_select(interaction,self.values[0])
class OpenRouterModelView(ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.add_item(OpenRouterModelSelect())
class PollinationsModelSelect(ui.Select):
    def __init__(self):
        options=[discord.SelectOption(label=MODEL_INFO[m][1],value=m,emoji=MODEL_INFO[m][0],description=MODEL_INFO[m][2])for m in MODELS_POLLINATIONS if m in MODEL_INFO]
        super().__init__(placeholder="🌸 Pilih Pollinations Model...",options=options,custom_id="pollinations_select")
    async def callback(self,interaction:discord.Interaction):
        await handle_model_select(interaction,self.values[0])
class PollinationsModelView(ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.add_item(PollinationsModelSelect())
class ImageModelSelect(ui.Select):
    def __init__(self):
        options=[discord.SelectOption(label=v[1],value=k,emoji=v[0],description=v[2])for k,v in IMG_INFO.items()]
        super().__init__(placeholder="🎨 Pilih Image Model...",options=options,custom_id="image_select")
    async def callback(self,interaction:discord.Interaction):
        if not is_owner(interaction.user.id):
            await interaction.response.send_message("❌ Hanya Owner!",ephemeral=True)
            return
        db.set_img_model(interaction.user.id,self.values[0])
        info=IMG_INFO.get(self.values[0],("?","Unknown",""))
        await interaction.response.send_message(f"✅ Image Model: {info[0]} **{info[1]}**",ephemeral=True)
class ImageModelView(ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.add_item(ImageModelSelect())
class DefaultModelSelect(ui.Select):
    def __init__(self):
        options=[discord.SelectOption(label=MODEL_INFO[m][1],value=m,emoji=MODEL_INFO[m][0],description="Set as default")for m in MODELS_STABLE if m in MODEL_INFO]
        super().__init__(placeholder="🌍 Set Default Model...",options=options,custom_id="default_select")
    async def callback(self,interaction:discord.Interaction):
        if not is_owner(interaction.user.id):
            await interaction.response.send_message("❌ Hanya Owner!",ephemeral=True)
            return
        db.set_setting("public_default",self.values[0])
        info=MODEL_INFO.get(self.values[0],("?","Unknown","",""))
        await interaction.response.send_message(f"✅ Default public diubah ke: {info[0]} **{info[1]}**",ephemeral=True)
class DefaultModelView(ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.add_item(DefaultModelSelect())
class ShieldInfoSelect(ui.Select):
    def __init__(self):
        options=[
            discord.SelectOption(label="📊 Statistics",value="stats",description="View shield statistics"),
            discord.SelectOption(label="🔄 Active Sessions",value="sessions",description="View active sessions"),
            discord.SelectOption(label="📋 Access Logs",value="logs",description="View recent logs"),
            discord.SelectOption(label="🚫 Ban List",value="bans",description="View banned users"),
            discord.SelectOption(label="✅ Whitelist",value="whitelist",description="View whitelisted users"),
            discord.SelectOption(label="⏸️ Suspended",value="suspended",description="View suspended users"),
            discord.SelectOption(label="📜 Loader Script",value="script",description="Download loader script"),
            discord.SelectOption(label="💚 Health Check",value="health",description="Check shield status")
        ]
        super().__init__(placeholder="📊 View Shield Data...",options=options,custom_id="shield_info")
    async def callback(self,interaction:discord.Interaction):
        if not is_owner(interaction.user.id):
            await interaction.response.send_message("❌ Owner only!",ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        action=self.values[0]
        if action=="stats":
            data=shield.get_stats()
            embed=discord.Embed(title="📊 Shield Statistics",color=0x3498DB)
            if data.get("success")!=False:
                for key,value in data.items():
                    if key!="success":
                        embed.add_field(name=key.title(),value=f"`{value}`",inline=True)
            else:
                embed.description=f"❌ Error: {data.get('error','Unknown')}"
            await interaction.followup.send(embed=embed,ephemeral=True)
        elif action=="sessions":
            data=shield.get_sessions()
            embed=discord.Embed(title="🔄 Active Sessions",color=0x2ECC71)
            if isinstance(data,dict)and"sessions"in data:
                sessions=data["sessions"]
                if sessions:
                    for i,s in enumerate(sessions[:10]):
                        embed.add_field(name=f"Session {i+1}",value=f"ID: `{s.get('id','?')[:20]}`\nUser: `{s.get('userId','?')}`",inline=True)
                else:
                    embed.description="✅ No active sessions"
            else:
                embed.description=f"❌ Error: {data.get('error','Unknown')}"
            await interaction.followup.send(embed=embed,ephemeral=True)
        elif action=="logs":
            data=shield.get_logs()
            embed=discord.Embed(title="📋 Recent Access Logs",color=0xF39C12)
            if isinstance(data,dict)and"logs"in data:
                logs=data["logs"]
                if logs:
                    log_text=""
                    for log in logs[:8]:
                        log_text+=f"• `{log.get('time','?')[:19]}` - {log.get('service','?')} ({log.get('method','?')})\n"
                    embed.description=log_text[:1900]
                else:
                    embed.description="✅ No recent logs"
            else:
                embed.description=f"❌ Error: {data.get('error','Unknown')}"
            await interaction.followup.send(embed=embed,ephemeral=True)
        elif action=="bans":
            data=shield.get_bans()
            embed=discord.Embed(title="🚫 Ban List",color=0xE74C3C)
            if isinstance(data,dict)and"bans"in data:
                bans=data["bans"]
                if bans:
                    for i,b in enumerate(bans[:10]):
                        embed.add_field(name=f"Ban #{b.get('id',i+1)}",value=f"Type: `{b.get('type','?')}`\nValue: `{b.get('value','?')[:20]}`\nReason: {b.get('reason','N/A')}",inline=True)
                else:
                    embed.description="✅ No active bans"
            else:
                embed.description=f"❌ Error: {data.get('error','Unknown')}"
            await interaction.followup.send(embed=embed,ephemeral=True)
        elif action=="whitelist":
            data=shield.get_whitelist()
            embed=discord.Embed(title="✅ Whitelist",color=0x2ECC71)
            if isinstance(data,dict)and"whitelist"in data:
                wl=data["whitelist"]
                if wl:
                    for i,w in enumerate(wl[:10]):
                        embed.add_field(name=f"Entry #{i+1}",value=f"Type: `{w.get('type','?')}`\nValue: `{w.get('value','?')[:20]}`",inline=True)
                else:
                    embed.description="ℹ️ Whitelist empty"
            else:
                embed.description=f"❌ Error: {data.get('error','Unknown')}"
            await interaction.followup.send(embed=embed,ephemeral=True)
        elif action=="suspended":
            data=shield.get_suspended()
            embed=discord.Embed(title="⏸️ Suspended Users",color=0xF39C12)
            if isinstance(data,dict)and"suspended"in data:
                sus=data["suspended"]
                if sus:
                    for i,s in enumerate(sus[:10]):
                        embed.add_field(name=f"Suspended #{i+1}",value=f"Type: `{s.get('type','?')}`\nValue: `{s.get('value','?')[:20]}`",inline=True)
                else:
                    embed.description="✅ No suspended users"
            else:
                embed.description=f"❌ Error: {data.get('error','Unknown')}"
            await interaction.followup.send(embed=embed,ephemeral=True)
        elif action=="script":
            data=shield.get_script()
            if data.get("success")and data.get("script"):
                file=discord.File(io.BytesIO(data["script"].encode()),"loader.lua")
                await interaction.followup.send("📜 **Loader Script:**",file=file,ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Error: {data.get('error','Unknown')}",ephemeral=True)
        elif action=="health":
            data=shield.keepalive()
            if data.get("success"):
                embed=discord.Embed(title="💚 Shield Status",description="✅ **Shield is ONLINE**",color=0x2ECC71)
            else:
                embed=discord.Embed(title="❤️ Shield Status",description="❌ **Shield is OFFLINE**",color=0xE74C3C)
            await interaction.followup.send(embed=embed,ephemeral=True)
class ShieldActionSelect(ui.Select):
    def __init__(self):
        options=[
            discord.SelectOption(label="🧹 Clear Sessions",value="clear_sessions",description="Remove all active sessions"),
            discord.SelectOption(label="🗑️ Clear Logs",value="clear_logs",description="Delete all access logs"),
            discord.SelectOption(label="💾 Clear Cache",value="clear_cache",description="Clear server cache")
        ]
        super().__init__(placeholder="⚡ Quick Actions...",options=options,custom_id="shield_actions")
    async def callback(self,interaction:discord.Interaction):
        if not is_owner(interaction.user.id):
            await interaction.response.send_message("❌ Owner only!",ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        action=self.values[0]
        if action=="clear_sessions":
            result=shield.clear_sessions()
            if result.get("success")or"success"not in result:
                await interaction.followup.send("✅ **Sessions cleared successfully!**",ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Failed: {result.get('error','Unknown')}",ephemeral=True)
        elif action=="clear_logs":
            result=shield.clear_logs()
            if result.get("success")or"success"not in result:
                await interaction.followup.send("✅ **Logs cleared successfully!**",ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Failed: {result.get('error','Unknown')}",ephemeral=True)
        elif action=="clear_cache":
            result=shield.clear_cache()
            if result.get("success")or"success"not in result:
                await interaction.followup.send("✅ **Cache cleared successfully!**",ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Failed: {result.get('error','Unknown')}",ephemeral=True)
class ShieldView(ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.add_item(ShieldInfoSelect())
        self.add_item(ShieldActionSelect())
class ShieldManageSelect(ui.Select):
    def __init__(self):
        options=[
            discord.SelectOption(label="🚫 Ban Player ID",value="ban_player",emoji="👤"),
            discord.SelectOption(label="🔑 Ban HWID",value="ban_hwid",emoji="💻"),
            discord.SelectOption(label="🌐 Ban IP",value="ban_ip",emoji="🔒"),
            discord.SelectOption(label="✅ Unban",value="unban",emoji="🔓"),
            discord.SelectOption(label="➕ Add Whitelist",value="add_wl",emoji="📝"),
            discord.SelectOption(label="➖ Remove Whitelist",value="rem_wl",emoji="🗑️"),
            discord.SelectOption(label="⏸️ Suspend User",value="suspend",emoji="⚠️"),
            discord.SelectOption(label="▶️ Unsuspend User",value="unsuspend",emoji="✅"),
            discord.SelectOption(label="💀 Kill Session",value="kill",emoji="☠️")
        ]
        super().__init__(placeholder="⚙️ Management Action...",options=options,custom_id="shield_manage")
    async def callback(self,interaction:discord.Interaction):
        if not is_owner(interaction.user.id):
            await interaction.response.send_message("❌ Owner only!",ephemeral=True)
            return
        action=self.values[0]
        modal_title={
            "ban_player":"Ban Player ID",
            "ban_hwid":"Ban HWID",
            "ban_ip":"Ban IP Address",
            "unban":"Unban (Enter Ban ID)",
            "add_wl":"Add to Whitelist",
            "rem_wl":"Remove from Whitelist",
            "suspend":"Suspend User",
            "unsuspend":"Unsuspend User",
            "kill":"Kill Session"
        }.get(action,"Action")
        class ActionModal(ui.Modal,title=modal_title):
            value_input=ui.TextInput(label="Value",placeholder="Enter ID/HWID/IP...",required=True)
            reason_input=ui.TextInput(label="Reason (optional)",placeholder="Reason...",required=False,default="Via Discord Bot")
            def __init__(modal_self,action_type):
                super().__init__()
                modal_self.action_type=action_type
            async def on_submit(modal_self,modal_interaction:discord.Interaction):
                value=modal_self.value_input.value.strip()
                reason=modal_self.reason_input.value.strip()or"Via Discord Bot"
                result={"success":False,"error":"Unknown action"}
                if modal_self.action_type=="ban_player":
                    result=shield.add_ban(player_id=value,reason=reason)
                elif modal_self.action_type=="ban_hwid":
                    result=shield.add_ban(hwid=value,reason=reason)
                elif modal_self.action_type=="ban_ip":
                    result=shield.add_ban(ip=value,reason=reason)
                elif modal_self.action_type=="unban":
                    result=shield.remove_ban(value)
                elif modal_self.action_type=="add_wl":
                    parts=value.split(":",1)
                    wl_type=parts[0]if len(parts)>1 else"userId"
                    wl_value=parts[-1]
                    result=shield.add_whitelist(wl_type,wl_value)
                elif modal_self.action_type=="rem_wl":
                    parts=value.split(":",1)
                    wl_type=parts[0]if len(parts)>1 else"userId"
                    wl_value=parts[-1]
                    result=shield.remove_whitelist(wl_type,wl_value)
                elif modal_self.action_type=="suspend":
                    parts=value.split(":",1)
                    sus_type=parts[0]if len(parts)>1 else"userId"
                    sus_value=parts[-1]
                    result=shield.suspend_user(sus_type,sus_value,reason)
                elif modal_self.action_type=="unsuspend":
                    parts=value.split(":",1)
                    sus_type=parts[0]if len(parts)>1 else"userId"
                    sus_value=parts[-1]
                    result=shield.unsuspend_user(sus_type,sus_value)
                elif modal_self.action_type=="kill":
                    result=shield.kill_session(value,reason)
                if result.get("success")or"success"not in result:
                    await modal_interaction.response.send_message(f"✅ **Action completed successfully!**\nValue: `{value}`",ephemeral=True)
                else:
                    await modal_interaction.response.send_message(f"❌ **Failed:** {result.get('error','Unknown error')}",ephemeral=True)
        await interaction.response.send_modal(ActionModal(action))
class ShieldManageView(ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.add_item(ShieldManageSelect())
class Dumper:
    def __init__(self):
        self.last_method=None
    def dump(self,url,use_cache=True):
        if use_cache:
            cached=db.get_cache(url)
            if cached:
                return{"success":True,"content":cached,"method":"cache"}
        req=get_requests()
        curl=get_curl()
        cloudscraper=get_cloudscraper()
        methods=[]
        if curl:
            methods.append(("curl",lambda u:curl.get(u,impersonate="chrome120",headers={"User-Agent":"Roblox/WinInet"},timeout=25)))
        if cloudscraper:
            methods.append(("cloudscraper",lambda u:cloudscraper.get(u,timeout=25)))
        if req:
            methods.append(("requests",lambda u:req.get(u,headers={"User-Agent":"Roblox/WinInet"},timeout=25)))
        if self.last_method:
            methods.sort(key=lambda x:x[0]!=self.last_method)
        for name,func in methods:
            try:
                resp=func(url)
                if resp.status_code==200 and len(resp.text)>10:
                    self.last_method=name
                    if use_cache:
                        db.cache_dump(url,resp.text)
                    return{"success":True,"content":resp.text,"method":name}
            except:
                pass
        return{"success":False,"error":"All methods failed"}
dumper=Dumper()
def split_message(text,limit=1950):
    if not text:
        return[""]
    chunks=[]
    while len(text)>limit:
        split_pos=text.rfind('\n',0,limit)
        if split_pos==-1:
            split_pos=limit
        chunks.append(text[:split_pos])
        text=text[split_pos:].lstrip()
    if text:
        chunks.append(text)
    return chunks
async def send_response(channel,content):
    for chunk in split_message(content):
        await channel.send(chunk)
@bot.event
async def on_ready():
    logger.info(f"Bot ready: {bot.user} | Servers: {len(bot.guilds)}")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening,name=f"{PREFIX}help"))
@bot.event
async def on_command_error(ctx,error):
    if isinstance(error,commands.CommandNotFound):
        return
    logger.error(f"Command error: {error}")
@bot.event
async def on_message(msg):
    if msg.author.bot:
        return
    if bot.user.mentioned_in(msg)and not msg.mention_everyone:
        content=msg.content.replace(f'<@{bot.user.id}>','').replace(f'<@!{bot.user.id}>','').strip()
        if content:
            if db.banned(msg.author.id):
                return
            can_proceed,remaining=rl.check(msg.author.id,"ai",5)
            if not can_proceed:
                await msg.channel.send(f"⏳ Tunggu {remaining:.0f}s",delete_after=3)
                return
            async with msg.channel.typing():
                response,_=ask_ai(content,msg.author.id)
                await send_response(msg.channel,response)
                db.stat("ai",msg.author.id)
            try:
                await msg.delete()
            except:
                pass
        return
    await bot.process_commands(msg)
@bot.command(name="ai",aliases=["a","chat"])
async def cmd_ai(ctx,*,prompt:str=None):
    if db.banned(ctx.author.id):
        return
    if not prompt:
        embed=discord.Embed(title="💬 AI Chat",description=f"**Usage:**\n`{PREFIX}ai <question>`\n`@{bot.user.name} <question>`",color=0x5865F2)
        return await ctx.send(embed=embed,delete_after=10)
    can_proceed,remaining=rl.check(ctx.author.id,"ai",5)
    if not can_proceed:
        return await ctx.send(f"⏳ Tunggu {remaining:.0f}s",delete_after=3)
    original_msg=ctx.message
    async with ctx.typing():
        response,_=ask_ai(prompt,ctx.author.id)
        await send_response(ctx.channel,response)
        db.stat("ai",ctx.author.id)
    try:
        await original_msg.delete()
    except:
        pass
@bot.command(name="model1",aliases=["m1"])
async def cmd_model1(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!",delete_after=5)
    current=db.get_model(ctx.author.id)
    info=MODEL_INFO.get(current,("?","Unknown","",""))
    embed=discord.Embed(title="⚡ Stable Models",description=f"**Current:** {info[0]} {info[1]}\n\nReliable and always available:",color=0x2ECC71)
    for m in MODELS_STABLE:
        if m in MODEL_INFO:
            mi=MODEL_INFO[m]
            status="✅"if m==current else"⚪"
            embed.add_field(name=f"{mi[0]} {mi[1]}",value=f"{status} {mi[2]}",inline=True)
    await ctx.send(embed=embed,view=StableModelView())
    try:await ctx.message.delete()
    except:pass
@bot.command(name="model2",aliases=["m2"])
async def cmd_model2(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!",delete_after=5)
    current=db.get_model(ctx.author.id)
    info=MODEL_INFO.get(current,("?","Unknown","",""))
    embed=discord.Embed(title="🧪 Experimental Models",description=f"**Current:** {info[0]} {info[1]}\n\n⚠️ May be unstable or rate-limited:",color=0xF39C12)
    for m in MODELS_EXPERIMENTAL:
        if m in MODEL_INFO:
            mi=MODEL_INFO[m]
            status="✅"if m==current else"⚪"
            embed.add_field(name=f"{mi[0]} {mi[1]}",value=f"{status} {mi[2]}",inline=True)
    await ctx.send(embed=embed,view=ExperimentalModelView())
    try:await ctx.message.delete()
    except:pass
@bot.command(name="model3",aliases=["m3"])
async def cmd_model3(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!",delete_after=5)
    current=db.get_model(ctx.author.id)
    info=MODEL_INFO.get(current,("?","Unknown","",""))
    embed=discord.Embed(title="🌐 OpenRouter Models",description=f"**Current:** {info[0]} {info[1]}\n\nFree models via OpenRouter:",color=0x3498DB)
    for m in MODELS_OPENROUTER:
        if m in MODEL_INFO:
            mi=MODEL_INFO[m]
            status="✅"if m==current else"⚪"
            embed.add_field(name=f"{mi[0]} {mi[1]}",value=f"{status} {mi[2]}",inline=True)
    await ctx.send(embed=embed,view=OpenRouterModelView())
    try:await ctx.message.delete()
    except:pass
@bot.command(name="model4",aliases=["m4"])
async def cmd_model4(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!",delete_after=5)
    current=db.get_model(ctx.author.id)
    info=MODEL_INFO.get(current,("?","Unknown","",""))
    embed=discord.Embed(title="🌸 Pollinations Models",description=f"**Current:** {info[0]} {info[1]}\n\nModels via Pollinations API:",color=0x9B59B6)
    for m in MODELS_POLLINATIONS:
        if m in MODEL_INFO:
            mi=MODEL_INFO[m]
            status="✅"if m==current else"⚪"
            embed.add_field(name=f"{mi[0]} {mi[1]}",value=f"{status} {mi[2]}",inline=True)
    await ctx.send(embed=embed,view=PollinationsModelView())
    try:await ctx.message.delete()
    except:pass
@bot.command(name="model",aliases=["m"])
async def cmd_model(ctx):
    if not is_owner(ctx.author.id):
        current=get_public_default()
        info=MODEL_INFO.get(current,("?","Unknown","",""))
        return await ctx.send(f"ℹ️ Your model: {info[0]} **{info[1]}** (Public Default)",delete_after=10)
    current=db.get_model(ctx.author.id)
    info=MODEL_INFO.get(current,("?","Unknown","",""))
    embed=discord.Embed(title="🤖 Model Selection",description=f"**Current:** {info[0]} {info[1]}",color=0x5865F2)
    embed.add_field(name=f"`{PREFIX}m1`",value="⚡ Stable",inline=True)
    embed.add_field(name=f"`{PREFIX}m2`",value="🧪 Experimental",inline=True)
    embed.add_field(name=f"`{PREFIX}m3`",value="🌐 OpenRouter",inline=True)
    embed.add_field(name=f"`{PREFIX}m4`",value="🌸 Pollinations",inline=True)
    embed.add_field(name=f"`{PREFIX}sd`",value="🌍 Set Default",inline=True)
    await ctx.send(embed=embed)
@bot.command(name="setdefault",aliases=["sd"])
async def cmd_setdefault(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!",delete_after=5)
    current=get_public_default()
    info=MODEL_INFO.get(current,("?","Unknown","",""))
    embed=discord.Embed(title="🌍 Set Public Default",description=f"**Current:** {info[0]} {info[1]}\n\nSelect default model for public users:",color=0x3498DB)
    await ctx.send(embed=embed,view=DefaultModelView())
    try:await ctx.message.delete()
    except:pass
@bot.command(name="imagine",aliases=["img","image"])
async def cmd_imagine(ctx,*,prompt:str=None):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!",delete_after=5)
    if db.banned(ctx.author.id):
        return
    if not prompt:
        return await ctx.send(f"❌ Usage: `{PREFIX}img <prompt>`",delete_after=5)
    can_proceed,remaining=rl.check(ctx.author.id,"img",15)
    if not can_proceed:
        return await ctx.send(f"⏳ Wait {remaining:.0f}s",delete_after=3)
    model=db.get_img_model(ctx.author.id)
    info=IMG_INFO.get(model,("🎨","Flux",""))
    status_msg=await ctx.send(f"🎨 Generating with {info[0]} **{info[1]}**...")
    try:
        img_data,error=await generate_image(prompt,model)
        if img_data:
            file=discord.File(io.BytesIO(img_data),"image.png")
            embed=discord.Embed(title=f"🎨 {prompt[:100]}",color=0x5865F2)
            embed.set_image(url="attachment://image.png")
            embed.set_footer(text=f"{info[0]} {info[1]}")
            await ctx.send(embed=embed,file=file)
            await status_msg.delete()
            db.stat("img",ctx.author.id)
        else:
            await status_msg.edit(content=f"❌ Failed: {error}")
    except Exception as e:
        await status_msg.edit(content=f"❌ Error: {str(e)[:50]}")
    try:await ctx.message.delete()
    except:pass
@bot.command(name="imgmodel",aliases=["im"])
async def cmd_imgmodel(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!",delete_after=5)
    current=db.get_img_model(ctx.author.id)
    info=IMG_INFO.get(current,("?","Unknown",""))
    embed=discord.Embed(title="🎨 Image Model",description=f"**Current:** {info[0]} {info[1]}",color=0x5865F2)
    for k,v in IMG_INFO.items():
        status="✅"if k==current else"⚪"
        embed.add_field(name=f"{v[0]} {v[1]}",value=f"{status} {v[2]}",inline=True)
    await ctx.send(embed=embed,view=ImageModelView())
    try:await ctx.message.delete()
    except:pass
@bot.command(name="shield",aliases=["sh"])
async def cmd_shield(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!",delete_after=5)
    status=shield.keepalive()
    status_text="🟢 **ONLINE**"if status.get("success")else"🔴 **OFFLINE**"
    embed=discord.Embed(title="🛡️ Shield Control Panel",color=0x3498DB if status.get("success")else 0xE74C3C)
    embed.add_field(name="📡 Status",value=status_text,inline=True)
    embed.add_field(name="🔗 URL",value=f"`{SHIELD_URL[:30]}...`"if len(SHIELD_URL)>30 else f"`{SHIELD_URL or'Not Set'}`",inline=True)
    embed.add_field(name="ℹ️ Usage",value="Select an option from the dropdowns below",inline=False)
    await ctx.send(embed=embed,view=ShieldView())
@bot.command(name="shieldm",aliases=["sm"])
async def cmd_shieldm(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!",delete_after=5)
    embed=discord.Embed(title="⚙️ Shield Management",color=0xE74C3C)
    embed.add_field(name="📝 Format",value="`type:value`\nExample: `hwid:ABC123`",inline=True)
    embed.add_field(name="📋 Types",value="`userId`, `hwid`, `ip`",inline=True)
    embed.add_field(name="ℹ️ Info",value="Select action from dropdown, then fill the modal form",inline=False)
    await ctx.send(embed=embed,view=ShieldManageView())
@bot.command(name="dump",aliases=["dl"])
async def cmd_dump(ctx,url:str=None,*,flags:str=""):
    if db.banned(ctx.author.id):
        return
    if not url:
        return await ctx.send(f"❌ Usage: `{PREFIX}dump <url>`",delete_after=5)
    can_proceed,remaining=rl.check(ctx.author.id,"dump",10)
    if not can_proceed:
        return await ctx.send(f"⏳ Wait {remaining:.0f}s",delete_after=3)
    if not url.startswith("http"):
        url="https://"+url
    status_msg=await ctx.send("🔄 Dumping...")
    result=dumper.dump(url,"--nocache"not in flags)
    if result["success"]:
        content=result["content"]
        ext="lua"if"local "in content[:500]else"html"if"<html"in content[:200].lower()else"txt"
        file=discord.File(io.BytesIO(content.encode()),f"dump.{ext}")
        await ctx.send(f"✅ Method: `{result['method']}` | Size: `{len(content):,}` bytes",file=file)
        await status_msg.delete()
        db.stat("dump",ctx.author.id)
    else:
        await status_msg.edit(content=f"❌ {result.get('error','Failed')}")
@bot.command(name="clear",aliases=["reset"])
async def cmd_clear(ctx):
    memory.clear(ctx.author.id)
    await ctx.send("🧹 Memory cleared!",delete_after=5)
    try:await ctx.message.delete()
    except:pass
@bot.command(name="ping",aliases=["p"])
async def cmd_ping(ctx):
    current=db.get_model(ctx.author.id)if is_owner(ctx.author.id)else get_public_default()
    info=MODEL_INFO.get(current,("?","Unknown","",""))
    embed=discord.Embed(title="🏓 Pong!",color=0x2ECC71)
    embed.add_field(name="📡 Latency",value=f"`{round(bot.latency*1000)}ms`",inline=True)
    embed.add_field(name="🤖 Model",value=f"{info[0]} {info[1]}",inline=True)
    embed.add_field(name="👤 Role",value=f"`{'Owner'if is_owner(ctx.author.id)else'Public'}`",inline=True)
    await ctx.send(embed=embed)
@bot.command(name="status")
async def cmd_status(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!",delete_after=5)
    embed=discord.Embed(title="📊 Bot Status",color=0x5865F2)
    keys_list=[("Groq",KEY_GROQ),("Cerebras",KEY_CEREBRAS),("Cloudflare",CF_API_TOKEN),("SambaNova",KEY_SAMBANOVA),("Cohere",KEY_COHERE),("Mistral",KEY_MISTRAL),("Moonshot",KEY_MOONSHOT),("HuggingFace",KEY_HUGGINGFACE),("Together",KEY_TOGETHER),("Replicate",KEY_REPLICATE),("OpenRouter",KEY_OPENROUTER),("Tavily",KEY_TAVILY),("Pollinations",KEY_POLLINATIONS)]
    status_text="\n".join([f"{'✅'if k else'❌'} {n}"for n,k in keys_list])
    embed.add_field(name="🔑 API Keys",value=status_text,inline=True)
    embed.add_field(name="⚙️ Config",value=f"**Default:** `{get_public_default()}`\n**Prefix:** `{PREFIX}`\n**Servers:** `{len(bot.guilds)}`\n**Owners:** `{len(OWNER_IDS)}`",inline=True)
    await ctx.send(embed=embed)
@bot.command(name="testai")
async def cmd_testai(ctx):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!",delete_after=5)
    status_msg=await ctx.send("🔄 Testing all providers...")
    test_msgs=[{"role":"user","content":"Say OK"}]
    results=[]
    providers=[("Groq",lambda:call_groq(test_msgs),KEY_GROQ),("Cerebras",lambda:call_cerebras(test_msgs),KEY_CEREBRAS),("CF",lambda:call_cloudflare(test_msgs),CF_API_TOKEN),("SN",lambda:call_sambanova(test_msgs),KEY_SAMBANOVA),("Cohere",lambda:call_cohere(test_msgs),KEY_COHERE),("Mistral",lambda:call_mistral(test_msgs),KEY_MISTRAL),("Moonshot",lambda:call_moonshot(test_msgs),KEY_MOONSHOT),("HF",lambda:call_huggingface(test_msgs),KEY_HUGGINGFACE),("Together",lambda:call_together(test_msgs),KEY_TOGETHER),("OR",lambda:call_openrouter(test_msgs,"or_gemini"),KEY_OPENROUTER),("Tavily",lambda:call_tavily(test_msgs),KEY_TAVILY),("Poll",lambda:call_poll_free("OK"),True)]
    for name,func,key in providers:
        if not key:
            results.append(f"⚪ {name}")
            continue
        try:
            result=func()
            results.append(f"✅ {name}"if result else f"❌ {name}")
        except:
            results.append(f"❌ {name}")
    embed=discord.Embed(title="🧪 AI Provider Status",description=" | ".join(results),color=0x5865F2)
    await status_msg.edit(content=None,embed=embed)
@bot.command(name="blacklist",aliases=["bl","ban"])
async def cmd_blacklist(ctx,action:str=None,user:discord.User=None):
    if not is_owner(ctx.author.id):
        return
    if not action or not user:
        return await ctx.send(f"Usage: `{PREFIX}bl add @user` / `{PREFIX}bl rem @user`",delete_after=10)
    if action in["add","ban"]:
        db.add_bl(user.id)
        await ctx.send(f"✅ {user} has been banned",delete_after=5)
    elif action in["rem","remove","unban"]:
        db.rem_bl(user.id)
        await ctx.send(f"✅ {user} has been unbanned",delete_after=5)
@bot.command(name="allowuser",aliases=["au"])
async def cmd_allowuser(ctx,user:discord.User=None,*,models:str=None):
    if not is_owner(ctx.author.id):
        return await ctx.send("❌ Owner only!",delete_after=5)
    if not user:
        return await ctx.send(f"Usage: `{PREFIX}au @user model1,model2` / `{PREFIX}au @user reset`",delete_after=10)
    if not models:
        current=db.get_user_allowed(user.id)
        return await ctx.send(f"📋 {user.mention}: `{','.join(current)or'None'}`",delete_after=10)
    if models.lower()=="reset":
        db.rem_user_allowed(user.id)
        return await ctx.send(f"✅ Reset permissions for {user.mention}",delete_after=5)
    valid=[m.strip()for m in models.split(",")if m.strip()in ALL_MODELS]
    if not valid:
        return await ctx.send("❌ Invalid models",delete_after=5)
    db.set_user_allowed(user.id,valid)
    await ctx.send(f"✅ {user.mention}: `{','.join(valid)}`",delete_after=5)
@bot.command(name="help",aliases=["h"])
async def cmd_help(ctx):
    embed=discord.Embed(title="📚 Command Help",color=0x5865F2)
    embed.add_field(name="💬 AI Chat",value=f"`{PREFIX}ai <text>`\n`@{bot.user.name} <text>`",inline=False)
    if is_owner(ctx.author.id):
        embed.add_field(name="🤖 Models",value=f"`{PREFIX}m1` Stable\n`{PREFIX}m2` Experimental\n`{PREFIX}m3` OpenRouter\n`{PREFIX}m4` Pollinations",inline=True)
        embed.add_field(name="🎨 Image",value=f"`{PREFIX}img <prompt>`\n`{PREFIX}im` Select model",inline=True)
        embed.add_field(name="⚙️ Admin",value=f"`{PREFIX}sd` Set default\n`{PREFIX}sh` Shield panel\n`{PREFIX}sm` Shield manage\n`{PREFIX}testai` Test\n`{PREFIX}bl` Blacklist",inline=True)
    embed.add_field(name="🔧 Utility",value=f"`{PREFIX}dump <url>`\n`{PREFIX}clear`\n`{PREFIX}ping`\n`{PREFIX}status`",inline=False)
    await ctx.send(embed=embed)
if __name__=="__main__":
    keep_alive()
    print("="*50)
    print("🚀 Bot Starting...")
    print(f"👑 Owners: {OWNER_IDS}")
    print(f"🌍 Default: {db.get_setting('public_default')or'groq'}")
    print(f"🛡️ Shield: {'✅'if SHIELD_URL else'❌'}")
    print("-"*50)
    for name,key in[("Groq",KEY_GROQ),("Cerebras",KEY_CEREBRAS),("Cloudflare",CF_API_TOKEN),("SambaNova",KEY_SAMBANOVA),("Cohere",KEY_COHERE),("Mistral",KEY_MISTRAL),("Moonshot",KEY_MOONSHOT),("HuggingFace",KEY_HUGGINGFACE),("Together",KEY_TOGETHER),("Replicate",KEY_REPLICATE),("OpenRouter",KEY_OPENROUTER),("Tavily",KEY_TAVILY),("Pollinations",KEY_POLLINATIONS)]:
        print(f"   {'✅'if key else'❌'} {name}")
    print("="*50)
    bot.run(DISCORD_TOKEN,log_handler=None)
