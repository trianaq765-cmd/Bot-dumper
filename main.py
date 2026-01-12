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
 def __init__(self,url,key):self.url=url;self.key=key;self.timeout=25
 def _h(self):return{"x-admin-key":self.key,"Content-Type":"application/json"}
 def _get(self,ep):
  if not self.url or not self.key:return{"success":False,"error":"Not configured"}
  try:r=get_requests().get(f"{self.url}{ep}",headers=self._h(),timeout=self.timeout);return r.json()if r.status_code==200 else{"success":False,"error":f"HTTP {r.status_code}"}
  except Exception as e:return{"success":False,"error":str(e)[:50]}
 def _post(self,ep,d=None):
  if not self.url or not self.key:return{"success":False,"error":"Not configured"}
  try:r=get_requests().post(f"{self.url}{ep}",headers=self._h(),json=d or{},timeout=self.timeout);return r.json()if r.status_code in[200,201]else{"success":False,"error":f"HTTP {r.status_code}"}
  except Exception as e:return{"success":False,"error":str(e)[:50]}
 def _del(self,ep):
  if not self.url or not self.key:return{"success":False,"error":"Not configured"}
  try:r=get_requests().delete(f"{self.url}{ep}",headers=self._h(),timeout=self.timeout);return r.json()if r.status_code==200 else{"success":False,"error":f"HTTP {r.status_code}"}
  except Exception as e:return{"success":False,"error":str(e)[:50]}
 def stats(self):return self._get("/api/admin/stats")
 def sessions(self):return self._get("/api/admin/sessions")
 def logs(self):return self._get("/api/admin/logs")
 def bans(self):return self._get("/api/admin/bans")
 def whitelist(self):return self._get("/api/admin/whitelist")
 def suspended(self):return self._get("/api/admin/suspended")
 def script(self):return self._get("/api/admin/script")
 def keepalive(self):
  try:r=get_requests().get(f"{self.url}/api/keepalive",timeout=10);return r.json()if r.status_code==200 else{"success":False,"error":f"HTTP {r.status_code}"}
  except Exception as e:return{"success":False,"error":str(e)[:50]}
 def add_ban(self,hwid=None,ip=None,pid=None,reason="Discord"):return self._post("/api/admin/bans",{"hwid":hwid,"ip":ip,"playerId":pid,"reason":reason})
 def remove_ban(self,bid):return self._del(f"/api/admin/bans/{bid}")
 def clear_bans(self):return self._post("/api/admin/bans/clear")
 def add_wl(self,t,v):return self._post("/api/admin/whitelist",{"type":t,"value":v})
 def remove_wl(self,t,v):return self._post("/api/admin/whitelist/remove",{"type":t,"value":v})
 def suspend(self,t,v,r="Discord",d=None):return self._post("/api/admin/suspend",{"type":t,"value":v,"reason":r,"duration":d})
 def unsuspend(self,t,v):return self._post("/api/admin/unsuspend",{"type":t,"value":v})
 def kill(self,sid,r="Discord"):return self._post("/api/admin/kill-session",{"sessionId":sid,"reason":r})
 def clear_sessions(self):return self._post("/api/admin/sessions/clear")
 def clear_logs(self):return self._post("/api/admin/logs/clear")
 def clear_cache(self):return self._post("/api/admin/cache/clear")
shield=ShieldAPI(SHIELD_URL,SHIELD_ADMIN_KEY)
class Database:
 def __init__(self,path="bot.db"):
  self.conn=sqlite3.connect(path,check_same_thread=False);self.lock=threading.Lock()
  self.conn.executescript('''CREATE TABLE IF NOT EXISTS user_prefs(uid INTEGER PRIMARY KEY,model TEXT DEFAULT "auto",img_model TEXT DEFAULT "flux");
   CREATE TABLE IF NOT EXISTS stats(id INTEGER PRIMARY KEY,cmd TEXT,uid INTEGER,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
   CREATE TABLE IF NOT EXISTS blacklist(uid INTEGER PRIMARY KEY);
   CREATE TABLE IF NOT EXISTS dump_cache(url TEXT PRIMARY KEY,content TEXT,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);''')
 def get_model(self,uid):
  with self.lock:r=self.conn.execute('SELECT model FROM user_prefs WHERE uid=?',(uid,)).fetchone();return r[0]if r else"auto"
 def set_model(self,uid,m):
  with self.lock:self.conn.execute('INSERT OR REPLACE INTO user_prefs(uid,model) VALUES(?,?)',(uid,m));self.conn.commit()
 def get_img_model(self,uid):
  with self.lock:r=self.conn.execute('SELECT img_model FROM user_prefs WHERE uid=?',(uid,)).fetchone();return r[0]if r else"flux"
 def set_img_model(self,uid,m):
  with self.lock:self.conn.execute('UPDATE user_prefs SET img_model=? WHERE uid=?',(m,uid));self.conn.commit()
 def stat(self,cmd,uid):
  with self.lock:self.conn.execute('INSERT INTO stats(cmd,uid) VALUES(?,?)',(cmd,uid));self.conn.commit()
 def get_stats(self):
  with self.lock:return self.conn.execute('SELECT cmd,COUNT(*) FROM stats GROUP BY cmd').fetchall()
 def banned(self,uid):
  with self.lock:return self.conn.execute('SELECT 1 FROM blacklist WHERE uid=?',(uid,)).fetchone()is not None
 def add_bl(self,uid):
  with self.lock:self.conn.execute('INSERT OR IGNORE INTO blacklist VALUES(?)',(uid,));self.conn.commit()
 def rem_bl(self,uid):
  with self.lock:self.conn.execute('DELETE FROM blacklist WHERE uid=?',(uid,));self.conn.commit()
 def cache_dump(self,url,c):
  with self.lock:h=hashlib.md5(url.encode()).hexdigest();self.conn.execute('INSERT OR REPLACE INTO dump_cache VALUES(?,?,CURRENT_TIMESTAMP)',(h,c[:500000]));self.conn.commit()
 def get_cache(self,url):
  with self.lock:h=hashlib.md5(url.encode()).hexdigest();r=self.conn.execute('SELECT content FROM dump_cache WHERE url=? AND ts>datetime("now","-1 hour")',(h,)).fetchone();return r[0]if r else None
