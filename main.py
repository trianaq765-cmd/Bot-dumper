import discord,os,io,re,time,json,logging,sqlite3,random,threading,hashlib,asyncio
from collections import defaultdict
from dataclasses import dataclass
from discord.ext import commands
from discord import ui
from urllib.parse import quote
try:from web_panel import start_web_panel,get_key as wp_get_key,get_model as wp_get_model,get_all_models as wp_get_all_models,get_setting as wp_get_setting,config as wp_config
except Exception as e:print(f"Web panel import error: {e}");start_web_panel=None;wp_get_key=None;wp_get_model=None;wp_get_all_models=None;wp_get_setting=None;wp_config=None
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
 k=get_api_key("groq")
 if _groq is None and k:
  try:from groq import Groq;_groq=Groq(api_key=k)
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
def get_api_key(name):
 if wp_get_key:
  k=wp_get_key(name)
  if k:return k
 mapping={"groq":KEY_GROQ,"openrouter":KEY_OPENROUTER,"cerebras":KEY_CEREBRAS,"sambanova":KEY_SAMBANOVA,"cohere":KEY_COHERE,"cloudflare_token":CF_API_TOKEN,"cloudflare_account":CF_ACCOUNT_ID,"together":KEY_TOGETHER,"tavily":KEY_TAVILY,"mistral":KEY_MISTRAL,"replicate":KEY_REPLICATE,"huggingface":KEY_HUGGINGFACE,"moonshot":KEY_MOONSHOT}
 return mapping.get(name,"")or os.getenv(name.upper()+"_API_KEY","")
class ShieldAPI:
 def __init__(self,url,key):self.url=url;self.key=key;self.timeout=30
 def _h(self):return{"x-admin-key":self.key,"Content-Type":"application/json","Accept":"application/json"}
 def _get(self,ep):
  if not self.url or not self.key:return{"success":False,"error":"Not configured"}
  try:r=get_requests().get(f"{self.url}{ep}",headers=self._h(),timeout=self.timeout);return r.json()if r.status_code==200 else{"success":False,"error":f"HTTP {r.status_code}"}
  except Exception as e:return{"success":False,"error":str(e)[:80]}
 def _post(self,ep,data=None):
  if not self.url or not self.key:return{"success":False,"error":"Not configured"}
  try:r=get_requests().post(f"{self.url}{ep}",headers=self._h(),json=data or{},timeout=self.timeout);return r.json()if r.status_code in[200,201]else{"success":False,"error":f"HTTP {r.status_code}"}
  except Exception as e:return{"success":False,"error":str(e)[:80]}
 def _del(self,ep):
  if not self.url or not self.key:return{"success":False,"error":"Not configured"}
  try:r=get_requests().delete(f"{self.url}{ep}",headers=self._h(),timeout=self.timeout);return r.json()if r.status_code==200 else{"success":False,"error":f"HTTP {r.status_code}"}
  except Exception as e:return{"success":False,"error":str(e)[:80]}
 def stats(self):return self._get("/api/admin/stats")
 def sessions(self):return self._get("/api/admin/sessions")
 def logs(self):return self._get("/api/admin/logs")
 def bans(self):return self._get("/api/admin/bans")
 def whitelist(self):return self._get("/api/admin/whitelist")
 def suspended(self):return self._get("/api/admin/suspended")
 def script(self):return self._get("/api/admin/script")
 def health(self):
  try:r=get_requests().get(f"{self.url}/api/keepalive",timeout=10);return{"success":r.status_code==200}
  except:return{"success":False}
 def add_ban(self,hwid=None,ip=None,pid=None,reason="Via Discord"):
  d={"reason":reason}
  if hwid:d["hwid"]=hwid
  if ip:d["ip"]=ip
  if pid:d["playerId"]=pid
  return self._post("/api/admin/bans",d)
 def rem_ban(self,bid):return self._del(f"/api/admin/bans/{bid}")
 def add_wl(self,t,v):return self._post("/api/admin/whitelist",{"type":t,"value":v})
 def rem_wl(self,t,v):return self._post("/api/admin/whitelist/remove",{"type":t,"value":v})
 def suspend(self,t,v,reason="Via Discord",dur=None):d={"type":t,"value":v,"reason":reason};d["duration"]=dur if dur else None;return self._post("/api/admin/suspend",d)
 def unsuspend(self,t,v):return self._post("/api/admin/unsuspend",{"type":t,"value":v})
 def kill(self,sid,reason="Via Discord"):return self._post("/api/admin/kill-session",{"sessionId":sid,"reason":reason})
 def clear_sessions(self):return self._post("/api/admin/sessions/clear",{})
 def clear_logs(self):return self._post("/api/admin/logs/clear",{})
 def clear_cache(self):return self._post("/api/admin/cache/clear",{})
