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
   r=s.conn.execute('SELECT value FROM bot_settings WHERE key="public_model_access"').fetchone()
   if not r:s.conn.execute('INSERT INTO bot_settings VALUES("public_model_access","groq")');s.conn.commit()
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
 def get_user_allowed(s,uid):
  with s.lock:r=s.conn.execute('SELECT allowed_models FROM allowed_users WHERE uid=?',(uid,)).fetchone();return r[0].split(",")if r else[]
 def set_user_allowed(s,uid,m):
  with s.lock:s.conn.execute('INSERT OR REPLACE INTO allowed_users VALUES(?,?)',(uid,",".join(m)));s.conn.commit()
 def rem_user_allowed(s,uid):
  with s.lock:s.conn.execute('DELETE FROM allowed_users WHERE uid=?',(uid,));s.conn.commit()
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
   s.data[uid].append(Msg(role,c[:1500],now))
   if len(s.data[uid])>15:s.data[uid]=s.data[uid][-15:]
 def get(s,uid):
  with s.lock:now=time.time();s.data[uid]=[m for m in s.data[uid]if now-m.ts<1800];return[{"role":m.role,"content":m.content}for m in s.data[uid]]
 def clear(s,uid):
  with s.lock:s.data[uid]=[]
mem=Memory()
SYSTEM_PROMPT='Kamu adalah AI Assistant yang helpful dan friendly. Jawab dalam Bahasa Indonesia kecuali diminta lain.'
# Updated 2024-2025 Model Strings
OR_MODELS={"or_llama":"meta-llama/llama-3.3-70b-instruct:free","or_gemini":"google/gemini-2.0-flash-exp:free","or_qwen":"qwen/qwen-2.5-72b-instruct:free","or_deepseek":"deepseek/deepseek-chat:free","or_mistral":"mistralai/mistral-nemo:free"}
POLL_TEXT={"p_gpt5":"openai","p_claude":"claude","p_gemini":"gemini","p_deepseek":"deepseek","p_grok":"grok","p_perplexity":"perplexity-fast"}
POLL_IMG={"flux":"flux","sdxl":"turbo","gpt_img":"gptimage","dream":"seedream"}
FREE_MODELS=["groq","cerebras","cohere","cloudflare","sambanova","together","mistral","moonshot","huggingface","replicate","tavily","poll_free","or_gemini","or_llama","or_qwen","or_deepseek","or_mistral"]
PREMIUM_MODELS=["p_gpt5","p_claude","p_gemini","p_deepseek","p_grok","p_perplexity"]
MODEL_INFO={
 "groq":("⚡","Groq","Llama 3.3 70B","free"),
 "cerebras":("🧠","Cerebras","Llama 3.3 70B","free"),
 "cohere":("🔷","Cohere","Command R+","free"),
 "cloudflare":("☁️","Cloudflare","Llama 3.3 70B","free"),
 "sambanova":("🦣","SambaNova","Llama 3.3 70B","free"),
 "together":("🤝","Together","Llama 3.3 Turbo","free"),
 "mistral":("Ⓜ️","Mistral","Mistral Large","free"),
 "moonshot":("🌙","Moonshot","Kimi 128K","free"),
 "huggingface":("🤗","HuggingFace","Mixtral 8x7B","free"),
 "replicate":("🔄","Replicate","Llama 3.1 405B","free"),
 "tavily":("🔍","Tavily","Search AI","free"),
 "poll_free":("🌸","Pollinations","Free","free"),
 "or_gemini":("🔵","OR-Gemini","Gemini 2.0","free"),
 "or_llama":("🦙","OR-Llama","Llama 3.3","free"),
 "or_qwen":("💻","OR-Qwen","Qwen 2.5 72B","free"),
 "or_deepseek":("🌊","OR-DeepSeek","DeepSeek Chat","free"),
 "or_mistral":("🅼","OR-Mistral","Mistral Nemo","free"),
 "p_gpt5":("🤖","GPT-5","OpenAI","premium"),
 "p_claude":("🎭","Claude","Anthropic","premium"),
 "p_gemini":("💎","Gemini 3","Google","premium"),
 "p_deepseek":("🐳","DeepSeek V3","Premium","premium"),
 "p_grok":("❌","Grok 4","xAI","premium"),
 "p_perplexity":("🔎","Perplexity","Search","premium")
}
IMG_INFO={"flux":("🎨","Flux","Fast HQ"),"sdxl":("⚡","SDXL","Turbo"),"gpt_img":("🤖","GPT","OpenAI"),"dream":("🌌","Seedream","Artistic")}
def is_owner(uid):return uid in OWNER_IDS
def can_use_model(uid,m):
 if is_owner(uid):return True
 if m in PREMIUM_MODELS:return False
 pub=db.get_setting("public_model_access")or"groq"
 if pub=="all":return m in FREE_MODELS
 allowed=set(pub.split(",")+db.get_user_allowed(uid))
 return m in allowed