db=Database()
class RateLimiter:
 def __init__(self):self.cd=defaultdict(lambda:defaultdict(float));self.lock=threading.Lock()
 def check(self,uid,cmd,t=5):
  with self.lock:
   now=time.time()
   if now-self.cd[uid][cmd]<t:return False,t-(now-self.cd[uid][cmd])
   self.cd[uid][cmd]=now;return True,0
rl=RateLimiter()
@dataclass
class Msg:role:str;content:str;ts:float
class Memory:
 def __init__(self):self.data=defaultdict(list);self.lock=threading.Lock()
 def add(self,uid,role,c):
  with self.lock:
   now=time.time();self.data[uid]=[m for m in self.data[uid]if now-m.ts<1800]
   self.data[uid].append(Msg(role,c[:1500],now))
   if len(self.data[uid])>15:self.data[uid]=self.data[uid][-15:]
 def get(self,uid):
  with self.lock:now=time.time();self.data[uid]=[m for m in self.data[uid]if now-m.ts<1800];return[{"role":m.role,"content":m.content}for m in self.data[uid]]
 def clear(self,uid):
  with self.lock:self.data[uid]=[]
mem=Memory()
SYSTEM_PROMPT='Kamu adalah AI Assistant yang helpful dan friendly. Jawab dalam Bahasa Indonesia kecuali diminta lain. Berikan jawaban yang informatif dan akurat.'
OR_MODELS={"or_llama":"meta-llama/llama-3.3-70b-instruct:free","or_gemini":"google/gemini-2.0-flash-thinking-exp:free","or_qwen":"qwen/qwen-2.5-coder-32b-instruct:free","or_deepseek":"deepseek/deepseek-r1:free","or_mistral":"mistralai/mistral-small-24b-instruct-2501:free"}
POLL_TEXT={"gpt5":"openai","gpt5_large":"openai-large","claude":"claude","claude_large":"claude-large","gemini3":"gemini","gemini3_large":"gemini-large","deepseek":"deepseek","grok":"grok","perplexity":"perplexity-fast","perplexity_r":"perplexity-reasoning","qwen_code":"qwen-coder","mistral":"mistral","minimax":"minimax","kimi":"kimi"}
POLL_IMG={"flux":"flux","sdxl":"turbo","gpt_img":"gptimage","dream":"seedream","context":"kontext"}
MODEL_INFO={
 "auto":("🚀","Auto (Smart Fallback)","Otomatis pilih AI tercepat"),
 "groq":("⚡","Groq","Llama 3.3 70B - Sangat cepat"),
 "cerebras":("🧠","Cerebras","Llama 3.3 70B - Fast inference"),
 "cohere":("🔷","Cohere","Command R+ - Native API"),
 "cloudflare":("☁️","Cloudflare","Llama 3.3 70B - Workers AI"),
 "sambanova":("🦣","SambaNova","Llama 3.3 70B - Enterprise"),
 "together":("🤝","Together","Llama 3.3 70B Turbo"),
 "poll_free":("🌸","Pollinations Free","Gratis tanpa key"),
 "gpt5":("🤖","GPT-5 Mini","OpenAI via Pollinations"),
 "gpt5_large":("🧠","GPT-5.2","OpenAI Large - Premium"),
 "claude":("🎭","Claude 4.5","Anthropic Sonnet"),
 "claude_large":("👑","Claude Opus","Anthropic Premium"),
 "gemini3":("💎","Gemini 3 Flash","Google via Pollinations"),
 "deepseek":("🐳","DeepSeek V3","Reasoning model"),
 "grok":("❌","Grok 4","xAI via Pollinations"),
 "perplexity":("🔍","Perplexity","Search-enabled AI"),
 "or_gemini":("🔵","Gemini 2.0","OpenRouter Free"),
 "or_llama":("🦙","Llama 3.3","OpenRouter Free"),
 "or_qwen":("💻","Qwen Coder","OpenRouter Free"),
 "or_deepseek":("🌊","DeepSeek R1","OpenRouter Free")
}
IMG_INFO={
 "flux":("🎨","Flux","Fast & high quality"),
 "sdxl":("⚡","SDXL Turbo","Very fast"),
 "gpt_img":("🤖","GPT Image","OpenAI quality"),
 "dream":("🌌","Seedream","Artistic style"),
 "context":("🔄","Kontext","Context-aware")
}
def call_groq(msgs):
 g=get_groq()
 if not g:return None
 try:r=g.chat.completions.create(messages=msgs,model="llama-3.3-70b-versatile",temperature=0.7,max_tokens=2000);return r.choices[0].message.content
 except Exception as e:logger.error(f"Groq:{e}");return None
def call_cerebras(msgs):
 if not KEY_CEREBRAS:return None
 try:
  r=get_requests().post("https://api.cerebras.ai/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_CEREBRAS}","Content-Type":"application/json"},json={"model":"llama-3.3-70b","messages":msgs,"temperature":0.7,"max_tokens":2000},timeout=25)
  return r.json()["choices"][0]["message"]["content"]if r.status_code==200 else None
 except Exception as e:logger.error(f"Cerebras:{e}");return None
