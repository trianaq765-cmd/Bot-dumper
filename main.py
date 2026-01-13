import discord,os,io,re,time,json,logging,sqlite3,random,threading,hashlib,asyncio
from collections import defaultdict
from dataclasses import dataclass
from discord.ext import commands
from discord import ui
from urllib.parse import quote
try:
 from web_panel import start_web_panel,get_key as wp_get_key,config as wp_config
 HAS_WEB_PANEL=True
except:start_web_panel=None;wp_get_key=None;wp_config=None;HAS_WEB_PANEL=False
try:from keep_alive import keep_alive
except:keep_alive=lambda:None
logging.basicConfig(level=logging.INFO,format='%(asctime)s|%(levelname)s|%(message)s')
logger=logging.getLogger(__name__)
DISCORD_TOKEN=os.getenv("DISCORD_TOKEN")
KEY_GROQ=os.getenv("GROQ_API_KEY","")
KEY_OPENROUTER=os.getenv("OPENROUTER_API_KEY","")
KEY_CEREBRAS=os.getenv("CEREBRAS_API_KEY","")
KEY_SAMBANOVA=os.getenv("SAMBANOVA_API_KEY","")
KEY_COHERE=os.getenv("COHERE_API_KEY","")
CF_ACCOUNT_ID=os.getenv("CLOUDFLARE_ACCOUNT_ID","")
CF_API_TOKEN=os.getenv("CLOUDFLARE_API_TOKEN","")
KEY_TOGETHER=os.getenv("TOGETHER_API_KEY","")
KEY_POLLINATIONS=os.getenv("POLLINATIONS_API_KEY","")
KEY_TAVILY=os.getenv("TAVILY_API_KEY","")
KEY_MISTRAL=os.getenv("MISTRAL_API_KEY","")
KEY_REPLICATE=os.getenv("REPLICATE_API_TOKEN","")
KEY_HUGGINGFACE=os.getenv("HUGGINGFACE_API_KEY","")
KEY_MOONSHOT=os.getenv("MOONSHOT_API_KEY","")
SHIELD_URL=os.getenv("SHIELD_URL","").rstrip("/")
SHIELD_ADMIN_KEY=os.getenv("SHIELD_ADMIN_KEY","")
CONFIG_PANEL_URL=os.getenv("CONFIG_PANEL_URL","").rstrip("/")
CONFIG_BOT_SECRET=os.getenv("CONFIG_BOT_SECRET","")
OWNER_IDS=[int(x)for x in os.getenv("OWNER_IDS","0").split(",")if x.isdigit()]
PREFIX=os.getenv("BOT_PREFIX",".")
WATERMARK="ByToingDc"
if not DISCORD_TOKEN:print("DISCORD_TOKEN Missing");exit(1)
intents=discord.Intents.default();intents.message_content=True
bot=commands.Bot(command_prefix=PREFIX,intents=intents,help_command=None)
_groq=None;_requests=None;_curl=None;_cloudscraper=None
_panel_config={"keys":{},"models":{},"settings":{},"user_models":{},"last_fetch":0}
_panel_lock=threading.Lock()
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
def fetch_panel_config(force=False):
 global _panel_config
 if not CONFIG_PANEL_URL or not CONFIG_BOT_SECRET:return None
 with _panel_lock:
  now=time.time()
  if not force and now-_panel_config.get("last_fetch",0)<60:return _panel_config if _panel_config.get("last_fetch",0)>0 else None
  try:
   r=get_requests().get(f"{CONFIG_PANEL_URL}/api/bot/config",headers={"X-Bot-Secret":CONFIG_BOT_SECRET},timeout=10)
   if r.status_code==200:
    data=r.json()
    _panel_config={"keys":data.get("keys",{}),"models":data.get("models",{}),"settings":data.get("settings",{}),"user_models":data.get("user_models",{}),"last_fetch":now}
    logger.info(f"Panel synced:{len(_panel_config['keys'])} keys,{len(_panel_config['models'])} models")
    return _panel_config
  except Exception as e:logger.warning(f"Panel fetch:{e}")
 return None
def get_api_key(name):
 config=fetch_panel_config()
 if config and name in config.get("keys",{}):return config["keys"][name]
 if wp_get_key:
  k=wp_get_key(name)
  if k:return k
 mapping={"groq":KEY_GROQ,"openrouter":KEY_OPENROUTER,"cerebras":KEY_CEREBRAS,"sambanova":KEY_SAMBANOVA,"cohere":KEY_COHERE,"cloudflare_token":CF_API_TOKEN,"cloudflare_account":CF_ACCOUNT_ID,"together":KEY_TOGETHER,"tavily":KEY_TAVILY,"mistral":KEY_MISTRAL,"replicate":KEY_REPLICATE,"huggingface":KEY_HUGGINGFACE,"moonshot":KEY_MOONSHOT,"pollinations":KEY_POLLINATIONS}
 return mapping.get(name,"")or os.getenv(name.upper()+"_API_KEY","")
def get_groq():
 global _groq
 if _groq is None:
  k=get_api_key("groq")
  if k:
   try:from groq import Groq;_groq=Groq(api_key=k)
   except:pass
 return _groq