def get_available_models(uid):
 if is_owner(uid):return list(MODEL_INFO.keys())
 pub=db.get_setting("public_model_access")or"groq"
 if pub=="all":return FREE_MODELS.copy()
 return list(set(pub.split(",")+db.get_user_allowed(uid)))
def call_groq(msgs):
 g=get_groq()
 if not g:return None
 try:r=g.chat.completions.create(messages=msgs,model="llama-3.3-70b-versatile",temperature=0.7,max_tokens=2000);return r.choices[0].message.content
 except Exception as e:logger.error(f"Groq:{e}");return None
def call_cerebras(msgs):
 if not KEY_CEREBRAS:return None
 try:r=get_requests().post("https://api.cerebras.ai/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_CEREBRAS}","Content-Type":"application/json"},json={"model":"llama-3.3-70b","messages":msgs,"max_tokens":2000},timeout=30);return r.json()["choices"][0]["message"]["content"]if r.status_code==200 else None
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
  if r.status_code==200:
   data=r.json()
   return data.get("text")or data.get("message")
  logger.error(f"Cohere:{r.status_code}-{r.text[:100]}")
  return None
 except Exception as e:logger.error(f"Cohere:{e}");return None
def call_cloudflare(msgs):
 if not CF_ACCOUNT_ID or not CF_API_TOKEN:return None
 try:
  r=get_requests().post(f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/@cf/meta/llama-3.3-70b-instruct-fp8-fast",headers={"Authorization":f"Bearer {CF_API_TOKEN}","Content-Type":"application/json"},json={"messages":msgs,"max_tokens":2000},timeout=45)
  if r.status_code==200:d=r.json();return d["result"]["response"].strip()if d.get("success")else None
  return None
 except Exception as e:logger.error(f"CF:{e}");return None
def call_sambanova(msgs):
 if not KEY_SAMBANOVA:return None
 try:r=get_requests().post("https://api.sambanova.ai/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_SAMBANOVA}","Content-Type":"application/json"},json={"model":"Meta-Llama-3.3-70B-Instruct","messages":msgs,"max_tokens":2000},timeout=45);return r.json()["choices"][0]["message"]["content"]if r.status_code==200 else None
 except Exception as e:logger.error(f"SN:{e}");return None
def call_together(msgs):
 if not KEY_TOGETHER:return None
 try:r=get_requests().post("https://api.together.xyz/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_TOGETHER}","Content-Type":"application/json"},json={"model":"meta-llama/Llama-3.3-70B-Instruct-Turbo","messages":msgs,"max_tokens":2000},timeout=45);return r.json()["choices"][0]["message"]["content"]if r.status_code==200 else None
 except Exception as e:logger.error(f"Together:{e}");return None
def call_mistral(msgs):
 if not KEY_MISTRAL:return None
 try:
  r=get_requests().post("https://api.mistral.ai/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_MISTRAL}","Content-Type":"application/json","Accept":"application/json"},json={"model":"mistral-small-latest","messages":msgs,"max_tokens":2000},timeout=45)
  if r.status_code==200:return r.json()["choices"][0]["message"]["content"]
  logger.error(f"Mistral:{r.status_code}-{r.text[:100]}")
  return None
 except Exception as e:logger.error(f"Mistral:{e}");return None