def call_cohere(msgs):
 if not KEY_COHERE:return None
 try:
  sys_p,hist,user_msg="",[],"Hello"
  for m in msgs:
   if m["role"]=="system":sys_p=m["content"]
   elif m["role"]=="user":user_msg=m["content"]
   else:hist.append({"role":"USER"if m["role"]=="user"else"CHATBOT","message":m["content"]})
  for m in msgs[:-1]:
   if m["role"]in["user","assistant"]:hist.append({"role":"USER"if m["role"]=="user"else"CHATBOT","message":m["content"]})
  user_msg=msgs[-1]["content"]if msgs else"Hi"
  d={"model":"command-r-plus","message":user_msg,"temperature":0.7}
  if sys_p:d["preamble"]=sys_p
  if hist:d["chat_history"]=hist[-10:]
  r=get_requests().post("https://api.cohere.com/v2/chat",headers={"Authorization":f"Bearer {KEY_COHERE}","Content-Type":"application/json"},json=d,timeout=45)
  return r.json().get("text")if r.status_code==200 else None
 except Exception as e:logger.error(f"Cohere:{e}");return None
def call_cloudflare(msgs):
 if not CF_ACCOUNT_ID or not CF_API_TOKEN:return None
 try:
  r=get_requests().post(f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/@cf/meta/llama-3.3-70b-instruct-fp8-fast",headers={"Authorization":f"Bearer {CF_API_TOKEN}","Content-Type":"application/json"},json={"messages":msgs,"max_tokens":2000},timeout=45)
  if r.status_code==200:
   d=r.json()
   if d.get("success"):return d["result"]["response"].strip()
  return None
 except Exception as e:logger.error(f"CF:{e}");return None
def call_sambanova(msgs):
 if not KEY_SAMBANOVA:return None
 try:
  r=get_requests().post("https://api.sambanova.ai/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_SAMBANOVA}","Content-Type":"application/json"},json={"model":"Meta-Llama-3.3-70B-Instruct","messages":msgs,"temperature":0.7,"max_tokens":2000},timeout=45)
  return r.json()["choices"][0]["message"]["content"]if r.status_code==200 else None
 except Exception as e:logger.error(f"SN:{e}");return None
def call_together(msgs):
 if not KEY_TOGETHER:return None
 try:
  r=get_requests().post("https://api.together.xyz/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_TOGETHER}","Content-Type":"application/json"},json={"model":"meta-llama/Llama-3.3-70B-Instruct-Turbo","messages":msgs,"temperature":0.7,"max_tokens":2000},timeout=45)
  return r.json()["choices"][0]["message"]["content"]if r.status_code==200 else None
 except Exception as e:logger.error(f"Together:{e}");return None
def call_openrouter(msgs,model_key):
 if not KEY_OPENROUTER:return None
 try:
  mid=OR_MODELS.get(model_key,OR_MODELS["or_llama"])
  r=get_requests().post("https://openrouter.ai/api/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_OPENROUTER}","Content-Type":"application/json","HTTP-Referer":"https://github.com"},json={"model":mid,"messages":msgs,"temperature":0.7,"max_tokens":2000},timeout=60)
  if r.status_code==200:
   d=r.json()
   if"choices"in d and d["choices"]:return d["choices"][0]["message"]["content"]
  return None
 except Exception as e:logger.error(f"OR:{e}");return None
def call_poll_free(prompt):
 try:
  r=get_requests().get(f"https://text.pollinations.ai/{quote(prompt)}",timeout=45)
  return r.text.strip()if r.status_code==200 and r.text.strip()else None
 except Exception as e:logger.error(f"PollFree:{e}");return None
def call_poll_api(msgs,model_key):
 if not KEY_POLLINATIONS:return None
 try:
  mid=POLL_TEXT.get(model_key,model_key)
  r=get_requests().post("https://text.pollinations.ai/",headers={"Authorization":f"Bearer {KEY_POLLINATIONS}","Content-Type":"application/json"},json={"messages":msgs,"model":mid,"jsonMode":False},timeout=60)
  return r.text.strip()if r.status_code==200 else None
 except Exception as e:logger.error(f"PollAPI:{e}");return None
def call_ai(model,msgs,prompt=""):
 if model=="groq":return call_groq(msgs),"Groq"
 elif model=="cerebras":return call_cerebras(msgs),"Cerebras"
 elif model=="cohere":return call_cohere(msgs),"Cohere"
 elif model=="cloudflare":return call_cloudflare(msgs),"Cloudflare"
 elif model=="sambanova":return call_sambanova(msgs),"SambaNova"
 elif model=="together":return call_together(msgs),"Together"
 elif model=="poll_free":return call_poll_free(prompt),"Poll(Free)"
 elif model.startswith("or_"):return call_openrouter(msgs,model),f"OR({model[3:]})"
 elif model in POLL_TEXT:return call_poll_api(msgs,model),f"Poll({model})"
 return None,"none"
def ask_ai(prompt,uid=None,model=None):
 user_model=db.get_model(uid)if uid else"auto"
 sel=model if model and model!="auto"else(user_model if user_model!="auto"else"auto")
 msgs=[{"role":"system","content":SYSTEM_PROMPT}]
 if uid:
  h=mem.get(uid)
  if h:msgs.extend(h[-6:])
 msgs.append({"role":"user","content":prompt})
 result,used=None,"none"
 if sel!="auto":
  result,used=call_ai(sel,msgs,prompt)
  if not result:sel="auto"
 if sel=="auto"or not result:
  free_providers=[
   (lambda:call_groq(msgs),"Groq",bool(get_groq())),
   (lambda:call_cohere(msgs),"Cohere",bool(KEY_COHERE)),
   (lambda:call_cerebras(msgs),"Cerebras",bool(KEY_CEREBRAS)),
   (lambda:call_cloudflare(msgs),"CF",bool(CF_API_TOKEN)),
   (lambda:call_sambanova(msgs),"SN",bool(KEY_SAMBANOVA)),
   (lambda:call_together(msgs),"Together",bool(KEY_TOGETHER)),
   (lambda:call_openrouter(msgs,"or_gemini"),"OR(Gemini)",bool(KEY_OPENROUTER)),
   (lambda:call_poll_free(prompt),"Poll(Free)",True)
  ]
  available=[p for p in free_providers if p[2]]
  random.shuffle(available)
  for fn,name,_ in available:
   try:
    r=fn()
    if r:result=r;used=name;break
   except:continue
 if not result:return"❌ Semua AI sedang sibuk. Coba lagi nanti.","none"
 if uid:
  mem.add(uid,"user",prompt[:500])
  mem.add(uid,"assistant",result[:500])
 return result,used