DEFAULT_MODELS={"groq":{"e":"⚡","n":"Groq","d":"Llama 3.3 70B - Ultra Fast","c":"main","p":"groq","m":"llama-3.3-70b-versatile"},"cerebras":{"e":"🧠","n":"Cerebras","d":"Llama 3.3 70B - Fast Inference","c":"main","p":"cerebras","m":"llama-3.3-70b"},"sambanova":{"e":"🦣","n":"SambaNova","d":"Llama 3.3 70B - Enterprise","c":"main","p":"sambanova","m":"Meta-Llama-3.3-70B-Instruct"},"cloudflare":{"e":"☁️","n":"Cloudflare","d":"Llama 3.3 70B - Edge AI","c":"main","p":"cloudflare","m":"@cf/meta/llama-3.3-70b-instruct-fp8-fast"},"cohere":{"e":"🔷","n":"Cohere","d":"Command R+ - Advanced RAG","c":"main","p":"cohere","m":"command-r-plus-08-2024"},"mistral":{"e":"Ⓜ️","n":"Mistral","d":"Mistral Small - Efficient","c":"main","p":"mistral","m":"mistral-small-latest"},"together":{"e":"🤝","n":"Together","d":"Llama 3.3 Turbo","c":"main","p":"together","m":"meta-llama/Llama-3.3-70B-Instruct-Turbo"},"moonshot":{"e":"🌙","n":"Moonshot","d":"Kimi 128K - Long Context","c":"main","p":"moonshot","m":"moonshot-v1-8k"},"huggingface":{"e":"🤗","n":"HuggingFace","d":"Mixtral 8x7B","c":"main","p":"huggingface","m":"mistralai/Mixtral-8x7B-Instruct-v0.1"},"replicate":{"e":"🔄","n":"Replicate","d":"Llama 405B - Largest","c":"main","p":"replicate","m":"meta/meta-llama-3.1-405b-instruct"},"tavily":{"e":"🔍","n":"Tavily","d":"Web Search AI","c":"main","p":"tavily","m":"search"},"or_llama":{"e":"🦙","n":"OR-Llama","d":"Llama 3.3 70B via OpenRouter","c":"openrouter","p":"openrouter","m":"meta-llama/llama-3.3-70b-instruct:free"},"or_gemini":{"e":"💎","n":"OR-Gemini","d":"Gemini 2.0 Flash","c":"openrouter","p":"openrouter","m":"google/gemini-2.0-flash-exp:free"},"or_qwen":{"e":"💻","n":"OR-Qwen","d":"Qwen 2.5 72B","c":"openrouter","p":"openrouter","m":"qwen/qwen-2.5-72b-instruct:free"},"or_deepseek":{"e":"🌊","n":"OR-DeepSeek","d":"DeepSeek Chat","c":"openrouter","p":"openrouter","m":"deepseek/deepseek-chat:free"},"or_mistral":{"e":"🅼","n":"OR-Mistral","d":"Mistral Nemo","c":"openrouter","p":"openrouter","m":"mistralai/mistral-nemo:free"},"pf_openai":{"e":"🆓","n":"PollFree-OpenAI","d":"OpenAI Free","c":"pollinations_free","p":"pollinations_free","m":"openai"},"pf_claude":{"e":"🆓","n":"PollFree-Claude","d":"Claude Free","c":"pollinations_free","p":"pollinations_free","m":"claude"},"pf_gemini":{"e":"🆓","n":"PollFree-Gemini","d":"Gemini Free","c":"pollinations_free","p":"pollinations_free","m":"gemini"},"pf_deepseek":{"e":"🆓","n":"PollFree-DeepSeek","d":"DeepSeek Free","c":"pollinations_free","p":"pollinations_free","m":"deepseek"},"pf_qwen":{"e":"🆓","n":"PollFree-Qwen","d":"Qwen 72B Free","c":"pollinations_free","p":"pollinations_free","m":"qwen-72b"},"pf_llama":{"e":"🆓","n":"PollFree-Llama","d":"Llama 3.3 Free","c":"pollinations_free","p":"pollinations_free","m":"llama"},"poll_free":{"e":"🌸","n":"PollFree-Auto","d":"Auto Select Free","c":"pollinations_free","p":"pollinations_free","m":"auto"},"pa_openai":{"e":"🔑","n":"PollAPI-OpenAI","d":"OpenAI API","c":"pollinations_api","p":"pollinations_api","m":"openai"},"pa_claude":{"e":"🔑","n":"PollAPI-Claude","d":"Claude API","c":"pollinations_api","p":"pollinations_api","m":"claude"},"pa_gemini":{"e":"🔑","n":"PollAPI-Gemini","d":"Gemini API","c":"pollinations_api","p":"pollinations_api","m":"gemini"},"pa_mistral":{"e":"🔑","n":"PollAPI-Mistral","d":"Mistral API","c":"pollinations_api","p":"pollinations_api","m":"mistral"},"pa_deepseek":{"e":"🔑","n":"PollAPI-DeepSeek","d":"DeepSeek API","c":"pollinations_api","p":"pollinations_api","m":"deepseek"}}
IMG_MODELS={"flux":("🎨","Flux","Standard"),"flux_pro":("⚡","Flux Pro","Pro"),"turbo":("🚀","Turbo","Fast"),"dalle":("🤖","DALL-E 3","OpenAI"),"sdxl":("🖼️","SDXL","SD")}
def get_models():
 config=fetch_panel_config()
 if config and config.get("models"):return{**DEFAULT_MODELS,**config["models"]}
 return DEFAULT_MODELS
def get_panel_setting(key,default=None):
 config=fetch_panel_config()
 if config and key in config.get("settings",{}):return config["settings"][key]
 return default
def get_user_model(uid):
 config=fetch_panel_config()
 if config and str(uid)in config.get("user_models",{}):return config["user_models"][str(uid)]
 return None
def get_default_model():return get_panel_setting("default_model","groq")
def get_model_for_user(uid):
 um=get_user_model(uid)
 if um:return um
 return get_default_model()
def get_model_info(model_id):
 models=get_models()
 if model_id in models:return models[model_id]
 return{"e":"❓","n":"Unknown","d":"","c":"unknown","p":"unknown","m":model_id}
def is_owner(uid):return uid in OWNER_IDS
class ShieldAPI:
 def __init__(self,url,key):self.url=url;self.key=key;self.timeout=30
 def _h(self):return{"x-admin-key":self.key,"Content-Type":"application/json","Accept":"application/json"}
 def _req(self,method,ep,data=None):
  if not self.url or not self.key:return{"success":False,"error":"Shield not configured"}
  try:
   url=f"{self.url}{ep}"
   if method=="GET":r=get_requests().get(url,headers=self._h(),timeout=self.timeout)
   elif method=="POST":r=get_requests().post(url,headers=self._h(),json=data or{},timeout=self.timeout)
   elif method=="DELETE":r=get_requests().delete(url,headers=self._h(),json=data,timeout=self.timeout)
   else:return{"success":False,"error":"Invalid method"}
   if r.status_code in[200,201,204]:
    try:return r.json()
    except:return{"success":True}
   return{"success":False,"error":f"HTTP {r.status_code}"}
  except Exception as e:return{"success":False,"error":str(e)[:100]}
 def health(self):
  if not self.url:return{"success":False}
  try:r=get_requests().get(f"{self.url}/api/keepalive",timeout=10);return{"success":r.status_code==200}
  except:return{"success":False}
 def stats(self):return self._req("GET","/api/admin/stats")
 def sessions(self):return self._req("GET","/api/admin/sessions")
 def logs(self):return self._req("GET","/api/admin/logs")
 def bans(self):return self._req("GET","/api/admin/bans")
 def whitelist(self):return self._req("GET","/api/admin/whitelist")
 def suspended(self):return self._req("GET","/api/admin/suspended")
 def script(self):return self._req("GET","/api/admin/script")
 def add_ban(self,t,v,reason="Via Discord"):return self._req("POST","/api/admin/bans",{t:v,"reason":reason})
 def rem_ban(self,bid):return self._req("DELETE",f"/api/admin/bans/{bid}")
 def add_wl(self,t,v):return self._req("POST","/api/admin/whitelist",{"type":t,"value":v})
 def rem_wl(self,t,v):return self._req("POST","/api/admin/whitelist/remove",{"type":t,"value":v})
 def suspend(self,t,v,reason="Via Discord"):return self._req("POST","/api/admin/suspend",{"type":t,"value":v,"reason":reason})
 def unsuspend(self,t,v):return self._req("POST","/api/admin/unsuspend",{"type":t,"value":v})
 def kill(self,sid,reason="Via Discord"):return self._req("POST","/api/admin/kill-session",{"sessionId":sid,"reason":reason})
 def clear_sessions(self):return self._req("POST","/api/admin/sessions/clear")
 def clear_logs(self):return self._req("POST","/api/admin/logs/clear")
 def clear_cache(self):return self._req("POST","/api/admin/cache/clear")