shield=ShieldAPI(SHIELD_URL,SHIELD_ADMIN_KEY)
class Database:
 def __init__(self,path="bot.db"):
  self.conn=sqlite3.connect(path,check_same_thread=False);self.lock=threading.Lock()
  self.conn.executescript('''CREATE TABLE IF NOT EXISTS user_prefs(uid INTEGER PRIMARY KEY,model TEXT DEFAULT "groq",img_model TEXT DEFAULT "flux");
CREATE TABLE IF NOT EXISTS bot_settings(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS stats(id INTEGER PRIMARY KEY,cmd TEXT,uid INTEGER,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS blacklist(uid INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS allowed_users(uid INTEGER PRIMARY KEY,allowed_models TEXT DEFAULT "groq");
CREATE TABLE IF NOT EXISTS dump_cache(url TEXT PRIMARY KEY,content TEXT,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);''')
  self._init()
 def _init(self):
  with self.lock:
   if not self.conn.execute('SELECT 1 FROM bot_settings WHERE key="public_default"').fetchone():self.conn.execute('INSERT INTO bot_settings VALUES("public_default","groq")');self.conn.commit()
 def get_setting(self,k):
  with self.lock:r=self.conn.execute('SELECT value FROM bot_settings WHERE key=?',(k,)).fetchone();return r[0]if r else None
 def set_setting(self,k,v):
  with self.lock:self.conn.execute('INSERT OR REPLACE INTO bot_settings VALUES(?,?)',(k,v));self.conn.commit()
 def get_model(self,uid):
  with self.lock:r=self.conn.execute('SELECT model FROM user_prefs WHERE uid=?',(uid,)).fetchone();return r[0]if r else"groq"
 def set_model(self,uid,m):
  with self.lock:self.conn.execute('INSERT OR REPLACE INTO user_prefs(uid,model,img_model)VALUES(?,?,COALESCE((SELECT img_model FROM user_prefs WHERE uid=?),"flux"))',(uid,m,uid));self.conn.commit()
 def get_img(self,uid):
  with self.lock:r=self.conn.execute('SELECT img_model FROM user_prefs WHERE uid=?',(uid,)).fetchone();return r[0]if r else"flux"
 def set_img(self,uid,m):
  with self.lock:self.conn.execute('INSERT OR REPLACE INTO user_prefs(uid,model,img_model)VALUES(?,COALESCE((SELECT model FROM user_prefs WHERE uid=?),"groq"),?)',(uid,uid,m));self.conn.commit()
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
  with self.lock:now=time.time();last=self.cd[uid][cmd]
  if now-last<cd:return False,cd-(now-last)
  self.cd[uid][cmd]=now;return True,0
rl=RateLimiter()
@dataclass
class ChatMsg:
 role:str
 content:str
 ts:float
class Memory:
 def __init__(self):self.conv=defaultdict(list);self.lock=threading.Lock()
 def add(self,uid,role,content):
  with self.lock:now=time.time();self.conv[uid]=[m for m in self.conv[uid]if now-m.ts<1800];self.conv[uid].append(ChatMsg(role,content[:2500],now))
  if len(self.conv[uid])>25:self.conv[uid]=self.conv[uid][-25:]
 def get(self,uid):
  with self.lock:now=time.time();self.conv[uid]=[m for m in self.conv[uid]if now-m.ts<1800];return[{"role":m.role,"content":m.content}for m in self.conv[uid]]
 def clear(self,uid):
  with self.lock:self.conv[uid]=[]