async def gen_image(prompt,model="flux"):
 if not KEY_POLLINATIONS:return None,"API Key required"
 try:
  mid=POLL_IMG.get(model,"flux")
  url=f"https://image.pollinations.ai/prompt/{quote(prompt)}?model={mid}&nologo=true&width=1024&height=1024"
  r=get_requests().get(url,headers={"Authorization":f"Bearer {KEY_POLLINATIONS}"},timeout=90)
  if r.status_code==200:return r.content,None
  return None,f"HTTP {r.status_code}"
 except Exception as e:return None,str(e)
class ModelSelect(ui.Select):
 def __init__(self):
  opts=[]
  for k,v in MODEL_INFO.items():
   if k in["auto","groq","cohere","cerebras","cloudflare","poll_free","gpt5","claude","gemini3","deepseek","or_gemini","or_llama"]:
    opts.append(discord.SelectOption(label=v[1],value=k,emoji=v[0],description=v[2][:50]))
  super().__init__(placeholder="🤖 Pilih Model AI...",min_values=1,max_values=1,options=opts[:25])
 async def callback(self,itr:discord.Interaction):
  v=self.values[0];db.set_model(itr.user.id,v)
  info=MODEL_INFO.get(v,("","Unknown",""))
  await itr.response.send_message(f"✅ Model diubah ke: {info[0]} **{info[1]}**\n_{info[2]}_",ephemeral=True)
class ModelView(ui.View):
 def __init__(self):super().__init__(timeout=120);self.add_item(ModelSelect())
class ImgModelSelect(ui.Select):
 def __init__(self):
  opts=[discord.SelectOption(label=v[1],value=k,emoji=v[0],description=v[2])for k,v in IMG_INFO.items()]
  super().__init__(placeholder="🎨 Pilih Model Gambar...",min_values=1,max_values=1,options=opts)
 async def callback(self,itr:discord.Interaction):
  v=self.values[0];db.set_img_model(itr.user.id,v)
  info=IMG_INFO.get(v,("","Unknown",""))
  await itr.response.send_message(f"✅ Image model: {info[0]} **{info[1]}**",ephemeral=True)
class ImgModelView(ui.View):
 def __init__(self):super().__init__(timeout=120);self.add_item(ImgModelSelect())