shield=ShieldAPI(SHIELD_URL,SHIELD_ADMIN_KEY)
class Database:
 def __init__(self,path="bot.db"):
  self.conn=sqlite3.connect(path,check_same_thread=False);self.lock=threading.Lock()
  self.conn.executescript('''CREATE TABLE IF NOT EXISTS user_prefs(uid INTEGER PRIMARY KEY,img_model TEXT DEFAULT "flux");
CREATE TABLE IF NOT EXISTS bot_settings(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS stats(id INTEGER PRIMARY KEY,cmd TEXT,uid INTEGER,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS blacklist(uid INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS allowed_users(uid INTEGER PRIMARY KEY,allowed_models TEXT DEFAULT "groq");
CREATE TABLE IF NOT EXISTS dump_cache(url TEXT PRIMARY KEY,content TEXT,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);''')
 def get_setting(self,k):
  with self.lock:r=self.conn.execute('SELECT value FROM bot_settings WHERE key=?',(k,)).fetchone();return r[0]if r else None
 def set_setting(self,k,v):
  with self.lock:self.conn.execute('INSERT OR REPLACE INTO bot_settings VALUES(?,?)',(k,v));self.conn.commit()
 def get_img(self,uid):
  with self.lock:r=self.conn.execute('SELECT img_model FROM user_prefs WHERE uid=?',(uid,)).fetchone();return r[0]if r else"flux"
 def set_img(self,uid,m):
  with self.lock:self.conn.execute('INSERT OR REPLACE INTO user_prefs VALUES(?,?)',(uid,m));self.conn.commit()
 def get_allowed(self,uid):
  with self.lock:r=self.conn.execute('SELECT allowed_models FROM allowed_users WHERE uid=?',(uid,)).fetchone();return r[0].split(",")if r else[]
 def set_allowed(self,uid,models):
  with self.lock:self.conn.execute('INSERT OR REPLACE INTO allowed_users VALUES(?,?)',(uid,",".join(models)));self.conn.commit()
 def rem_allowed(self,uid):
  with self.lock:self.conn.execute('DELETE FROM allowed_users WHERE uid=?',(uid,));self.conn.commit()
 def stat(self,cmd,uid):
  with self.lock:self.conn.execute('INSERT INTO stats(cmd,uid)VALUES(?,?)',(cmd,uid));self.conn.commit()
 def banned(self,uid):
  with self.lock:return self.conn.execute('SELECT 1 FROM blacklist WHERE uid=?',(uid,)).fetchone()is not None
 def ban(self,uid):
  with self.lock:self.conn.execute('INSERT OR IGNORE INTO blacklist VALUES(?)',(uid,));self.conn.commit()
 def unban(self,uid):
  with self.lock:self.conn.execute('DELETE FROM blacklist WHERE uid=?',(uid,));self.conn.commit()
 def cache_dump(self,url,c):
  with self.lock:h=hashlib.md5(url.encode()).hexdigest();self.conn.execute('INSERT OR REPLACE INTO dump_cache VALUES(?,?,CURRENT_TIMESTAMP)',(h,c[:500000]));self.conn.commit()
 def get_cache(self,url):
  with self.lock:h=hashlib.md5(url.encode()).hexdigest();r=self.conn.execute('SELECT content FROM dump_cache WHERE url=? AND ts>datetime("now","-1 hour")',(h,)).fetchone();return r[0]if r else None
 def get_stats(self):
  with self.lock:
   total=self.conn.execute('SELECT COUNT(*)FROM stats').fetchone()[0]
   today=self.conn.execute('SELECT COUNT(*)FROM stats WHERE ts>datetime("now","-1 day")').fetchone()[0]
   users=self.conn.execute('SELECT COUNT(DISTINCT uid)FROM stats').fetchone()[0]
   top=self.conn.execute('SELECT cmd,COUNT(*)as c FROM stats GROUP BY cmd ORDER BY c DESC LIMIT 5').fetchall()
   return{"total":total,"today":today,"users":users,"top":top}
db=Database()
class RateLimiter:
 def __init__(self):self.cd=defaultdict(lambda:defaultdict(float));self.lock=threading.Lock()
 def check(self,uid,cmd,cd=5):
  pcd=get_panel_setting(f"rate_limit_{cmd}")
  if pcd:
   try:cd=int(pcd)
   except:pass
  with self.lock:
   now=time.time();last=self.cd[uid][cmd]
   if now-last<cd:return False,cd-(now-last)
   self.cd[uid][cmd]=now;return True,0
rl=RateLimiter()
@dataclass
class ChatMsg:
 role:str;content:str;ts:float
class Memory:
 def __init__(self):self.conv=defaultdict(list);self.lock=threading.Lock()
 def add(self,uid,role,content):
  max_m=25;timeout=30
  pm=get_panel_setting("max_memory_messages")
  if pm:
   try:max_m=int(pm)
   except:pass
  pt=get_panel_setting("memory_timeout_minutes")
  if pt:
   try:timeout=int(pt)
   except:pass
  with self.lock:
   now=time.time();self.conv[uid]=[m for m in self.conv[uid]if now-m.ts<timeout*60]
   self.conv[uid].append(ChatMsg(role,content[:2500],now))
   if len(self.conv[uid])>max_m:self.conv[uid]=self.conv[uid][-max_m:]
 def get(self,uid):
  with self.lock:now=time.time();self.conv[uid]=[m for m in self.conv[uid]if now-m.ts<1800];return[{"role":m.role,"content":m.content}for m in self.conv[uid]]
 def clear(self,uid):
  with self.lock:self.conv[uid]=[]
mem=Memory()
class Dumper:
 def __init__(self):self.last=None
 def dump(self,url,cache=True):
  if cache:
   c=db.get_cache(url)
   if c:return{"success":True,"content":c,"method":"cache"}
  req=get_requests();curl=get_curl();cs=get_cloudscraper();methods=[]
  if curl:methods.append(("curl",lambda u:curl.get(u,impersonate="chrome120",headers={"User-Agent":"Roblox/WinInet"},timeout=25)))
  if cs:methods.append(("cloudscraper",lambda u:cs.get(u,timeout=25)))
  if req:methods.append(("requests",lambda u:req.get(u,headers={"User-Agent":"Roblox/WinInet"},timeout=25)))
  if self.last:methods.sort(key=lambda x:x[0]!=self.last)
  for name,func in methods:
   try:
    r=func(url)
    if r.status_code==200 and len(r.text)>10:self.last=name;db.cache_dump(url,r.text)if cache else None;return{"success":True,"content":r.text,"method":name}
   except:pass
  return{"success":False,"error":"All methods failed"}
dumper=Dumper()
def get_system_prompt():
 p=get_panel_setting("system_prompt")
 return p if p else"You are a helpful AI assistant. Default language: Bahasa Indonesia."
def call_groq(msgs):
 c=get_groq()
 if not c:return None
 try:
  m=get_models().get("groq",{}).get("m","llama-3.3-70b-versatile")
  r=c.chat.completions.create(messages=msgs,model=m,temperature=0.7,max_tokens=4096);return r.choices[0].message.content
 except Exception as e:logger.error(f"Groq:{e}");return None
def call_cerebras(msgs):
 k=get_api_key("cerebras")
 if not k:return None
 try:
  m=get_models().get("cerebras",{}).get("m","llama-3.3-70b")
  r=get_requests().post("https://api.cerebras.ai/v1/chat/completions",headers={"Authorization":f"Bearer {k}","Content-Type":"application/json"},json={"model":m,"messages":msgs,"max_tokens":4096},timeout=30)
  return r.json()["choices"][0]["message"]["content"]if r.status_code==200 else None
 except Exception as e:logger.error(f"Cerebras:{e}");return None