mem=Memory()
class Dumper:
 def __init__(self):self.last=None
 def dump(self,url,cache=True):
  if cache:c=db.get_cache(url);
  if cache and c:return{"success":True,"content":c,"method":"cache"}
  req=get_requests();curl=get_curl();cs=get_cloudscraper();methods=[]
  if curl:methods.append(("curl",lambda u:curl.get(u,impersonate="chrome120",headers={"User-Agent":"Roblox/WinInet"},timeout=25)))
  if cs:methods.append(("cloudscraper",lambda u:cs.get(u,timeout=25)))
  if req:methods.append(("requests",lambda u:req.get(u,headers={"User-Agent":"Roblox/WinInet"},timeout=25)))
  if self.last:methods.sort(key=lambda x:x[0]!=self.last)
  for name,func in methods:
   try:r=func(url)
   except:continue
   if r.status_code==200 and len(r.text)>10:self.last=name;db.cache_dump(url,r.text)if cache else None;return{"success":True,"content":r.text,"method":name}
  return{"success":False,"error":"All methods failed"}
dumper=Dumper()
SYS_PROMPT='''You are an elite AI assistant. Be helpful, accurate, and concise. Default language: Bahasa Indonesia.'''
MODELS={"groq":{"e":"⚡","n":"Groq","d":"Llama 3.3 70B","c":"main","p":"groq","m":"llama-3.3-70b-versatile"},"cerebras":{"e":"🧠","n":"Cerebras","d":"Llama 3.3 70B","c":"main","p":"cerebras","m":"llama-3.3-70b"},"sambanova":{"e":"🦣","n":"SambaNova","d":"Llama 3.3 70B","c":"main","p":"sambanova","m":"Meta-Llama-3.3-70B-Instruct"},"cloudflare":{"e":"☁️","n":"Cloudflare","d":"Llama 3.3 70B","c":"main","p":"cloudflare","m":"@cf/meta/llama-3.3-70b-instruct-fp8-fast"},"cohere":{"e":"🔷","n":"Cohere","d":"Command R+","c":"main","p":"cohere","m":"command-r-plus-08-2024"},"mistral":{"e":"Ⓜ️","n":"Mistral","d":"Mistral Small","c":"main","p":"mistral","m":"mistral-small-latest"},"together":{"e":"🤝","n":"Together","d":"Llama 3.3","c":"main","p":"together","m":"meta-llama/Llama-3.3-70B-Instruct-Turbo"},"tavily":{"e":"🔍","n":"Tavily","d":"Search","c":"main","p":"tavily","m":"search"},"or_llama":{"e":"🦙","n":"OR-Llama","d":"Llama 3.3","c":"openrouter","p":"openrouter","m":"meta-llama/llama-3.3-70b-instruct:free"},"or_gemini":{"e":"💎","n":"OR-Gemini","d":"Gemini 2.0","c":"openrouter","p":"openrouter","m":"google/gemini-2.0-flash-exp:free"},"or_deepseek":{"e":"🌊","n":"OR-DeepSeek","d":"DeepSeek","c":"openrouter","p":"openrouter","m":"deepseek/deepseek-chat:free"},"p_openai":{"e":"🤖","n":"Poll-OpenAI","d":"OpenAI","c":"pollinations","p":"pollinations","m":"openai-large"},"p_claude":{"e":"🎭","n":"Poll-Claude","d":"Claude","c":"pollinations","p":"pollinations","m":"claude-hybridspace"},"poll_free":{"e":"🌸","n":"Poll-Free","d":"Free","c":"pollinations","p":"pollinations","m":"free"}}
IMG_MODELS={"flux":("🎨","Flux","Standard"),"flux_pro":("⚡","Flux Pro","Pro"),"turbo":("🚀","Turbo","Fast"),"dalle":("🤖","DALL-E 3","OpenAI"),"sdxl":("🖼️","SDXL","SD")}
ALL_MODELS=list(MODELS.keys())
def is_owner(uid):return uid in OWNER_IDS
def get_public_default():
 if wp_get_setting:s=wp_get_setting("default_model");
 else:s=None
 return s or db.get_setting("public_default")or"groq"