def call_moonshot(msgs):
 if not KEY_MOONSHOT:return None
 try:
  r=get_requests().post("https://api.moonshot.cn/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_MOONSHOT}","Content-Type":"application/json"},json={"model":"moonshot-v1-8k","messages":msgs,"max_tokens":2000},timeout=60)
  if r.status_code==200:return r.json()["choices"][0]["message"]["content"]
  logger.error(f"Moonshot:{r.status_code}-{r.text[:100]}")
  return None
 except Exception as e:logger.error(f"Moonshot:{e}");return None
def call_huggingface(msgs):
 if not KEY_HUGGINGFACE:return None
 try:
  prompt="\n".join([f"{m['role']}:{m['content']}"for m in msgs[-3:]])
  r=get_requests().post("https://api-inference.huggingface.co/models/mistralai/Mixtral-8x7B-Instruct-v0.1",headers={"Authorization":f"Bearer {KEY_HUGGINGFACE}","Content-Type":"application/json"},json={"inputs":prompt,"parameters":{"max_new_tokens":500,"return_full_text":False}},timeout=60)
  if r.status_code==200:
   d=r.json()
   if isinstance(d,list)and d:return d[0].get("generated_text","").strip()
   return None
  logger.error(f"HF:{r.status_code}-{r.text[:100]}")
  return None
 except Exception as e:logger.error(f"HF:{e}");return None
def call_replicate(msgs):
 if not KEY_REPLICATE:return None
 try:
  prompt="\n".join([f"{m['role']}:{m['content']}"for m in msgs[-3:]])
  r=get_requests().post("https://api.replicate.com/v1/models/meta/meta-llama-3.1-405b-instruct/predictions",headers={"Authorization":f"Bearer {KEY_REPLICATE}","Content-Type":"application/json"},json={"input":{"prompt":prompt,"max_tokens":1000}},timeout=15)
  if r.status_code in[200,201]:
   pred=r.json()
   pred_url=f"https://api.replicate.com/v1/predictions/{pred.get('id')}"
   for _ in range(20):
    time.sleep(3)
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
  sr=get_requests().post("https://api.tavily.com/search",json={"api_key":KEY_TAVILY,"query":query,"search_depth":"basic","max_results":5},timeout=15)
  if sr.status_code==200:
   sd=sr.json()
   results=sd.get("results",[])[:3]
   context="\n".join([f"• {r.get('title','')}: {r.get('content','')[:150]}"for r in results])
   answer=sd.get("answer","")
   if answer:return f"🔍 {answer}\n\n**Sources:**\n{context}"
   return f"🔍 **Results:**\n{context}"if context else None
  return None
 except Exception as e:logger.error(f"Tavily:{e}");return None
def call_openrouter(msgs,mk):
 if not KEY_OPENROUTER:return None
 try:
  mid=OR_MODELS.get(mk,OR_MODELS["or_llama"])
  r=get_requests().post("https://openrouter.ai/api/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_OPENROUTER}","Content-Type":"application/json","HTTP-Referer":"https://github.com","X-Title":"DiscordBot"},json={"model":mid,"messages":msgs,"max_tokens":2000},timeout=60)
  if r.status_code==200:d=r.json();return d["choices"][0]["message"]["content"]if"choices"in d else None
  logger.error(f"OR:{r.status_code}-{r.text[:100]}")
  return None
 except Exception as e:logger.error(f"OR:{e}");return None
def call_poll_free(prompt):
 try:r=get_requests().get(f"https://text.pollinations.ai/{quote(prompt)}",timeout=45);return r.text.strip()if r.status_code==200 and r.text.strip()else None
 except Exception as e:logger.error(f"Poll:{e}");return None
def call_poll_api(msgs,mk):
 if not KEY_POLLINATIONS:return None
 try:
  mid=POLL_TEXT.get(mk,mk)
  r=get_requests().post("https://text.pollinations.ai/",headers={"Authorization":f"Bearer {KEY_POLLINATIONS}","Content-Type":"application/json"},json={"messages":msgs,"model":mid},timeout=60)
  return r.text.strip()if r.status_code==200 else None
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
 elif model=="poll_free":return call_poll_free(prompt),"Poll(Free)"
 elif model.startswith("or_"):return call_openrouter(msgs,model),f"OR({model[3:]})"
 elif model.startswith("p_"):return call_poll_api(msgs,model),f"Poll({model[2:]})"
 return None,"none"