def call_sambanova(msgs):
 k=get_api_key("sambanova")
 if not k:return None
 try:
  m=get_models().get("sambanova",{}).get("m","Meta-Llama-3.3-70B-Instruct")
  r=get_requests().post("https://api.sambanova.ai/v1/chat/completions",headers={"Authorization":f"Bearer {k}","Content-Type":"application/json"},json={"model":m,"messages":msgs,"max_tokens":4096},timeout=45)
  return r.json()["choices"][0]["message"]["content"]if r.status_code==200 else None
 except Exception as e:logger.error(f"SambaNova:{e}");return None
def call_cloudflare(msgs):
 acc=get_api_key("cloudflare_account");tok=get_api_key("cloudflare_token")
 if not acc or not tok:return None
 try:
  m=get_models().get("cloudflare",{}).get("m","@cf/meta/llama-3.3-70b-instruct-fp8-fast")
  r=get_requests().post(f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{m}",headers={"Authorization":f"Bearer {tok}","Content-Type":"application/json"},json={"messages":msgs,"max_tokens":4096},timeout=45)
  if r.status_code==200:d=r.json();return d["result"]["response"].strip()if d.get("success")else None
 except Exception as e:logger.error(f"CF:{e}")
 return None
def call_cohere(msgs):
 k=get_api_key("cohere")
 if not k:return None
 try:
  sys_p="";user_m="Hi"
  for msg in msgs:
   if msg["role"]=="system":sys_p=msg["content"]
  if msgs:user_m=msgs[-1]["content"]
  m=get_models().get("cohere",{}).get("m","command-r-plus-08-2024")
  payload={"model":m,"message":user_m}
  if sys_p:payload["preamble"]=sys_p
  r=get_requests().post("https://api.cohere.com/v1/chat",headers={"Authorization":f"Bearer {k}","Content-Type":"application/json"},json=payload,timeout=45)
  return r.json().get("text")if r.status_code==200 else None
 except Exception as e:logger.error(f"Cohere:{e}");return None
def call_mistral(msgs):
 k=get_api_key("mistral")
 if not k:return None
 try:
  m=get_models().get("mistral",{}).get("m","mistral-small-latest")
  r=get_requests().post("https://api.mistral.ai/v1/chat/completions",headers={"Authorization":f"Bearer {k}","Content-Type":"application/json"},json={"model":m,"messages":msgs,"max_tokens":4096},timeout=45)
  return r.json()["choices"][0]["message"]["content"]if r.status_code==200 else None
 except Exception as e:logger.error(f"Mistral:{e}");return None
def call_together(msgs):
 k=get_api_key("together")
 if not k:return None
 try:
  m=get_models().get("together",{}).get("m","meta-llama/Llama-3.3-70B-Instruct-Turbo")
  r=get_requests().post("https://api.together.xyz/v1/chat/completions",headers={"Authorization":f"Bearer {k}","Content-Type":"application/json"},json={"model":m,"messages":msgs,"max_tokens":4096},timeout=45)
  return r.json()["choices"][0]["message"]["content"]if r.status_code==200 else None
 except Exception as e:logger.error(f"Together:{e}");return None
def call_moonshot(msgs):
 k=get_api_key("moonshot")
 if not k:return None
 try:
  m=get_models().get("moonshot",{}).get("m","moonshot-v1-8k")
  r=get_requests().post("https://api.moonshot.cn/v1/chat/completions",headers={"Authorization":f"Bearer {k}","Content-Type":"application/json"},json={"model":m,"messages":msgs,"max_tokens":4096},timeout=60)
  return r.json()["choices"][0]["message"]["content"]if r.status_code==200 else None
 except Exception as e:logger.error(f"Moonshot:{e}");return None
def call_huggingface(msgs):
 k=get_api_key("huggingface")
 if not k:return None
 try:
  prompt="\n".join([f"{x['role']}:{x['content']}"for x in msgs[-5:]])
  m=get_models().get("huggingface",{}).get("m","mistralai/Mixtral-8x7B-Instruct-v0.1")
  r=get_requests().post(f"https://api-inference.huggingface.co/models/{m}",headers={"Authorization":f"Bearer {k}"},json={"inputs":prompt,"parameters":{"max_new_tokens":1000,"return_full_text":False}},timeout=60)
  if r.status_code==200:d=r.json();return d[0].get("generated_text","").strip()if isinstance(d,list)and d else None
 except Exception as e:logger.error(f"HF:{e}")
 return None
def call_replicate(msgs):
 k=get_api_key("replicate")
 if not k:return None
 try:
  prompt="\n".join([f"{x['role']}:{x['content']}"for x in msgs[-5:]])
  m=get_models().get("replicate",{}).get("m","meta/meta-llama-3.1-405b-instruct")
  r=get_requests().post(f"https://api.replicate.com/v1/models/{m}/predictions",headers={"Authorization":f"Bearer {k}","Content-Type":"application/json"},json={"input":{"prompt":prompt,"max_tokens":2000}},timeout=15)
  if r.status_code in[200,201]:
   pred=r.json();url=f"https://api.replicate.com/v1/predictions/{pred.get('id')}"
   for _ in range(30):
    time.sleep(2);ch=get_requests().get(url,headers={"Authorization":f"Bearer {k}"},timeout=10)
    if ch.status_code==200:
     d=ch.json()
     if d.get("status")=="succeeded":return"".join(d.get("output",[]))
     if d.get("status")in["failed","canceled"]:return None
 except Exception as e:logger.error(f"Replicate:{e}")
 return None
def call_tavily(msgs):
 k=get_api_key("tavily")
 if not k:return None
 try:
  q=msgs[-1]["content"]if msgs else""
  r=get_requests().post("https://api.tavily.com/search",json={"api_key":k,"query":q,"search_depth":"advanced","max_results":5},timeout=20)
  if r.status_code==200:
   d=r.json();results=d.get("results",[])[:3]
   ctx="\n".join([f"• {x.get('title','')}: {x.get('content','')[:100]}"for x in results])
   ans=d.get("answer","")
   return f"🔍 **Answer:**\n{ans}\n\n**Sources:**\n{ctx}"if ans else f"🔍 **Results:**\n{ctx}"if ctx else None
 except Exception as e:logger.error(f"Tavily:{e}")
 return None
def call_openrouter(msgs,model_key):
 k=get_api_key("openrouter")
 if not k:return None
 try:
  mid=get_models().get(model_key,{}).get("m","meta-llama/llama-3.3-70b-instruct:free")
  r=get_requests().post("https://openrouter.ai/api/v1/chat/completions",headers={"Authorization":f"Bearer {k}","Content-Type":"application/json","HTTP-Referer":"https://github.com"},json={"model":mid,"messages":msgs,"max_tokens":4096},timeout=60)
  if r.status_code==200:d=r.json();return d["choices"][0]["message"]["content"]if"choices"in d else None
 except Exception as e:logger.error(f"OR:{e}")
 return None
def call_pollinations_free(msgs,model_key):
 try:
  mid=get_models().get(model_key,{}).get("m","openai")
  prompt=msgs[-1]["content"]if msgs else""
  if mid=="auto":r=get_requests().get(f"https://text.pollinations.ai/{quote(prompt[:3000])}",timeout=60)
  else:r=get_requests().post("https://text.pollinations.ai/",headers={"Content-Type":"application/json"},json={"messages":msgs,"model":mid,"temperature":0.7},timeout=60)
  return r.text.strip()if r.status_code==200 and r.text.strip()else None
 except Exception as e:logger.error(f"PollFree:{e}");return None
def call_pollinations_api(msgs,model_key):
 k=get_api_key("pollinations")
 if not k:return call_pollinations_free(msgs,model_key)
 try:
  mid=get_models().get(model_key,{}).get("m","openai")
  r=get_requests().post("https://text.pollinations.ai/",headers={"Content-Type":"application/json","Authorization":f"Bearer {k}"},json={"messages":msgs,"model":mid,"temperature":0.7},timeout=60)
  return r.text.strip()if r.status_code==200 and r.text.strip()else None
 except Exception as e:logger.error(f"PollAPI:{e}");return None
def call_ai(model,msgs):
 models=get_models();m=models.get(model,{});p=m.get("p","groq")
 result=None
 if p=="groq":result=call_groq(msgs)
 elif p=="cerebras":result=call_cerebras(msgs)
 elif p=="sambanova":result=call_sambanova(msgs)
 elif p=="cloudflare":result=call_cloudflare(msgs)
 elif p=="cohere":result=call_cohere(msgs)
 elif p=="mistral":result=call_mistral(msgs)
 elif p=="together":result=call_together(msgs)
 elif p=="moonshot":result=call_moonshot(msgs)
 elif p=="huggingface":result=call_huggingface(msgs)
 elif p=="replicate":result=call_replicate(msgs)
 elif p=="openrouter":result=call_openrouter(msgs,model)
 elif p=="pollinations_free":result=call_pollinations_free(msgs,model)
 elif p=="pollinations_api":result=call_pollinations_api(msgs,model)
 elif p=="tavily":result=call_tavily(msgs)
 return result,model
FALLBACK=[("groq",call_groq),("cerebras",call_cerebras),("sambanova",call_sambanova),("poll_free",lambda m:call_pollinations_free(m,"poll_free"))]
def ask_ai(prompt,uid=None):
 sel=get_model_for_user(uid)if uid else get_default_model()
 msgs=[{"role":"system","content":get_system_prompt()}]
 if uid:
  h=mem.get(uid)
  if h:msgs.extend(h[-10:])
 msgs.append({"role":"user","content":prompt})
 result,used=call_ai(sel,msgs)
 if not result:
  for name,func in FALLBACK:
   if name==sel:continue
   try:result=func(msgs)
   except:continue
   if result:used=name;break
 if not result:return"Maaf, semua AI sedang tidak tersedia.","unknown"
 if uid:mem.add(uid,"user",prompt[:1500]);mem.add(uid,"assistant",result[:1500])
 return result,used
async def gen_image(prompt,model="flux"):
 try:
  mid={"flux":"flux","flux_pro":"flux-pro","turbo":"turbo","dalle":"dall-e-3","sdxl":"sdxl"}.get(model,"flux")
  url=f"https://image.pollinations.ai/prompt/{quote(prompt)}?model={mid}&nologo=true&width=1024&height=1024&seed={random.randint(1,99999)}"
  r=get_requests().get(url,timeout=120)
  return(r.content,None)if r.status_code==200 and len(r.content)>1000 else(None,f"HTTP {r.status_code}")
 except Exception as e:return None,str(e)[:50]
def split_msg(txt,lim=1900):
 if not txt:return[""]
 chunks=[]
 while len(txt)>lim:
  sp=txt.rfind('\n',0,lim)
  if sp==-1:sp=lim
  chunks.append(txt[:sp]);txt=txt[sp:].lstrip()
 if txt:chunks.append(txt)
 return chunks
async def send_ai_response(ch,content,model_id,ref_msg=None):
 info=get_model_info(model_id)
 chunks=split_msg(content)
 footer=f"\n\n-# {info['e']} *{WATERMARK}*"
 for i,c in enumerate(chunks):
  if i==len(chunks)-1:
   await ch.send(f"{c}{footer}",reference=ref_msg,mention_author=False)
  else:
   await ch.send(c,reference=ref_msg if i==0 else None,mention_author=False)
class ShieldInfoSelect(ui.Select):
 def __init__(self):
  opts=[discord.SelectOption(label="Statistics",value="stats",emoji="📊"),discord.SelectOption(label="Sessions",value="sessions",emoji="🔄"),discord.SelectOption(label="Logs",value="logs",emoji="📋"),discord.SelectOption(label="Bans",value="bans",emoji="🚫"),discord.SelectOption(label="Whitelist",value="wl",emoji="✅"),discord.SelectOption(label="Suspended",value="sus",emoji="⏸️"),discord.SelectOption(label="Health",value="health",emoji="💚"),discord.SelectOption(label="Bot Stats",value="botstats",emoji="📈"),discord.SelectOption(label="Script",value="script",emoji="📜")]
  super().__init__(placeholder="View Data...",options=opts)
 async def callback(self,i:discord.Interaction):
  if not is_owner(i.user.id):return await i.response.send_message("❌ Owner only!",ephemeral=True)
  await i.response.defer(ephemeral=True);a=self.values[0];embed=discord.Embed(color=0x3498DB)
  try:
   if a=="stats":
    d=shield.stats();embed.title="📊 Statistics"
    if d.get("success")is False:embed.description=f"❌ {d.get('error','Failed')}"
    elif isinstance(d,dict):
     for k,v in list(d.items())[:15]:
      if k not in["success","error"]:embed.add_field(name=str(k).title(),value=f"`{str(v)[:50]}`",inline=True)
   elif a=="sessions":
    d=shield.sessions();embed.title="🔄 Sessions"
    if d.get("success")is False:embed.description=f"❌ {d.get('error','Failed')}"
    else:
     ss=d.get("sessions",d if isinstance(d,list)else[])
     if ss:
      for idx,s in enumerate(ss[:8]):embed.add_field(name=f"#{idx+1}",value=f"ID:`{str(s.get('id','?'))[:10]}`\nUser:`{str(s.get('userId','?'))[:10]}`",inline=True)
     else:embed.description="None"
   elif a=="logs":
    d=shield.logs();embed.title="📋 Logs"
    if d.get("success")is False:embed.description=f"❌ {d.get('error','Failed')}"
    else:
     ll=d.get("logs",d if isinstance(d,list)else[])
     if ll:
      txt=[]
      for l in ll[:8]:txt.append(f"`{l.get('time','?')[:16]}` {l.get('service','?')}")
      embed.description="\n".join(txt)
     else:embed.description="None"
   elif a=="bans":
    d=shield.bans();embed.title="🚫 Bans"
    if d.get("success")is False:embed.description=f"❌ {d.get('error','Failed')}"
    else:
     bb=d.get("bans",d if isinstance(d,list)else[])
     if bb:
      for idx,b in enumerate(bb[:8]):embed.add_field(name=f"#{b.get('id','?')}",value=f"`{str(b.get('value','?'))[:15]}`",inline=True)
     else:embed.description="None"
   elif a=="health":
    d=shield.health();embed.title="💚 Health"
    embed.description="✅ Online"if d.get("success")else"❌ Offline"
   elif a=="botstats":
    s=db.get_stats();embed.title="📈 Bot Stats"
    embed.add_field(name="Total",value=f"`{s['total']}`",inline=True)
    embed.add_field(name="Today",value=f"`{s['today']}`",inline=True)
   elif a=="script":
    d=shield.script()
    if d.get("script"):
     f=discord.File(io.BytesIO(d["script"].encode()),"loader.lua")
     return await i.followup.send("📜 **Script:**",file=f,ephemeral=True)
    else:embed.description="❌ Not available"
  except Exception as e:embed.description=f"Error: {str(e)[:100]}"
  embed.set_footer(text=WATERMARK)
  await i.followup.send(embed=embed,ephemeral=True)
class ShieldManageSelect(ui.Select):
 def __init__(self):
  opts=[
   discord.SelectOption(label="Ban User",value="ban",emoji="🚫",description="Ban by ID/HWID/IP"),
   discord.SelectOption(label="Unban ID",value="unban",emoji="🔓",description="Unban by Ban ID (Number)"),
   discord.SelectOption(label="Whitelist",value="wl",emoji="✅",description="Add to whitelist"),
   discord.SelectOption(label="Remove WL",value="rem_wl",emoji="➖",description="Remove from whitelist"),
   discord.SelectOption(label="Suspend",value="sus",emoji="⏸️",description="Suspend user"),
   discord.SelectOption(label="Unsuspend",value="unsus",emoji="▶️",description="Unsuspend user"),
   discord.SelectOption(label="Kill Session",value="kill",emoji="💀",description="Kill session by ID")
  ]
  super().__init__(placeholder="⚙️ Select Action...",options=opts)
 async def callback(self,i:discord.Interaction):
  if not is_owner(i.user.id):return await i.response.send_message("❌ Owner only!",ephemeral=True)
  a=self.values[0]
  if a=="unban":t="Unban User";l="Ban ID (Number)";p="Example: 5"
  elif a=="kill":t="Kill Session";l="Session ID";p="Enter Session ID"
  elif a in ["wl","rem_wl","sus","unsus"]:t="Manage User";l="Type:Value";p="userId:123 or hwid:ABC"
  else:t="Ban User";l="Value";p="userId:123 or hwid:ABC"
  class SM(ui.Modal,title=t):
   val=ui.TextInput(label=l,placeholder=p,required=True)
   reason=ui.TextInput(label="Reason",required=False,default="Via Discord")
   def __init__(s,ac):
    super().__init__();s.ac=ac
    if ac in ["unban","unsus","rem_wl","kill"]:s.remove_item(s.reason)
   async def on_submit(s,mi):
    await mi.response.defer(ephemeral=True);v=s.val.value.strip()
    r=s.reason.value.strip() if hasattr(s,"reason") else "Via Discord"
    res={"success":False,"error":"Unknown"}
    try:
     if s.ac=="ban":
      if ":" in v:t,val=v.split(":",1)
      else:t,val="userId",v
      res=shield.add_ban(t.strip(),val.strip(),r)
     elif s.ac=="unban":res=shield.rem_ban(v)
     elif s.ac in ["wl","rem_wl","sus","unsus"]:
      if ":" in v:t,val=v.split(":",1)
      else:t,val="userId",v
      t,val=t.strip(),val.strip()
      if s.ac=="wl":res=shield.add_wl(t,val)
      elif s.ac=="rem_wl":res=shield.rem_wl(t,val)
      elif s.ac=="sus":res=shield.suspend(t,val,r)
      elif s.ac=="unsus":res=shield.unsuspend(t,val)
     elif s.ac=="kill":res=shield.kill(v,r)
     if res.get("success")is not False and not res.get("error"):
      await mi.followup.send(f"✅ **Success!**\nAction: `{s.ac}`\nValue: `{v}`\n-# *{WATERMARK}*",ephemeral=True)
     else:await mi.followup.send(f"❌ **Failed**\nError: {res.get('error','Unknown')}\n-# *{WATERMARK}*",ephemeral=True)
    except Exception as e:await mi.followup.send(f"❌ **Error:** {str(e)[:100]}",ephemeral=True)
  await i.response.send_modal(SM(a))
class ShieldManageView(ui.View):
 def __init__(self):super().__init__(timeout=120);self.add_item(ShieldManageSelect())
class ImgSelect(ui.Select):
 def __init__(self):
  opts=[discord.SelectOption(label=v[1],value=k,emoji=v[0],description=v[2])for k,v in IMG_MODELS.items()]
  super().__init__(placeholder="Select Image Model...",options=opts)
 async def callback(self,i:discord.Interaction):
  if not is_owner(i.user.id):return await i.response.send_message("❌ Owner only!",ephemeral=True)
  db.set_img(i.user.id,self.values[0]);v=IMG_MODELS.get(self.values[0],("?","?",""))
  await i.response.send_message(f"✅ Image: {v[0]} **{v[1]}**",ephemeral=True)
class ImgView(ui.View):
 def __init__(self):super().__init__(timeout=120);self.add_item(ImgSelect())
@bot.event
async def on_ready():
 logger.info(f"Bot ready:{bot.user}|Servers:{len(bot.guilds)}");fetch_panel_config()
 await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening,name=f"{PREFIX}help | {WATERMARK}"))