def call_groq(msgs):
 c=get_groq()
 if not c:return None
 try:r=c.chat.completions.create(messages=msgs,model=MODELS["groq"]["m"],temperature=0.7,max_tokens=4096);return r.choices[0].message.content
 except Exception as e:logger.error(f"Groq:{e}");return None
def call_cerebras(msgs):
 k=get_api_key("cerebras")
 if not k:return None
 try:r=get_requests().post("https://api.cerebras.ai/v1/chat/completions",headers={"Authorization":f"Bearer {k}","Content-Type":"application/json"},json={"model":MODELS["cerebras"]["m"],"messages":msgs,"max_tokens":4096},timeout=30);return r.json()["choices"][0]["message"]["content"]if r.status_code==200 else None
 except Exception as e:logger.error(f"Cerebras:{e}");return None
def call_sambanova(msgs):
 k=get_api_key("sambanova")
 if not k:return None
 try:r=get_requests().post("https://api.sambanova.ai/v1/chat/completions",headers={"Authorization":f"Bearer {k}","Content-Type":"application/json"},json={"model":MODELS["sambanova"]["m"],"messages":msgs,"max_tokens":4096},timeout=45);return r.json()["choices"][0]["message"]["content"]if r.status_code==200 else None
 except Exception as e:logger.error(f"SambaNova:{e}");return None