def ask_ai(prompt,uid=None,model=None):
 user_model=db.get_model(uid)if uid else"groq"
 sel=model if model else user_model
 if not can_use_model(uid,sel):sel="groq";db.set_model(uid,"groq")
 msgs=[{"role":"system","content":SYSTEM_PROMPT}]
 if uid:
  h=mem.get(uid)
  if h:msgs.extend(h[-6:])
 msgs.append({"role":"user","content":prompt})
 result,used=call_ai(sel,msgs,prompt)
 if not result:
  fallback=[(call_groq,msgs,"Groq",KEY_GROQ),(call_cerebras,msgs,"Cerebras",KEY_CEREBRAS),(call_cloudflare,msgs,"CF",CF_API_TOKEN),(call_sambanova,msgs,"SN",KEY_SAMBANOVA),(lambda m:call_openrouter(m,"or_gemini"),msgs,"OR",KEY_OPENROUTER),(lambda p:call_poll_free(prompt),None,"Poll",True)]
  for fn,arg,name,key in fallback:
   if not key:continue
   try:
    r=fn(arg)if arg else fn(prompt)
    if r:result=r;used=f"{name}(fb)";break
   except:continue
 if not result:return"❌ Semua AI sibuk.","none"
 if uid:mem.add(uid,"user",prompt[:500]);mem.add(uid,"assistant",result[:500])
 return result,used
async def gen_image(prompt,model="flux"):
 if not KEY_POLLINATIONS:return None,"No API Key"
 try:
  mid=POLL_IMG.get(model,"flux")
  url=f"https://image.pollinations.ai/prompt/{quote(prompt)}?model={mid}&nologo=true&width=1024&height=1024"
  r=get_requests().get(url,headers={"Authorization":f"Bearer {KEY_POLLINATIONS}"},timeout=90)
  return(r.content,None)if r.status_code==200 else(None,f"HTTP {r.status_code}")
 except Exception as e:return None,str(e)
# Fixed: Split models into pages for Owner (max 25 per Select)
class ModelSelectPage(ui.Select):
 def __init__(s,uid,models,page=1):
  s.uid=uid
  opts=[discord.SelectOption(label=MODEL_INFO[m][1],value=m,emoji=MODEL_INFO[m][0],description=f"{MODEL_INFO[m][2][:30]}[{MODEL_INFO[m][3]}]")for m in models if m in MODEL_INFO]
  if not opts:opts=[discord.SelectOption(label="Groq",value="groq",emoji="⚡")]
  super().__init__(placeholder=f"🤖 Model (Page {page})...",options=opts[:25])
 async def callback(s,i:discord.Interaction):
  if i.user.id!=s.uid:return await i.response.send_message("❌ Bukan menu kamu!",ephemeral=True)
  v=s.values[0]
  if not can_use_model(i.user.id,v):return await i.response.send_message(f"❌ No access to `{v}`",ephemeral=True)
  db.set_model(i.user.id,v);info=MODEL_INFO.get(v,("","?","",""))
  await i.response.send_message(f"✅ Model: {info[0]} **{info[1]}**",ephemeral=True)
class ModelView(ui.View):
 def __init__(s,uid):
  super().__init__(timeout=120)
  avail=get_available_models(uid)
  if len(avail)<=25:
   s.add_item(ModelSelectPage(uid,avail,1))
  else:
   s.add_item(ModelSelectPage(uid,avail[:25],1))
   if len(avail)>25:s.add_item(ModelSelectPage(uid,avail[25:50],2))
class ImgSelect(ui.Select):
 def __init__(s,uid):
  s.uid=uid
  opts=[discord.SelectOption(label=v[1],value=k,emoji=v[0],description=v[2])for k,v in IMG_INFO.items()]
  super().__init__(placeholder="🎨 Image Model...",options=opts)
 async def callback(s,i:discord.Interaction):
  if i.user.id!=s.uid:return await i.response.send_message("❌ Bukan menu kamu!",ephemeral=True)
  v=s.values[0];db.set_img_model(i.user.id,v);info=IMG_INFO.get(v,("","?",""))
  await i.response.send_message(f"✅ {info[0]} **{info[1]}**",ephemeral=True)