@bot.event
async def on_command_error(ctx,err):
 if isinstance(err,commands.CommandNotFound):return
 logger.error(f"Error:{err}")
@bot.event
async def on_message(msg):
 if msg.author.bot:return
 if bot.user.mentioned_in(msg)and not msg.mention_everyone:
  content=msg.content.replace(f'<@{bot.user.id}>','').replace(f'<@!{bot.user.id}>','').strip()
  if content:
   if db.banned(msg.author.id):return
   ok,rem=rl.check(msg.author.id,"ai",5)
   if not ok:
    warn=await msg.channel.send(f"⏳ Wait {rem:.0f}s",delete_after=3)
    return
   async with msg.channel.typing():
    resp,used=ask_ai(content,msg.author.id)
    await send_ai_response(msg.channel,resp,used,msg)
    db.stat("ai",msg.author.id)
   try:await msg.delete()
   except:pass
  return
 await bot.process_commands(msg)
@bot.command(name="ai",aliases=["a","chat"])
async def cmd_ai(ctx,*,prompt:str=None):
 if db.banned(ctx.author.id):return
 if not prompt:
  await ctx.send(f"Usage:`{PREFIX}ai <question>`",delete_after=10)
  try:await ctx.message.delete()
  except:pass
  return
 ok,rem=rl.check(ctx.author.id,"ai",5)
 if not ok:
  await ctx.send(f"⏳ Wait {rem:.0f}s",delete_after=3)
  try:await ctx.message.delete()
  except:pass
  return
 ref_msg=ctx.message
 try:await ctx.message.delete();ref_msg=None
 except:pass
 async with ctx.typing():
  resp,used=ask_ai(prompt,ctx.author.id)
  await send_ai_response(ctx.channel,resp,used,ref_msg)
  db.stat("ai",ctx.author.id)