def call_cloudflare(msgs):
 acc=get_api_key("cloudflare_account");tok=get_api_key("cloudflare_token")
 if not acc or not tok:return None
 try:r=get_requests().post(f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{MODELS['cloudflare']['m']}",headers={"Authorization":f"Bearer {tok}","Content-Type":"application/json"},json={"messages":msgs,"max_tokens":4096},timeout=45);d=r.json();return d["result"]["response"].strip()if r.status_code==200 and d.get("success")else None
 except Exception as e:logger.error(f"CF:{e}");return None
def call_cohere(msgs):
 k=get_api_key("cohere")
 if not k:return None
 try:sys_p="";user_m=msgs[-1]["content"]if msgs else"Hi"
 except:user_m="Hi"
 for m in msgs:
  if m.get("role")=="system":sys_p=m["content"]
 payload={"model":MODELS["cohere"]["m"],"message":user_m}
 if sys_p:payload["preamble"]=sys_p
 try:r=get_requests().post("https://api.cohere.com/v1/chat",headers={"Authorization":f"Bearer {k}","Content-Type":"application/json"},json=payload,timeout=45);return r.json().get("text")if r.status_code==200 else None
 except Exception as e:logger.error(f"Cohere:{e}");return None
def call_mistral(msgs):
 k=get_api_key("mistral")
 if not k:return None
 try:r=get_requests().post("https://api.mistral.ai/v1/chat/completions",headers={"Authorization":f"Bearer {k}","Content-Type":"application/json"},json={"model":MODELS["mistral"]["m"],"messages":msgs,"max_tokens":4096},timeout=45);return r.json()["choices"][0]["message"]["content"]if r.status_code==200 else None
 except Exception as e:logger.error(f"Mistral:{e}");return None
def call_together(msgs):
 k=get_api_key("together")
 if not k:return None
 try:r=get_requests().post("https://api.together.xyz/v1/chat/completions",headers={"Authorization":f"Bearer {k}","Content-Type":"application/json"},json={"model":MODELS["together"]["m"],"messages":msgs,"max_tokens":4096},timeout=45);return r.json()["choices"][0]["message"]["content"]if r.status_code==200 else None
 except Exception as e:logger.error(f"Together:{e}");return None
def call_tavily(msgs):
 k=get_api_key("tavily")
 if not k:return None
 try:q=msgs[-1]["content"]if msgs else"";r=get_requests().post("https://api.tavily.com/search",json={"api_key":k,"query":q,"search_depth":"advanced","max_results":5},timeout=20)
 except Exception as e:logger.error(f"Tavily:{e}");return None
 if r.status_code==200:d=r.json();results=d.get("results",[])[:5];ctx="\n".join([f"• {x.get('title','')}: {x.get('content','')[:100]}"for x in results]);ans=d.get("answer","");return f"🔍 {ans}\n\n{ctx}"if ans else f"🔍 {ctx}"if ctx else None
 return None
def call_openrouter(msgs,model_key):
 k=get_api_key("openrouter")
 if not k:return None
 mid=MODELS.get(model_key,{}).get("m",MODELS["or_llama"]["m"])
 try:r=get_requests().post("https://openrouter.ai/api/v1/chat/completions",headers={"Authorization":f"Bearer {k}","Content-Type":"application/json","HTTP-Referer":"https://github.com"},json={"model":mid,"messages":msgs,"max_tokens":4096},timeout=60);d=r.json();return d["choices"][0]["message"]["content"]if r.status_code==200 and"choices"in d else None
 except Exception as e:logger.error(f"OR:{e}");return None
def call_pollinations(msgs,model_key):
 mid=MODELS.get(model_key,{}).get("m","openai-large")
 try:
  if mid=="free":prompt=msgs[-1]["content"]if msgs else"";r=get_requests().get(f"https://text.pollinations.ai/{quote(prompt[:3000])}",timeout=60)
  else:r=get_requests().post("https://text.pollinations.ai/",headers={"Content-Type":"application/json"},json={"messages":msgs,"model":mid},timeout=60)
  return r.text.strip()if r.status_code==200 and r.text.strip()else None
 except Exception as e:logger.error(f"Poll:{e}");return None
def call_ai(model,msgs):
 m=MODELS.get(model,{});p=m.get("p","groq")
 if p=="groq":return call_groq(msgs),m.get("n","Groq")
 elif p=="cerebras":return call_cerebras(msgs),m.get("n","Cerebras")
 elif p=="sambanova":return call_sambanova(msgs),m.get("n","SambaNova")
 elif p=="cloudflare":return call_cloudflare(msgs),m.get("n","Cloudflare")
 elif p=="cohere":return call_cohere(msgs),m.get("n","Cohere")
 elif p=="mistral":return call_mistral(msgs),m.get("n","Mistral")
 elif p=="together":return call_together(msgs),m.get("n","Together")
 elif p=="tavily":return call_tavily(msgs),m.get("n","Tavily")
 elif p=="openrouter":return call_openrouter(msgs,model),m.get("n","OpenRouter")
 elif p=="pollinations":return call_pollinations(msgs,model),m.get("n","Pollinations")
 return None,"Unknown"
FALLBACK=[("groq",call_groq),("cerebras",call_cerebras),("sambanova",call_sambanova),("poll_free",lambda m:call_pollinations(m,"poll_free"))]
def ask_ai(prompt,uid=None,model=None):
 sel=model or(db.get_model(uid)if is_owner(uid)else get_public_default())
 msgs=[{"role":"system","content":SYS_PROMPT}]
 if uid:h=mem.get(uid);msgs.extend(h[-10:])if h else None
 msgs.append({"role":"user","content":prompt})
 result,prov=call_ai(sel,msgs)
 if not result:
  for name,func in FALLBACK:
   if name==sel:continue
   try:result=func(msgs)
   except:continue
   if result:prov=name.title();break
 if not result:return"Maaf, AI tidak tersedia.","None"
 if uid:mem.add(uid,"user",prompt[:1500]);mem.add(uid,"assistant",result[:1500])
 return result,prov
async def gen_image(prompt,model="flux"):
 mid={"flux":"flux","flux_pro":"flux-pro","turbo":"turbo","dalle":"dall-e-3","sdxl":"sdxl"}.get(model,"flux")
 try:r=get_requests().get(f"https://image.pollinations.ai/prompt/{quote(prompt)}?model={mid}&nologo=true&width=1024&height=1024&seed={random.randint(1,99999)}",timeout=120);return(r.content,None)if r.status_code==200 and len(r.content)>1000 else(None,f"HTTP {r.status_code}")
 except Exception as e:return None,str(e)[:50]
class ModelSelect(ui.Select):
 def __init__(self,cat,cid):
  models=[m for m,d in MODELS.items()if d["c"]==cat]
  super().__init__(placeholder=f"{cat.title()} Models...",options=[discord.SelectOption(label=MODELS[m]["n"],value=m,emoji=MODELS[m]["e"],description=MODELS[m]["d"])for m in models[:25]],custom_id=cid)
 async def callback(self,i:discord.Interaction):
  if not is_owner(i.user.id):return await i.response.send_message("❌ Owner only!",ephemeral=True)
  db.set_model(i.user.id,self.values[0]);m=MODELS.get(self.values[0],{})
  await i.response.send_message(f"✅ {m.get('e','')} **{m.get('n','')}**",ephemeral=True)
class ModelView(ui.View):
 def __init__(self):super().__init__(timeout=None);self.add_item(ModelSelect("main","m1"));self.add_item(ModelSelect("openrouter","m2"));self.add_item(ModelSelect("pollinations","m3"))
class ImgSelect(ui.Select):
 def __init__(self):super().__init__(placeholder="Image Model...",options=[discord.SelectOption(label=v[1],value=k,emoji=v[0],description=v[2])for k,v in IMG_MODELS.items()],custom_id="imgsel")
 async def callback(self,i:discord.Interaction):
  if not is_owner(i.user.id):return await i.response.send_message("❌ Owner only!",ephemeral=True)
  db.set_img(i.user.id,self.values[0]);v=IMG_MODELS.get(self.values[0],("?","?",""))
  await i.response.send_message(f"✅ {v[0]} **{v[1]}**",ephemeral=True)
class ImgView(ui.View):
 def __init__(self):super().__init__(timeout=None);self.add_item(ImgSelect())
class DefaultSelect(ui.Select):
 def __init__(self):super().__init__(placeholder="Set Default...",options=[discord.SelectOption(label=MODELS[m]["n"],value=m,emoji=MODELS[m]["e"])for m in["groq","cerebras","sambanova","poll_free"]],custom_id="defsel")
 async def callback(self,i:discord.Interaction):
  if not is_owner(i.user.id):return await i.response.send_message("❌ Owner only!",ephemeral=True)
  db.set_setting("public_default",self.values[0])
  if wp_config:wp_config.set_setting("default_model",self.values[0])
  m=MODELS.get(self.values[0],{});await i.response.send_message(f"✅ Default: {m.get('e','')} **{m.get('n','')}**",ephemeral=True)
class DefaultView(ui.View):
 def __init__(self):super().__init__(timeout=None);self.add_item(DefaultSelect())
class ShieldInfoSelect(ui.Select):
 def __init__(self):super().__init__(placeholder="View...",options=[discord.SelectOption(label="Stats",value="stats",emoji="📊"),discord.SelectOption(label="Sessions",value="sessions",emoji="🔄"),discord.SelectOption(label="Bans",value="bans",emoji="🚫"),discord.SelectOption(label="Health",value="health",emoji="💚"),discord.SelectOption(label="Bot Stats",value="botstats",emoji="📈")],custom_id="shinfo")
 async def callback(self,i:discord.Interaction):
  if not is_owner(i.user.id):return await i.response.send_message("❌ Owner only!",ephemeral=True)
  await i.response.defer(ephemeral=True);a=self.values[0];embed=discord.Embed(color=0x3498DB)
  if a=="stats":d=shield.stats();embed.title="📊 Shield Stats";embed.description=str(d)[:1000]if d else"No data"
  elif a=="sessions":d=shield.sessions();embed.title="🔄 Sessions";embed.description=str(d.get("sessions",[]))[:1000]if isinstance(d,dict)else"No data"
  elif a=="bans":d=shield.bans();embed.title="🚫 Bans";embed.description=str(d.get("bans",[]))[:1000]if isinstance(d,dict)else"No data"
  elif a=="health":d=shield.health();embed.title="💚 Health";embed.description="✅ ONLINE"if d.get("success")else"❌ OFFLINE";embed.color=0x2ECC71 if d.get("success")else 0xE74C3C
  elif a=="botstats":s=db.get_stats();embed.title="📈 Bot Stats";embed.add_field(name="Total",value=f"`{s['total']}`",inline=True);embed.add_field(name="Today",value=f"`{s['today']}`",inline=True);embed.add_field(name="Users",value=f"`{s['users']}`",inline=True)
  await i.followup.send(embed=embed,ephemeral=True)
class ShieldView(ui.View):
 def __init__(self):super().__init__(timeout=None);self.add_item(ShieldInfoSelect())
def split_msg(txt,lim=1950):
 if not txt:return[""]
 chunks=[]
 while len(txt)>lim:sp=txt.rfind('\n',0,lim);sp=lim if sp==-1 else sp;chunks.append(txt[:sp]);txt=txt[sp:].lstrip()
 if txt:chunks.append(txt)
 return chunks
async def send_resp(ch,content):
 for c in split_msg(content):await ch.send(c)
@bot.event
async def on_ready():logger.info(f"Bot ready: {bot.user}");await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening,name=f"{PREFIX}help"))
@bot.event
async def on_command_error(ctx,err):
 if isinstance(err,commands.CommandNotFound):return
 logger.error(f"Error: {err}")