class ShieldSelect(ui.Select):
 def __init__(self):
  opts=[
   discord.SelectOption(label="Stats",value="stats",emoji="📊",description="View server statistics"),
   discord.SelectOption(label="Sessions",value="sessions",emoji="🔄",description="View active sessions"),
   discord.SelectOption(label="Logs",value="logs",emoji="📋",description="View recent logs"),
   discord.SelectOption(label="Bans",value="bans",emoji="🚫",description="View ban list"),
   discord.SelectOption(label="Whitelist",value="whitelist",emoji="📋",description="View whitelist"),
   discord.SelectOption(label="Suspended",value="suspended",emoji="⏸️",description="View suspensions"),
   discord.SelectOption(label="Get Script",value="script",emoji="📜",description="Download protected script"),
   discord.SelectOption(label="KeepAlive",value="keepalive",emoji="⚡",description="Check server health"),
   discord.SelectOption(label="Clear Sessions",value="clear_sess",emoji="🧹",description="Clear all sessions"),
   discord.SelectOption(label="Clear Logs",value="clear_logs",emoji="🗑️",description="Clear all logs"),
   discord.SelectOption(label="Clear Cache",value="clear_cache",emoji="💾",description="Clear script cache")
  ]
  super().__init__(placeholder="🛡️ Shield Actions...",min_values=1,max_values=1,options=opts)
 async def callback(self,itr:discord.Interaction):
  if itr.user.id not in OWNER_IDS:return await itr.response.send_message("❌ Owner only",ephemeral=True)
  v=self.values[0];await itr.response.defer(ephemeral=True)
  if v=="stats":
   r=shield.stats()
   if r.get("success"):
    s=r.get("stats",{});ka=r.get("keepAlive",{})
    e=discord.Embed(title="📊 Shield Stats",color=0x00FF00)
    e.add_field(name="Executions",value=f"`{s.get('totalExecutions',0)}`",inline=True)
    e.add_field(name="Bans",value=f"`{s.get('totalBans',0)}`",inline=True)
    e.add_field(name="Sessions",value=f"`{r.get('sessions',0)}`",inline=True)
    e.add_field(name="KeepAlive Pings",value=f"`{ka.get('count',0)}`",inline=True)
    e.add_field(name="Last Ping",value=f"`{str(ka.get('lastPing','N/A'))[:19]}`",inline=True)
    await itr.followup.send(embed=e,ephemeral=True)
   else:await itr.followup.send(f"❌ {r.get('error')}",ephemeral=True)
  elif v=="sessions":
   r=shield.sessions()
   if r.get("success"):
    sess=r.get("sessions",[])
    if not sess:await itr.followup.send("📭 No active sessions",ephemeral=True)
    else:
     e=discord.Embed(title=f"🔄 Sessions ({len(sess)})",color=0x3498DB)
     for s in sess[:10]:e.add_field(name=f"🔹 {str(s.get('sessionId',''))[:8]}...",value=f"User:`{s.get('userId')}` Age:`{s.get('age',0)}s`",inline=True)
     await itr.followup.send(embed=e,ephemeral=True)
   else:await itr.followup.send(f"❌ {r.get('error')}",ephemeral=True)
  elif v=="logs":
   r=shield.logs()
   if r.get("success"):
    logs=r.get("logs",[])[:15]
    txt="\n".join([f"{'✅'if l.get('success')else'❌'} `{l.get('action','')}` {str(l.get('ts',''))[:10]}"for l in logs])or"No logs"
    await itr.followup.send(f"📋 **Recent Logs:**\n{txt}",ephemeral=True)
   else:await itr.followup.send(f"❌ {r.get('error')}",ephemeral=True)
  elif v=="bans":
   r=shield.bans()
   if r.get("success"):
    bans=r.get("bans",[])
    if not bans:await itr.followup.send("📭 No bans",ephemeral=True)
    else:
     txt="\n".join([f"`{b.get('banId','')}` - {str(b.get('hwid','') or b.get('playerId','') or b.get('ip',''))[:15]}... ({b.get('reason','')[:20]})"for b in bans[:15]])
     await itr.followup.send(f"🚫 **Bans ({len(bans)}):**\n{txt}",ephemeral=True)
   else:await itr.followup.send(f"❌ {r.get('error')}",ephemeral=True)
  elif v=="whitelist":
   r=shield.whitelist()
   if r.get("success"):
    wl=r.get("whitelist",{})
    e=discord.Embed(title="📋 Whitelist",color=0x00FF00)
    e.add_field(name=f"Users ({len(wl.get('userIds',[]))})",value=", ".join([f"`{x}`"for x in wl.get('userIds',[])[:10]])or"None",inline=False)
    e.add_field(name=f"HWIDs ({len(wl.get('hwids',[]))})",value=", ".join([f"`{str(x)[:8]}...`"for x in wl.get('hwids',[])[:5]])or"None",inline=False)
    e.add_field(name=f"Owners ({len(wl.get('owners',[]))})",value=", ".join([f"`{x}`"for x in wl.get('owners',[])])or"None",inline=False)
    await itr.followup.send(embed=e,ephemeral=True)
   else:await itr.followup.send(f"❌ {r.get('error')}",ephemeral=True)
  elif v=="suspended":
   r=shield.suspended()
   if r.get("success"):
    susp=r.get("suspended",[])
    if not susp:await itr.followup.send("📭 No suspensions",ephemeral=True)
    else:
     txt="\n".join([f"`{s.get('type')}:{str(s.get('value',''))[:15]}` - {s.get('reason','')[:25]}"for s in susp[:10]])
     await itr.followup.send(f"⏸️ **Suspensions ({len(susp)}):**\n{txt}",ephemeral=True)
   else:await itr.followup.send(f"❌ {r.get('error')}",ephemeral=True)
  elif v=="script":
   r=shield.script()
   if r.get("success"):
    sc=r.get("script","")
    await itr.followup.send(f"📜 Script size: `{len(sc):,}` bytes",file=discord.File(io.BytesIO(sc.encode()),"protected_script.lua"),ephemeral=True)
   else:await itr.followup.send(f"❌ {r.get('error')}",ephemeral=True)
  elif v=="keepalive":
   r=shield.keepalive()
   if r.get("status")=="alive":
    st=r.get("stats",{})
    await itr.followup.send(f"✅ **Server Online**\nUptime: `{st.get('uptimeFormatted','?')}`\nMemory: `{st.get('memory','?')}`\nSessions: `{st.get('sessions',0)}`\nPings: `{st.get('pingCount',0)}`",ephemeral=True)
   else:await itr.followup.send(f"❌ Offline: {r.get('error')}",ephemeral=True)
  elif v=="clear_sess":r=shield.clear_sessions();await itr.followup.send(f"{'✅ Cleared '+str(r.get('cleared',0))+' sessions'if r.get('success')else'❌ '+r.get('error','')}",ephemeral=True)
  elif v=="clear_logs":r=shield.clear_logs();await itr.followup.send(f"{'✅ Logs cleared'if r.get('success')else'❌ '+r.get('error','')}",ephemeral=True)
  elif v=="clear_cache":r=shield.clear_cache();await itr.followup.send(f"{'✅ Cache cleared'if r.get('success')else'❌ '+r.get('error','')}",ephemeral=True)
class ShieldView(ui.View):
 def __init__(self):super().__init__(timeout=180);self.add_item(ShieldSelect())