class ImgView(ui.View):
 def __init__(s,uid):super().__init__(timeout=120);s.add_item(ImgSelect(uid))
class ShieldSelect(ui.Select):
 def __init__(s):
  opts=[discord.SelectOption(label="Stats",value="stats",emoji="📊"),discord.SelectOption(label="Sessions",value="sessions",emoji="🔄"),discord.SelectOption(label="Logs",value="logs",emoji="📋"),discord.SelectOption(label="Bans",value="bans",emoji="🚫"),discord.SelectOption(label="Script",value="script",emoji="📜"),discord.SelectOption(label="KeepAlive",value="ka",emoji="⚡"),discord.SelectOption(label="Clear Sessions",value="cs",emoji="🧹"),discord.SelectOption(label="Clear Logs",value="cl",emoji="🗑️")]
  super().__init__(placeholder="🛡️ Shield...",options=opts)
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
  elif v=="cs":r=shield.clear_sessions();await i.followup.send(f"{'✅'if r.get('success')else'❌'}",ephemeral=True)
  elif v=="cl":r=shield.clear_logs();await i.followup.send(f"{'✅'if r.get('success')else'❌'}",ephemeral=True)
class ShieldView(ui.View):
 def __init__(s):super().__init__(timeout=180);s.add_item(ShieldSelect())
class ShieldMgmtSelect(ui.Select):
 def __init__(s):
  opts=[discord.SelectOption(label="Ban User",value="ban_u",emoji="🚫"),discord.SelectOption(label="Ban HWID",value="ban_h",emoji="🔑"),discord.SelectOption(label="Ban IP",value="ban_i",emoji="🌐"),discord.SelectOption(label="Unban",value="unban",emoji="✅"),discord.SelectOption(label="Add WL",value="wl_a",emoji="➕"),discord.SelectOption(label="Remove WL",value="wl_r",emoji="➖"),discord.SelectOption(label="Suspend",value="sus",emoji="⏸️"),discord.SelectOption(label="Unsuspend",value="unsus",emoji="▶️"),discord.SelectOption(label="Kill Session",value="kill",emoji="💀")]
  super().__init__(placeholder="⚙️ Manage...",options=opts)
 async def callback(s,i:discord.Interaction):
  if not is_owner(i.user.id):return await i.response.send_message("❌ Owner only",ephemeral=True)
  v=s.values[0]
  class Modal(ui.Modal,title=f"Shield: {v}"):
   inp=ui.TextInput(label="Value",required=True)
   rsn=ui.TextInput(label="Reason",required=False,default="Discord")
   def __init__(m,act):super().__init__();m.act=act
   async def on_submit(m,it:discord.Interaction):
    val=m.inp.value;reason=m.rsn.value or"Discord"
    if m.act=="ban_u":r=shield.add_ban(pid=val,reason=reason)
    elif m.act=="ban_h":r=shield.add_ban(hwid=val,reason=reason)
    elif m.act=="ban_i":r=shield.add_ban(ip=val,reason=reason)
    elif m.act=="unban":r=shield.remove_ban(val)
    elif m.act=="wl_a":p=val.split(":",1);r=shield.add_wl(p[0]if len(p)>1 else"userId",p[-1])
    elif m.act=="wl_r":p=val.split(":",1);r=shield.remove_wl(p[0]if len(p)>1 else"userId",p[-1])
    elif m.act=="sus":p=val.split(":",1);r=shield.suspend(p[0]if len(p)>1 else"userId",p[-1],reason)
    elif m.act=="unsus":p=val.split(":",1);r=shield.unsuspend(p[0]if len(p)>1 else"userId",p[-1])
    elif m.act=="kill":r=shield.kill(val,reason)
    else:r={"success":False}
    await it.response.send_message(f"{'✅'if r.get('success')else'❌ '+r.get('error','')}",ephemeral=True)
  await i.response.send_modal(Modal(v))
class ShieldMgmtView(ui.View):
 def __init__(s):super().__init__(timeout=180);s.add_item(ShieldMgmtSelect())
class Dumper:
 def __init__(s):s.last=None
 def dump(s,url,cache=True):
  if cache:c=db.get_cache(url);
  if cache and c:return{"success":True,"content":c,"method":"cache"}
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
  return{"success":False,"error":"Failed"}