@bot.event
async def on_message(msg):
 if msg.author.bot:return
 if bot.user.mentioned_in(msg)and not msg.mention_everyone:
  content=msg.content.replace(f'<@{bot.user.id}>','').replace(f'<@!{bot.user.id}>','').strip()
  if content and not db.banned(msg.author.id):
   ok,_=rl.check(msg.author.id,"ai",5)
   if ok:
    async with msg.channel.typing():resp,_=ask_ai(content,msg.author.id);await send_resp(msg.channel,resp);db.stat("ai",msg.author.id)
  return
 await bot.process_commands(msg)
@bot.command(name="ai",aliases=["a"])
async def cmd_ai(ctx,*,prompt:str=None):
 if db.banned(ctx.author.id)or not prompt:return
 ok,_=rl.check(ctx.author.id,"ai",5)
 if ok:async with ctx.typing():resp,_=ask_ai(prompt,ctx.author.id);await send_resp(ctx.channel,resp);db.stat("ai",ctx.author.id)
@bot.command(name="model",aliases=["m"])
async def cmd_model(ctx):
 if not is_owner(ctx.author.id):return await ctx.send(f"Model: {get_public_default()}",delete_after=10)
 curr=db.get_model(ctx.author.id);m=MODELS.get(curr,{})
 embed=discord.Embed(title="🤖 Models",description=f"Current: {m.get('e','')} {m.get('n','')}",color=0x5865F2)
 await ctx.send(embed=embed,view=ModelView())