class ShieldManageSelect(ui.Select):
 def __init__(self):
  opts=[
   discord.SelectOption(label="Ban User",value="ban_user",emoji="🚫"),
   discord.SelectOption(label="Ban HWID",value="ban_hwid",emoji="🔑"),
   discord.SelectOption(label="Ban IP",value="ban_ip",emoji="🌐"),
   discord.SelectOption(label="Unban by ID",value="unban",emoji="✅"),
   discord.SelectOption(label="Add Whitelist",value="wl_add",emoji="➕"),
   discord.SelectOption(label="Remove Whitelist",value="wl_rem",emoji="➖"),
   discord.SelectOption(label="Suspend User",value="suspend",emoji="⏸️"),
   discord.SelectOption(label="Unsuspend",value="unsuspend",emoji="▶️"),
   discord.SelectOption(label="Kill Session",value="kill",emoji="💀")
  ]
  super().__init__(placeholder="⚙️ Manage Actions...",min_values=1,max_values=1,options=opts)
 async def callback(self,itr:discord.Interaction):
  if itr.user.id not in OWNER_IDS:return await itr.response.send_message("❌ Owner only",ephemeral=True)
  v=self.values[0]
  class InputModal(ui.Modal,title=f"Shield: {v}"):
   inp=ui.TextInput(label="Value",placeholder="Enter value...",required=True)
   reason=ui.TextInput(label="Reason (optional)",placeholder="Reason...",required=False,default="Via Discord")
   def __init__(self,action):super().__init__();self.action=action
   async def on_submit(self,interaction:discord.Interaction):
    val=self.inp.value;rsn=self.reason.value or"Via Discord"
    if self.action=="ban_user":r=shield.add_ban(pid=val,reason=rsn)
    elif self.action=="ban_hwid":r=shield.add_ban(hwid=val,reason=rsn)
    elif self.action=="ban_ip":r=shield.add_ban(ip=val,reason=rsn)
    elif self.action=="unban":r=shield.remove_ban(val)
    elif self.action=="wl_add":
     parts=val.split(":",1);t=parts[0]if len(parts)>1 else"userId";v2=parts[1]if len(parts)>1 else val
     r=shield.add_wl(t,v2)
    elif self.action=="wl_rem":
     parts=val.split(":",1);t=parts[0]if len(parts)>1 else"userId";v2=parts[1]if len(parts)>1 else val
     r=shield.remove_wl(t,v2)
    elif self.action=="suspend":
     parts=val.split(":",1);t=parts[0]if len(parts)>1 else"userId";v2=parts[1]if len(parts)>1 else val
     r=shield.suspend(t,v2,rsn)
    elif self.action=="unsuspend":
     parts=val.split(":",1);t=parts[0]if len(parts)>1 else"userId";v2=parts[1]if len(parts)>1 else val
     r=shield.unsuspend(t,v2)
    elif self.action=="kill":r=shield.kill(val,rsn)
    else:r={"success":False,"error":"Unknown action"}
    await interaction.response.send_message(f"{'✅ Success: '+str(r.get('msg',r.get('banId','')))if r.get('success')else'❌ Error: '+r.get('error','')}",ephemeral=True)
  await itr.response.send_modal(InputModal(v))
class ShieldManageView(ui.View):
 def __init__(self):super().__init__(timeout=180);self.add_item(ShieldManageSelect())
class AdvancedDumper:
 def __init__(self):self.last=None
 def dump(self,url,use_cache=True):
  if use_cache:
   c=db.get_cache(url)
   if c:return{"success":True,"content":c,"method":"cache","cached":True}
  req=get_requests();curl=get_curl();cs=get_cloudscraper()
  methods=[]
  if curl:methods.append(("curl",lambda u:curl.get(u,impersonate="chrome120",headers={"User-Agent":"Roblox/WinInet"},timeout=25)))
  if cs:methods.append(("cloudscraper",lambda u:cs.get(u,timeout=25)))
  if req:methods.append(("requests",lambda u:req.get(u,headers={"User-Agent":"Roblox/WinInet","Accept":"*/*"},timeout=25)))
  if self.last:methods.sort(key=lambda x:x[0]!=self.last)
  errors=[]
  for n,f in methods:
   try:
    r=f(url)
    if r.status_code==200 and len(r.text)>10:
     self.last=n
     if use_cache:db.cache_dump(url,r.text)
     return{"success":True,"content":r.text,"method":n,"cached":False}
    errors.append(f"{n}:{r.status_code}")
   except Exception as e:errors.append(f"{n}:{str(e)[:20]}")
  return{"success":False,"error":"All methods failed","details":errors}
dumper=AdvancedDumper()
def split_msg(t,lim=1900):return[t[i:i+lim]for i in range(0,len(t),lim)]if t else["(empty)"]
async def send_ai(ch,u,c,used):
 chunks=split_msg(c)
 for i,chunk in enumerate(chunks):
  e=discord.Embed(description=chunk,color=0x5865F2)
  if i==len(chunks)-1:e.set_footer(text=f"🤖 {used} | {u.display_name}")
  await ch.send(embed=e)
def fmt_ts(ts):return str(ts)[:19].replace("T"," ")if ts else"N/A"
@bot.event
async def on_ready():
 logger.info(f'🔥 {bot.user} | {len(bot.guilds)} servers')
 await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening,name=f"{PREFIX}help"))
@bot.event
async def on_command_error(ctx,error):
 if isinstance(error,commands.CommandNotFound):return
 logger.error(f"Cmd error:{error}")
@bot.event
async def on_message(msg):
 if msg.author.bot:return
 if bot.user.mentioned_in(msg)and not msg.mention_everyone:
  c=msg.content.replace(f'<@{bot.user.id}>','').replace(f'<@!{bot.user.id}>','').strip()
  if c:
   if db.banned(msg.author.id):return
   ok,rem=rl.check(msg.author.id,"ai",5)
   if not ok:return await msg.channel.send(f"⏳ Tunggu {rem:.0f}s",delete_after=5)
   async with msg.channel.typing():
    r,u=ask_ai(c,msg.author.id)
    await send_ai(msg.channel,msg.author,r,u)
    db.stat("ai",msg.author.id)
  else:
   m=db.get_model(msg.author.id)
   info=MODEL_INFO.get(m,("","Unknown",""))
   await msg.channel.send(f"👋 {msg.author.mention}\nModel: {info[0]} **{info[1]}**\nKetik pertanyaan setelah mention!",delete_after=10)
  return
 await bot.process_commands(msg)
@bot.command(name="ai",aliases=["ask","a","tanya"])
async def cmd_ai(ctx,*,prompt:str=None):
 if db.banned(ctx.author.id):return
 if not prompt:return await ctx.send(f"❌ `{PREFIX}ai <pertanyaan>`")
 ok,rem=rl.check(ctx.author.id,"ai",5)
 if not ok:return await ctx.send(f"⏳ Tunggu {rem:.0f}s",delete_after=5)
 async with ctx.typing():
  r,u=ask_ai(prompt,ctx.author.id)
  await send_ai(ctx.channel,ctx.author,r,u)
  db.stat("ai",ctx.author.id)