@bot.command(name="cm",aliases=["currentmodel","mymodel"])
async def cmd_cm(ctx):
 model_id=get_model_for_user(ctx.author.id);info=get_model_info(model_id)
 embed=discord.Embed(title="🤖 Your Current Model",color=0x5865F2)
 embed.add_field(name="Model",value=f"{info['e']} **{info['n']}**",inline=True)
 embed.add_field(name="Provider",value=f"`{info['p']}`",inline=True)
 embed.add_field(name="API Model",value=f"`{info['m']}`",inline=False)
 embed.set_footer(text=f"Change via Web Panel • {WATERMARK}")
 await ctx.send(embed=embed)
 try:await ctx.message.delete()
 except:pass
@bot.command(name="models",aliases=["lm","listmodels"])
async def cmd_lm(ctx):
 models=get_models()
 cats={"main":[],"openrouter":[],"pollinations_free":[],"pollinations_api":[],"custom":[]}
 for mid,m in models.items():
  c=m.get("c","main")
  if c not in cats:cats[c]=[]
  cats[c].append(f"{m['e']} `{mid}`")
 embed=discord.Embed(title="📋 Available Models",color=0x5865F2)
 for cat,items in cats.items():
  if items:
   val="\n".join(items[:6])
   if len(items)>6:val+=f"\n+{len(items)-6} more"
   embed.add_field(name=f"{cat.upper()} ({len(items)})",value=val,inline=True)
 embed.set_footer(text=f"Set via Web Panel • {WATERMARK}")
 await ctx.send(embed=embed)
 try:await ctx.message.delete()
 except:pass