@bot.command(name="setdefault",aliases=["sd"])
async def cmd_sd(ctx):
 if not is_owner(ctx.author.id):return
 await ctx.send(embed=discord.Embed(title="🌍 Set Default",color=0x3498DB),view=DefaultView())
@bot.command(name="imagine",aliases=["img"])
async def cmd_img(ctx,*,prompt:str=None):
 if not is_owner(ctx.author.id)or not prompt:return
 st=await ctx.send("🎨 Generating...")
 data,err=await gen_image(prompt,db.get_img(ctx.author.id))
 if data:f=discord.File(io.BytesIO(data),"image.png");await ctx.send(file=f);await st.delete();db.stat("img",ctx.author.id)
 else:await st.edit(content=f"❌ {err}")
@bot.command(name="imgmodel",aliases=["im"])
async def cmd_im(ctx):
 if not is_owner(ctx.author.id):return
 await ctx.send(embed=discord.Embed(title="🎨 Image Model",color=0x5865F2),view=ImgView())
@bot.command(name="dump",aliases=["dl"])
async def cmd_dump(ctx,url:str=None):
 if not url:return
 if not url.startswith("http"):url="https://"+url
 st=await ctx.send("🔄 Dumping...")
 result=dumper.dump(url)
 if result["success"]:content=result["content"];f=discord.File(io.BytesIO(content.encode()),"dump.txt");await ctx.send(f"✅ {result['method']} | {len(content):,} bytes",file=f);await st.delete();db.stat("dump",ctx.author.id)
 else:await st.edit(content=f"❌ {result.get('error')}")