dumper=Dumper()
def split_msg(t):return[t[i:i+1900]for i in range(0,len(t),1900)]if t else[""]
async def send_ai(ch,u,c,used):
 for i,chunk in enumerate(split_msg(c)):
  e=discord.Embed(description=chunk,color=0x5865F2)
  if i==0:e.set_footer(text=f"🤖 {used} | {u.display_name}")
  await ch.send(embed=e)
@bot.event
async def on_ready():logger.info(f'🔥 {bot.user} | {len(bot.guilds)}');await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening,name=f"{PREFIX}help"))
@bot.event
async def on_command_error(ctx,e):
 if isinstance(e,commands.CommandNotFound):return
 logger.error(f"CmdErr:{e}")
@bot.event
async def on_message(msg):
 if msg.author.bot:return
 if bot.user.mentioned_in(msg)and not msg.mention_everyone:
  c=msg.content.replace(f'<@{bot.user.id}>','').replace(f'<@!{bot.user.id}>','').strip()
  if c:
   if db.banned(msg.author.id):return
   ok,rem=rl.check(msg.author.id,"ai",5)
   if not ok:return await msg.channel.send(f"⏳ {rem:.0f}s",delete_after=5)
   async with msg.channel.typing():r,u=ask_ai(c,msg.author.id);await send_ai(msg.channel,msg.author,r,u);db.stat("ai",msg.author.id)
  else:
   m=db.get_model(msg.author.id);info=MODEL_INFO.get(m,("","?","",""))
   await msg.channel.send(f"👋 {msg.author.mention} Model: {info[0]} **{info[1]}**",delete_after=10)
  return
 await bot.process_commands(msg)
@bot.command(name="ai",aliases=["a"])
async def cmd_ai(ctx,*,p:str=None):
 if db.banned(ctx.author.id):return
 if not p:return await ctx.send(f"❌ `{PREFIX}ai <text>`")
 ok,rem=rl.check(ctx.author.id,"ai",5)
 if not ok:return await ctx.send(f"⏳ {rem:.0f}s",delete_after=5)
 async with ctx.typing():r,u=ask_ai(p,ctx.author.id);await send_ai(ctx.channel,ctx.author,r,u);db.stat("ai",ctx.author.id)
@bot.command(name="model",aliases=["m"])
async def cmd_model(ctx):
 cur=db.get_model(ctx.author.id);info=MODEL_INFO.get(cur,("","?","",""));avail=get_available_models(ctx.author.id)
 e=discord.Embed(title="🤖 Model Selection",description=f"Current: {info[0]} **{info[1]}**\nAvailable: `{len(avail)}` models",color=0x5865F2)
 if len(avail)>25:e.set_footer(text="Models split into multiple dropdowns")
 await ctx.send(embed=e,view=ModelView(ctx.author.id))
@bot.command(name="setpublic",aliases=["sp"])
async def cmd_sp(ctx,*,models:str=None):
 if not is_owner(ctx.author.id):return await ctx.send("❌ Owner only")
 if not models:
  cur=db.get_setting("public_model_access")or"groq"
  return await ctx.send(f"📋 Current: `{cur}`\n\n`{PREFIX}sp groq` - Groq only\n`{PREFIX}sp groq,cohere` - Multiple\n`{PREFIX}sp all` - All free\n`{PREFIX}sp none` - Owner only\n\nFree: `{','.join(FREE_MODELS[:8])}...`")
 m=models.lower().strip()
 if m=="none":db.set_setting("public_model_access","");await ctx.send("✅ Public: **None**")
 elif m=="all":db.set_setting("public_model_access",",".join(FREE_MODELS));await ctx.send(f"✅ Public: **All free** ({len(FREE_MODELS)})")
 else:
  valid=[x.strip()for x in m.split(",")if x.strip()in FREE_MODELS]
  if not valid:return await ctx.send(f"❌ Invalid. Free: `{','.join(FREE_MODELS)}`")
  db.set_setting("public_model_access",",".join(valid));await ctx.send(f"✅ Public: `{','.join(valid)}`")