@bot.command(name="model",aliases=["m"])
async def cmd_model(ctx):
 cur=db.get_model(ctx.author.id)
 info=MODEL_INFO.get(cur,("","Unknown",""))
 e=discord.Embed(title="🤖 AI Model Selection",description=f"Current: {info[0]} **{info[1]}**\n_{info[2]}_",color=0x5865F2)
 await ctx.send(embed=e,view=ModelView())
@bot.command(name="imagine",aliases=["img","draw","gen"])
async def cmd_imagine(ctx,*,prompt:str=None):
 if db.banned(ctx.author.id):return
 if not KEY_POLLINATIONS:return await ctx.send("❌ `POLLINATIONS_API_KEY` not configured")
 if not prompt:return await ctx.send(f"❌ `{PREFIX}imagine <prompt>`\nContoh: `{PREFIX}imagine kucing astronot di bulan`")
 ok,rem=rl.check(ctx.author.id,"img",15)
 if not ok:return await ctx.send(f"⏳ Tunggu {rem:.0f}s",delete_after=5)
 model=db.get_img_model(ctx.author.id)
 minfo=IMG_INFO.get(model,("🎨","flux",""))
 msg=await ctx.send(f"🎨 **Generating** dengan {minfo[0]} `{minfo[1]}`...\n_{prompt[:100]}_")
 try:
  img_data,err=await gen_image(prompt,model)
  if img_data:
   fn=f"gen_{hashlib.md5(prompt.encode()).hexdigest()[:8]}.png"
   await ctx.send(f"{minfo[0]} **{prompt[:100]}**",file=discord.File(io.BytesIO(img_data),fn))
   await msg.delete()
   db.stat("imagine",ctx.author.id)
  else:await msg.edit(content=f"❌ Error: {err}")
 except Exception as e:await msg.edit(content=f"❌ Error: {str(e)[:100]}")
@bot.command(name="imgmodel",aliases=["im"])
async def cmd_imgmodel(ctx):
 cur=db.get_img_model(ctx.author.id)
 info=IMG_INFO.get(cur,("","Unknown",""))
 e=discord.Embed(title="🎨 Image Model Selection",description=f"Current: {info[0]} **{info[1]}**\n_{info[2]}_",color=0xE91E63)
 await ctx.send(embed=e,view=ImgModelView())
@bot.command(name="shield",aliases=["sh","s"])
async def cmd_shield(ctx):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only")
 e=discord.Embed(title="🛡️ Shield Admin Panel",color=0x5865F2)
 e.description=f"**Server:** `{SHIELD_URL or 'Not configured'}`"
 e.add_field(name="📊 Info",value="View stats, sessions, logs, bans, whitelist",inline=False)
 e.add_field(name="⚙️ Manage",value=f"Use `{PREFIX}shieldm` for management actions",inline=False)
 await ctx.send(embed=e,view=ShieldView())
@bot.command(name="shieldm",aliases=["sm"])
async def cmd_shieldm(ctx):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only")
 e=discord.Embed(title="⚙️ Shield Management",description="Select an action below.\n\n**Format:**\n• Ban: Enter value directly\n• Whitelist/Suspend: `type:value` (e.g., `userId:123456`)",color=0xFF6B6B)
 await ctx.send(embed=e,view=ShieldManageView())
@bot.command(name="dump",aliases=["dl","get"])
async def cmd_dump(ctx,url:str=None,*,flags:str=""):
 if db.banned(ctx.author.id):return
 if not url:return await ctx.send(f"❌ `{PREFIX}dump <url>`")
 ok,rem=rl.check(ctx.author.id,"dump",10)
 if not ok:return await ctx.send(f"⏳ Tunggu {rem:.0f}s",delete_after=5)
 if not url.startswith(("http://","https://")):url="https://"+url
 use_cache="--nocache"not in flags.lower()
 msg=await ctx.send("🔄 **Dumping...**")
 try:
  r=dumper.dump(url,use_cache)
  if r["success"]:
   c=r["content"]
   ext="lua"
   if"<!DOCTYPE"in c[:300].upper()or"<html"in c[:200].lower():ext="html"
   elif c.strip().startswith("{")or c.strip().startswith("["):ext="json"
   elif"local "in c[:500]or"function"in c[:500]:ext="lua"
   size=len(c);sz_str=f"{size:,}b"if size<1024 else f"{size/1024:.1f}KB"
   e=discord.Embed(title="✅ Dump Success",color=0x00FF00)
   e.add_field(name="Size",value=f"`{sz_str}`",inline=True)
   e.add_field(name="Type",value=f"`.{ext}`",inline=True)
   e.add_field(name="Method",value=f"`{r['method']}`",inline=True)
   e.add_field(name="Cached",value=f"`{'Yes'if r.get('cached')else'No'}`",inline=True)
   fn=f"dump_{hashlib.md5(url.encode()).hexdigest()[:8]}.{ext}"
   await ctx.send(embed=e,file=discord.File(io.BytesIO(c.encode('utf-8',errors='replace')),fn))
   await msg.delete()
   db.stat("dump",ctx.author.id)
  else:
   e=discord.Embed(title="❌ Dump Failed",description=f"Error: `{r.get('error')}`",color=0xFF0000)
   if r.get("details"):e.add_field(name="Details",value=f"```{chr(10).join(r['details'][:3])}```")
   await msg.edit(content=None,embed=e)
 except Exception as ex:await msg.edit(content=f"❌ Error: `{str(ex)[:100]}`")
@bot.command(name="clear",aliases=["reset"])
async def cmd_clear(ctx):
 mem.clear(ctx.author.id)
 await ctx.send(f"🧹 {ctx.author.mention} Memory cleared!",delete_after=5)