@bot.command(name="imagine",aliases=["img","image"])
async def cmd_img(ctx,*,prompt:str=None):
 if not is_owner(ctx.author.id):
  await ctx.send("❌ Owner only!",delete_after=5)
  try:await ctx.message.delete()
  except:pass
  return
 if not prompt:
  await ctx.send(f"Usage:`{PREFIX}img <prompt>`",delete_after=5)
  try:await ctx.message.delete()
  except:pass
  return
 ok,rem=rl.check(ctx.author.id,"img",15)
 if not ok:
  await ctx.send(f"⏳ Wait {rem:.0f}s",delete_after=3)
  try:await ctx.message.delete()
  except:pass
  return
 try:await ctx.message.delete()
 except:pass
 model=db.get_img(ctx.author.id);info=IMG_MODELS.get(model,("🎨","Flux",""))
 st=await ctx.send(f"🎨 Generating with {info[0]} **{info[1]}**...")
 try:
  data,err=await gen_image(prompt,model)
  if data:
   f=discord.File(io.BytesIO(data),"image.png")
   embed=discord.Embed(title=f"🎨 {prompt[:80]}",color=0x5865F2)
   embed.set_image(url="attachment://image.png")
   embed.set_footer(text=f"{info[0]} {info[1]} • {WATERMARK}")
   await ctx.send(embed=embed,file=f);await st.delete();db.stat("img",ctx.author.id)
  else:await st.edit(content=f"❌ Failed:{err}")
 except Exception as e:await st.edit(content=f"❌ Error:{str(e)[:50]}")
@bot.command(name="imgmodel",aliases=["im"])
async def cmd_im(ctx):
 if not is_owner(ctx.author.id):
  await ctx.send("❌ Owner only!",delete_after=5)
  try:await ctx.message.delete()
  except:pass
  return
 curr=db.get_img(ctx.author.id);info=IMG_MODELS.get(curr,("?","?",""))
 embed=discord.Embed(title="🎨 Image Model",description=f"**Current:** {info[0]} {info[1]}",color=0x5865F2)
 embed.set_footer(text=WATERMARK)
 await ctx.send(embed=embed,view=ImgView())
 try:await ctx.message.delete()
 except:pass
@bot.command(name="dump",aliases=["dl"])
async def cmd_dump(ctx,url:str=None,*,flags:str=""):
 if db.banned(ctx.author.id):return
 if not url:
  await ctx.send(f"Usage:`{PREFIX}dump <url>`",delete_after=5)
  try:await ctx.message.delete()
  except:pass
  return
 ok,rem=rl.check(ctx.author.id,"dump",10)
 if not ok:
  await ctx.send(f"⏳ Wait {rem:.0f}s",delete_after=3)
  try:await ctx.message.delete()
  except:pass
  return
 try:await ctx.message.delete()
 except:pass
 if not url.startswith("http"):url="https://"+url
 st=await ctx.send("🔄 Dumping...")
 result=dumper.dump(url,"--nocache"not in flags)
 if result["success"]:
  content=result["content"];ext="lua"if"local "in content[:500]else"html"if"<html"in content[:200].lower()else"txt"
  f=discord.File(io.BytesIO(content.encode()),f"dump.{ext}")
  await ctx.send(f"✅ `{result['method']}`|`{len(content):,}` bytes\n-# *{WATERMARK}*",file=f);await st.delete();db.stat("dump",ctx.author.id)
 else:await st.edit(content=f"❌ {result.get('error','Failed')}")
@bot.command(name="shield",aliases=["sh"])
async def cmd_shield(ctx):
 if not is_owner(ctx.author.id):
  await ctx.send("❌ Owner only!",delete_after=5)
  try:await ctx.message.delete()
  except:pass
  return
 try:await ctx.message.delete()
 except:pass
 st=shield.health()
 embed=discord.Embed(title="🛡️ Shield Panel",color=0x2ECC71 if st.get("success")else 0xE74C3C)
 embed.add_field(name="Status",value="🟢 ONLINE"if st.get("success")else"🔴 OFFLINE",inline=True)
 embed.set_footer(text=WATERMARK)
 await ctx.send(embed=embed,view=ShieldView())
@bot.command(name="shieldm",aliases=["sm"])
async def cmd_sm(ctx):
 if not is_owner(ctx.author.id):
  await ctx.send("❌ Owner only!",delete_after=5)
  try:await ctx.message.delete()
  except:pass
  return
 try:await ctx.message.delete()
 except:pass
 embed=discord.Embed(title="⚙️ Shield Management",color=0xE74C3C)
 embed.add_field(name="Format",value="`type:value`\nEx:`hwid:ABC123`",inline=True)
 embed.set_footer(text=WATERMARK)
 await ctx.send(embed=embed,view=ShieldManageView())
@bot.command(name="sync",aliases=["resync"])
async def cmd_sync(ctx):
 if not is_owner(ctx.author.id):
  await ctx.send("❌ Owner only!",delete_after=5)
  try:await ctx.message.delete()
  except:pass
  return
 try:await ctx.message.delete()
 except:pass
 st=await ctx.send("🔄 Syncing...")
 config=fetch_panel_config(force=True)
 if config and config.get("last_fetch",0)>0:
  embed=discord.Embed(title="✅ Config Synced",color=0x2ECC71)
  embed.add_field(name="🔑 Keys",value=f"`{len(config.get('keys',{}))}`",inline=True)
  embed.add_field(name="🤖 Models",value=f"`{len(config.get('models',{}))}`",inline=True)
  embed.set_footer(text=WATERMARK)
  await st.edit(content=None,embed=embed)
 else:await st.edit(content="❌ Failed to sync")