@bot.command(name="allowuser",aliases=["au"])
async def cmd_au(ctx,user:discord.User=None,*,models:str=None):
 if not is_owner(ctx.author.id):return await ctx.send("❌ Owner only")
 if not user:return await ctx.send(f"`{PREFIX}au @user model1,model2`")
 if not models:return await ctx.send(f"📋 {user.mention}: `{','.join(db.get_user_allowed(user.id))or'None'}`")
 if models.lower()=="reset":db.rem_user_allowed(user.id);return await ctx.send(f"✅ Reset {user.mention}")
 valid=[x.strip()for x in models.split(",")if x.strip()in FREE_MODELS]
 if not valid:return await ctx.send("❌ Invalid models")
 db.set_user_allowed(user.id,valid);await ctx.send(f"✅ {user.mention}: `{','.join(valid)}`")
@bot.command(name="imagine",aliases=["img"])
async def cmd_img(ctx,*,p:str=None):
 if db.banned(ctx.author.id):return
 if not KEY_POLLINATIONS:return await ctx.send("❌ Not configured")
 if not p:return await ctx.send(f"❌ `{PREFIX}img <prompt>`")
 ok,rem=rl.check(ctx.author.id,"img",15)
 if not ok:return await ctx.send(f"⏳ {rem:.0f}s",delete_after=5)
 model=db.get_img_model(ctx.author.id);info=IMG_INFO.get(model,("🎨","flux",""))
 msg=await ctx.send(f"🎨 Generating {info[0]} `{info[1]}`...")
 try:
  img,err=await gen_image(p,model)
  if img:await ctx.send(f"{info[0]} **{p[:80]}**",file=discord.File(io.BytesIO(img),"gen.png"));await msg.delete();db.stat("img",ctx.author.id)
  else:await msg.edit(content=f"❌ {err}")
 except Exception as e:await msg.edit(content=f"❌ {str(e)[:50]}")
@bot.command(name="imgmodel",aliases=["im"])
async def cmd_im(ctx):
 cur=db.get_img_model(ctx.author.id);info=IMG_INFO.get(cur,("","?",""))
 await ctx.send(f"🎨 Current: {info[0]} **{info[1]}**",view=ImgView(ctx.author.id))
@bot.command(name="shield",aliases=["sh"])
async def cmd_sh(ctx):
 if not is_owner(ctx.author.id):return await ctx.send("❌ Owner only")
 await ctx.send(f"🛡️ Shield: `{SHIELD_URL or'Not configured'}`",view=ShieldView())
@bot.command(name="shieldm",aliases=["sm"])
async def cmd_sm(ctx):
 if not is_owner(ctx.author.id):return await ctx.send("❌ Owner only")
 await ctx.send("⚙️ Format: `type:value`",view=ShieldMgmtView())
@bot.command(name="dump",aliases=["dl"])
async def cmd_dump(ctx,url:str=None,*,f:str=""):
 if db.banned(ctx.author.id):return
 if not url:return await ctx.send(f"❌ `{PREFIX}dump <url>`")
 ok,rem=rl.check(ctx.author.id,"dump",10)
 if not ok:return await ctx.send(f"⏳ {rem:.0f}s",delete_after=5)
 if not url.startswith("http"):url="https://"+url
 msg=await ctx.send("🔄 Dumping...")
 r=dumper.dump(url,"--nocache"not in f)
 if r["success"]:
  c=r["content"];ext="lua"if"local "in c[:500]else"html"if"<html"in c[:200].lower()else"txt"
  await ctx.send(f"✅ `{r['method']}` | `{len(c):,}b`",file=discord.File(io.BytesIO(c.encode()),f"dump.{ext}"));await msg.delete();db.stat("dump",ctx.author.id)
 else:await msg.edit(content=f"❌ {r.get('error')}")
@bot.command(name="clear")
async def cmd_clear(ctx):mem.clear(ctx.author.id);await ctx.send("🧹 Cleared!",delete_after=5)
@bot.command(name="ping",aliases=["p"])
async def cmd_ping(ctx):
 m=db.get_model(ctx.author.id);info=MODEL_INFO.get(m,("","?","",""))
 e=discord.Embed(title="🏓 Pong!",color=0x00FF00)
 e.add_field(name="Ping",value=f"`{round(bot.latency*1000)}ms`",inline=True)
 e.add_field(name="Model",value=f"{info[0]}`{info[1]}`",inline=True)
 e.add_field(name="Access",value=f"`{'Owner'if is_owner(ctx.author.id)else'Public'}`",inline=True)
 await ctx.send(embed=e)