@bot.command(name="shield",aliases=["sh"])
async def cmd_shield(ctx):
 if not is_owner(ctx.author.id):return
 st=shield.health();embed=discord.Embed(title="🛡️ Shield",color=0x2ECC71 if st.get("success")else 0xE74C3C)
 embed.add_field(name="Status",value="🟢 ONLINE"if st.get("success")else"🔴 OFFLINE",inline=True)
 await ctx.send(embed=embed,view=ShieldView())
@bot.command(name="clear")
async def cmd_clear(ctx):mem.clear(ctx.author.id);await ctx.send("🧹 Cleared!",delete_after=5)
@bot.command(name="ping",aliases=["p"])
async def cmd_ping(ctx):await ctx.send(f"🏓 {round(bot.latency*1000)}ms")
@bot.command(name="status")
async def cmd_status(ctx):
 if not is_owner(ctx.author.id):return
 keys=[("Groq","groq"),("Cerebras","cerebras"),("SambaNova","sambanova"),("OpenRouter","openrouter"),("Cohere","cohere")]
 st="\n".join([f"{'✅'if get_api_key(k)else'❌'} {n}"for n,k in keys])
 embed=discord.Embed(title="📊 Status",description=st,color=0x5865F2)
 embed.add_field(name="Web Panel",value=f"`https://bot-dumper.onrender.com`",inline=False)
 await ctx.send(embed=embed)
@bot.command(name="blacklist",aliases=["bl"])
async def cmd_bl(ctx,action:str=None,user:discord.User=None):
 if not is_owner(ctx.author.id)or not action or not user:return
 if action=="add":db.ban(user.id);await ctx.send(f"✅ Banned {user}")
 elif action=="rem":db.unban(user.id);await ctx.send(f"✅ Unbanned {user}")
@bot.command(name="stats")
async def cmd_stats(ctx):s=db.get_stats();await ctx.send(f"📈 Total: {s['total']} | Today: {s['today']} | Users: {s['users']}")
@bot.command(name="help",aliases=["h"])
async def cmd_help(ctx):
 embed=discord.Embed(title="📚 Help",color=0x5865F2)
 embed.add_field(name="AI",value=f"`{PREFIX}ai` `@mention`",inline=True)
 embed.add_field(name="Models",value=f"`{PREFIX}m` `{PREFIX}sd`",inline=True)
 embed.add_field(name="Image",value=f"`{PREFIX}img` `{PREFIX}im`",inline=True)
 embed.add_field(name="Utils",value=f"`{PREFIX}dump` `{PREFIX}clear` `{PREFIX}ping`",inline=True)
 if is_owner(ctx.author.id):embed.add_field(name="Admin",value=f"`{PREFIX}status` `{PREFIX}sh` `{PREFIX}bl` `{PREFIX}stats`",inline=True)
 embed.add_field(name="🌐 Web Panel",value="`https://bot-dumper.onrender.com`",inline=False)
 await ctx.send(embed=embed)
if __name__=="__main__":
 PORT=int(os.getenv("PORT",8080))
 ADMIN_KEY=os.getenv("WEB_ADMIN_KEY",os.getenv("ADMIN_KEY","admin123"))
 if start_web_panel:start_web_panel(host="0.0.0.0",port=PORT,admin_key=ADMIN_KEY)
 else:
  from flask import Flask
  app=Flask(__name__)
  @app.route('/')
  def home():return"Bot running!"
  @app.route('/health')
  def health():return{"status":"ok"}
  threading.Thread(target=lambda:app.run(host="0.0.0.0",port=PORT),daemon=True).start()
 print("="*50)
 print(f"🚀 Bot Starting...")
 print(f"🌐 Web: https://bot-dumper.onrender.com?key={ADMIN_KEY}")
 print(f"👑 Owners: {OWNER_IDS}")
 print("="*50)
 bot.run(DISCORD_TOKEN,log_handler=None)