@bot.command(name="clear",aliases=["reset"])
async def cmd_clear(ctx):
 mem.clear(ctx.author.id)
 await ctx.send(f"🧹 Memory cleared!\n-# *{WATERMARK}*",delete_after=5)
 try:await ctx.message.delete()
 except:pass
@bot.command(name="ping",aliases=["p"])
async def cmd_ping(ctx):
 model_id=get_model_for_user(ctx.author.id);info=get_model_info(model_id)
 embed=discord.Embed(title="🏓 Pong!",color=0x2ECC71)
 embed.add_field(name="Latency",value=f"`{round(bot.latency*1000)}ms`",inline=True)
 embed.add_field(name="Model",value=f"{info['e']} {info['n']}",inline=True)
 embed.set_footer(text=WATERMARK)
 await ctx.send(embed=embed)
 try:await ctx.message.delete()
 except:pass
@bot.command(name="status")
async def cmd_status(ctx):
 if not is_owner(ctx.author.id):
  await ctx.send("❌ Owner only!",delete_after=5)
  try:await ctx.message.delete()
  except:pass
  return
 try:await ctx.message.delete()
 except:pass
 config=fetch_panel_config();panel_ok=config and config.get("last_fetch",0)>0
 embed=discord.Embed(title="📊 Status",color=0x5865F2)
 embed.add_field(name="🌐 Panel",value=f"{'✅ Connected'if panel_ok else'❌ Offline'}",inline=True)
 embed.add_field(name="🛡️ Shield",value=f"{'✅ Online'if shield.health().get('success')else'❌ Offline'}",inline=True)
 embed.set_footer(text=WATERMARK)
 await ctx.send(embed=embed)
@bot.command(name="testai")
async def cmd_testai(ctx):
 if not is_owner(ctx.author.id):
  await ctx.send("❌ Owner only!",delete_after=5)
  try:await ctx.message.delete()
  except:pass
  return
 try:await ctx.message.delete()
 except:pass
 st=await ctx.send("🔄 Testing providers...")
 test=[{"role":"user","content":"Say OK"}];results=[]
 providers=[("Groq",lambda:call_groq(test),get_api_key("groq")),("Cerebras",lambda:call_cerebras(test),get_api_key("cerebras")),("SambaNova",lambda:call_sambanova(test),get_api_key("sambanova")),("OR",lambda:call_openrouter(test,"or_gemini"),get_api_key("openrouter")),("PollFree",lambda:call_pollinations_free(test,"poll_free"),True)]
 for n,f,k in providers:
  if not k:results.append(f"⚪{n}");continue
  try:r=f();results.append(f"✅{n}"if r else f"❌{n}")
  except:results.append(f"❌{n}")
 embed=discord.Embed(title="🧪 AI Test",description=" | ".join(results),color=0x5865F2)
 embed.set_footer(text=WATERMARK)
 await st.edit(content=None,embed=embed)
@bot.command(name="blacklist",aliases=["bl","ban"])
async def cmd_bl(ctx,action:str=None,user:discord.User=None):
 if not is_owner(ctx.author.id):return
 try:await ctx.message.delete()
 except:pass
 if not action or not user:return await ctx.send(f"Usage:`{PREFIX}bl add/rem @user`",delete_after=10)
 if action in["add","ban"]:db.ban(user.id);await ctx.send(f"✅ Banned {user}\n-# *{WATERMARK}*",delete_after=5)
 elif action in["rem","remove","unban"]:db.unban(user.id);await ctx.send(f"✅ Unbanned {user}\n-# *{WATERMARK}*",delete_after=5)
@bot.command(name="stats")
async def cmd_stats(ctx):
 s=db.get_stats()
 embed=discord.Embed(title="📈 Bot Statistics",color=0x5865F2)
 embed.add_field(name="Total",value=f"`{s['total']}`",inline=True)
 embed.add_field(name="Today",value=f"`{s['today']}`",inline=True)
 embed.set_footer(text=WATERMARK)
 await ctx.send(embed=embed)
 try:await ctx.message.delete()
 except:pass
@bot.command(name="help",aliases=["h"])
async def cmd_help(ctx):
 embed=discord.Embed(title="📚 Help",color=0x5865F2)
 embed.add_field(name="💬 AI",value=f"`{PREFIX}ai <text>`\n`@{bot.user.name} <text>`",inline=False)
 embed.add_field(name="🤖 Models",value=f"`{PREFIX}cm` - Current\n`{PREFIX}models` - List\n*Set via Web Panel*",inline=True)
 if is_owner(ctx.author.id):
  embed.add_field(name="🎨 Image",value=f"`{PREFIX}img <prompt>`\n`{PREFIX}im` - Select",inline=True)
  embed.add_field(name="🛡️ Shield",value=f"`{PREFIX}sh` - Panel\n`{PREFIX}sm` - Manage",inline=True)
  embed.add_field(name="⚙️ Admin",value=f"`{PREFIX}status` `{PREFIX}testai`\n`{PREFIX}sync` `{PREFIX}bl`",inline=True)
 embed.add_field(name="🔧 Utility",value=f"`{PREFIX}dump <url>`\n`{PREFIX}clear` `{PREFIX}ping` `{PREFIX}stats`",inline=True)
 embed.add_field(name="🌐 Panel",value=f"`{CONFIG_PANEL_URL[:30] if CONFIG_PANEL_URL else 'Not set'}...`",inline=True)
 embed.set_footer(text=WATERMARK)
 await ctx.send(embed=embed)
 try:await ctx.message.delete()
 except:pass
@bot.command(name="panel")
async def cmd_panel(ctx):
 try:await ctx.message.delete()
 except:pass
 if CONFIG_PANEL_URL:
  embed=discord.Embed(title="🌐 Config Panel",description=f"`{CONFIG_PANEL_URL}`",color=0x5865F2)
  embed.set_footer(text=WATERMARK)
  await ctx.send(embed=embed)
 else:await ctx.send("❌ Panel not configured",delete_after=5)
def run_flask():
 from flask import Flask,jsonify
 app=Flask(__name__)
 @app.route('/')
 def home():return f"Bot {bot.user} running! | {WATERMARK}"if bot.user else"Starting..."
 @app.route('/health')
 def health():return jsonify({"status":"ok","bot":str(bot.user)if bot.user else"starting","watermark":WATERMARK})
 port=int(os.getenv("PORT",8080));app.run(host="0.0.0.0",port=port,debug=False,use_reloader=False)
if __name__=="__main__":
 keep_alive();PORT=int(os.getenv("PORT",8080))
 if HAS_WEB_PANEL and start_web_panel:start_web_panel(host="0.0.0.0",port=PORT,admin_key=os.getenv("ADMIN_KEY","admin123"));print(f"🚀 Web Panel: http://0.0.0.0:{PORT}")
 else:threading.Thread(target=run_flask,daemon=True).start();print(f"🚀 Health: http://0.0.0.0:{PORT}")
 print("="*50);print(f"🚀 Bot Starting... | {WATERMARK}")
 print(f"👑 Owners: {OWNER_IDS}");print(f"🛡️ Shield: {'✅'if SHIELD_URL else'❌'}");print(f"🌐 Panel: {'✅'if CONFIG_PANEL_URL else'❌'}")
 print("="*50);bot.run(DISCORD_TOKEN,log_handler=None)