@bot.command(name="help",aliases=["h"])
async def cmd_help(ctx):
 e=discord.Embed(title="📚 Help",color=0x5865F2)
 e.add_field(name="🤖 AI",value=f"`{PREFIX}ai <text>`\n`@bot <text>`\n`{PREFIX}model`",inline=True)
 e.add_field(name="🎨 Image",value=f"`{PREFIX}img <prompt>`\n`{PREFIX}imgmodel`",inline=True)
 e.add_field(name="🔧 Tools",value=f"`{PREFIX}dump <url>`\n`{PREFIX}clear` `{PREFIX}ping`",inline=True)
 if is_owner(ctx.author.id):e.add_field(name="👑 Owner",value=f"`{PREFIX}sp` `{PREFIX}au`\n`{PREFIX}sh` `{PREFIX}sm` `{PREFIX}testai`",inline=False)
 await ctx.send(embed=e)
@bot.command(name="testai")
async def cmd_testai(ctx):
 if not is_owner(ctx.author.id):return await ctx.send("❌ Owner only")
 msg=await ctx.send("🔄 Testing...")
 test=[{"role":"user","content":"Say OK"}]
 results=[]
 providers=[("Groq",lambda:call_groq(test),KEY_GROQ),("Cohere",lambda:call_cohere(test),KEY_COHERE),("Cerebras",lambda:call_cerebras(test),KEY_CEREBRAS),("Mistral",lambda:call_mistral(test),KEY_MISTRAL),("Moonshot",lambda:call_moonshot(test),KEY_MOONSHOT),("HF",lambda:call_huggingface(test),KEY_HUGGINGFACE),("CF",lambda:call_cloudflare(test),CF_API_TOKEN),("SN",lambda:call_sambanova(test),KEY_SAMBANOVA),("Together",lambda:call_together(test),KEY_TOGETHER),("OR",lambda:call_openrouter(test,"or_gemini"),KEY_OPENROUTER),("Tavily",lambda:call_tavily(test),KEY_TAVILY),("Poll",lambda:call_poll_free("OK"),True)]
 for name,fn,key in providers:
  if not key:results.append(f"⚪ {name}");continue
  try:r=fn();results.append(f"✅ {name}"if r else f"❌ {name}")
  except Exception as ex:results.append(f"❌ {name}");logger.error(f"Test {name}:{ex}")
 await msg.edit(content=f"**AI Status:**\n{' | '.join(results)}")
@bot.command(name="blacklist",aliases=["bl"])
async def cmd_bl(ctx,act:str=None,user:discord.User=None):
 if not is_owner(ctx.author.id):return
 if not act or not user:return await ctx.send(f"`{PREFIX}bl add/rem @user`")
 if act in["add","ban"]:db.add_bl(user.id);await ctx.send(f"✅ {user} banned")
 elif act in["rem","remove"]:db.rem_bl(user.id);await ctx.send(f"✅ {user} unbanned")
if __name__=="__main__":
 keep_alive()
 print("="*50)
 print("🚀 Bot Starting...")
 print(f"👑 Owners: {OWNER_IDS}")
 print(f"🔒 Public: {db.get_setting('public_model_access')or'groq'}")
 print(f"🛡️ Shield: {'✅'if SHIELD_URL else'❌'}")
 keys=[("Groq",KEY_GROQ),("Cohere",KEY_COHERE),("Cerebras",KEY_CEREBRAS),("CF",CF_API_TOKEN),("SN",KEY_SAMBANOVA),("Together",KEY_TOGETHER),("OR",KEY_OPENROUTER),("Poll",KEY_POLLINATIONS),("Mistral",KEY_MISTRAL),("Moonshot",KEY_MOONSHOT),("HF",KEY_HUGGINGFACE),("Replicate",KEY_REPLICATE),("Tavily",KEY_TAVILY)]
 for n,k in keys:print(f"   {n}:{'✅'if k else'❌'}")
 print("="*50)
 bot.run(DISCORD_TOKEN,log_handler=None)