@bot.command(name="ping",aliases=["p"])
async def cmd_ping(ctx):
 m=db.get_model(ctx.author.id)
 info=MODEL_INFO.get(m,("","?",""))
 e=discord.Embed(title="🏓 Pong!",color=0x00FF00)
 e.add_field(name="Latency",value=f"`{round(bot.latency*1000)}ms`",inline=True)
 e.add_field(name="Model",value=f"{info[0]} `{info[1]}`",inline=True)
 e.add_field(name="Shield",value=f"`{'✅'if SHIELD_URL else'❌'}`",inline=True)
 e.add_field(name="Pollinations",value=f"`{'✅'if KEY_POLLINATIONS else'❌'}`",inline=True)
 await ctx.send(embed=e)
@bot.command(name="help",aliases=["h"])
async def cmd_help(ctx):
 e=discord.Embed(title="📚 Bot Help",color=0x5865F2)
 e.add_field(name="🤖 AI Chat",value=f"`{PREFIX}ai <text>` - Tanya AI\n`@bot <text>` - Mention untuk chat\n`{PREFIX}model` - Pilih model AI",inline=False)
 e.add_field(name="🎨 Image Gen",value=f"`{PREFIX}imagine <prompt>` - Generate gambar\n`{PREFIX}imgmodel` - Pilih model gambar",inline=False)
 e.add_field(name="🔧 Tools",value=f"`{PREFIX}dump <url>` - Dump URL\n`{PREFIX}clear` - Clear memory\n`{PREFIX}ping` - Check status",inline=False)
 e.add_field(name="🛡️ Shield (Owner)",value=f"`{PREFIX}shield` - Admin panel\n`{PREFIX}shieldm` - Management",inline=False)
 e.add_field(name="👑 Admin (Owner)",value=f"`{PREFIX}testai` - Test providers\n`{PREFIX}blacklist` - Manage users",inline=False)
 await ctx.send(embed=e)
@bot.command(name="testai")
async def cmd_testai(ctx):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only")
 msg=await ctx.send("🔄 Testing AI providers...")
 results=[]
 test_msgs=[{"role":"user","content":"Say 'OK' only"}]
 providers=[
  ("Groq",lambda:call_groq(test_msgs),bool(get_groq())),
  ("Cohere",lambda:call_cohere(test_msgs),bool(KEY_COHERE)),
  ("Cerebras",lambda:call_cerebras(test_msgs),bool(KEY_CEREBRAS)),
  ("Cloudflare",lambda:call_cloudflare(test_msgs),bool(CF_API_TOKEN)),
  ("SambaNova",lambda:call_sambanova(test_msgs),bool(KEY_SAMBANOVA)),
  ("Together",lambda:call_together(test_msgs),bool(KEY_TOGETHER)),
  ("OR-Gemini",lambda:call_openrouter(test_msgs,"or_gemini"),bool(KEY_OPENROUTER)),
  ("Poll-Free",lambda:call_poll_free("Say OK"),True),
  ("Poll-API",lambda:call_poll_api(test_msgs,"gpt5"),bool(KEY_POLLINATIONS))
 ]
 for name,fn,available in providers:
  if not available:results.append(f"⚪ **{name}**: Not configured");continue
  try:
   r=fn()
   if r:results.append(f"✅ **{name}**: `{r[:20]}...`")
   else:results.append(f"❌ **{name}**: No response")
  except Exception as ex:results.append(f"❌ **{name}**: `{str(ex)[:20]}`")
 e=discord.Embed(title="🔧 AI Provider Status",description="\n".join(results),color=0x3498DB)
 await msg.edit(content=None,embed=e)
@bot.command(name="teststats")
async def cmd_teststats(ctx):
 if ctx.author.id not in OWNER_IDS:return
 stats=db.get_stats()
 txt="\n".join([f"`{s[0]}`: {s[1]}"for s in stats])or"No stats"
 await ctx.send(f"📊 **Command Stats:**\n{txt}")
@bot.command(name="blacklist",aliases=["bl"])
async def cmd_blacklist(ctx,action:str=None,user:discord.User=None):
 if ctx.author.id not in OWNER_IDS:return
 if not action or not user:return await ctx.send(f"❌ `{PREFIX}blacklist <add/remove> @user`")
 if action.lower()in["add","ban"]:db.add_bl(user.id);await ctx.send(f"✅ {user.mention} blacklisted")
 elif action.lower()in["remove","unban","rem"]:db.rem_bl(user.id);await ctx.send(f"✅ {user.mention} removed from blacklist")
if __name__=="__main__":
 keep_alive()
 print("="*50)
 print("🚀 Full Feature Bot Starting...")
 print(f"📦 Prefix: {PREFIX}")
 print(f"👑 Owners: {OWNER_IDS}")
 print(f"🛡️ Shield: {'✅ '+SHIELD_URL[:30]+'...'if SHIELD_URL else'❌ Not configured'}")
 print("🔑 API Keys:")
 keys=[("Groq",KEY_GROQ),("Cohere",KEY_COHERE),("Cerebras",KEY_CEREBRAS),("Cloudflare",CF_API_TOKEN),("SambaNova",KEY_SAMBANOVA),("Together",KEY_TOGETHER),("OpenRouter",KEY_OPENROUTER),("Pollinations",KEY_POLLINATIONS)]
 for n,k in keys:print(f"   {n}: {'✅'if k else'❌'}")
 print("🔧 Libraries:")
 print(f"   curl_cffi: {'✅'if get_curl()else'❌'}")
 print(f"   cloudscraper: {'✅'if get_cloudscraper()else'❌'}")
 print("="*50)
 bot.run(DISCORD_TOKEN,log_handler=None)
