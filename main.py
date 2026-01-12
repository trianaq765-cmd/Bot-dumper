import discord,os,io,re,time,json,logging,sqlite3,random,threading,hashlib,base64,asyncio
from collections import defaultdict
from dataclasses import dataclass
from discord.ext import commands
from urllib.parse import urlparse,urljoin
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
SHIELD_URL=os.getenv("SHIELD_URL","").rstrip("/")
SHIELD_ADMIN_KEY=os.getenv("SHIELD_ADMIN_KEY","")
OWNER_IDS=[int(x)for x in os.getenv("OWNER_IDS","0").split(",")if x.isdigit()]
PREFIX=os.getenv("BOT_PREFIX",".")
if not DISCORD_TOKEN:print("❌ DISCORD_TOKEN not found!");exit(1)
intents=discord.Intents.default()
intents.message_content=True
bot=commands.Bot(command_prefix=PREFIX,intents=intents,help_command=None)
_groq=_requests=_curl=_cloudscraper=None
def get_groq():
 global _groq
 if _groq is None and KEY_GROQ:from groq import Groq;_groq=Groq(api_key=KEY_GROQ)
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
 def __init__(self,url,key):self.url=url;self.key=key;self.timeout=30
 def _headers(self):return{"x-admin-key":self.key,"Content-Type":"application/json"}
 def _get(self,endpoint):
  if not self.url or not self.key:return{"success":False,"error":"Shield not configured"}
  try:
   r=get_requests().get(f"{self.url}{endpoint}",headers=self._headers(),timeout=self.timeout)
   return r.json()if r.status_code==200 else{"success":False,"error":f"HTTP {r.status_code}"}
  except Exception as e:return{"success":False,"error":str(e)}
 def _post(self,endpoint,data=None):
  if not self.url or not self.key:return{"success":False,"error":"Shield not configured"}
  try:
   r=get_requests().post(f"{self.url}{endpoint}",headers=self._headers(),json=data or{},timeout=self.timeout)
   return r.json()if r.status_code in[200,201]else{"success":False,"error":f"HTTP {r.status_code}"}
  except Exception as e:return{"success":False,"error":str(e)}
 def _delete(self,endpoint):
  if not self.url or not self.key:return{"success":False,"error":"Shield not configured"}
  try:
   r=get_requests().delete(f"{self.url}{endpoint}",headers=self._headers(),timeout=self.timeout)
   return r.json()if r.status_code==200 else{"success":False,"error":f"HTTP {r.status_code}"}
  except Exception as e:return{"success":False,"error":str(e)}
 def stats(self):return self._get("/api/admin/stats")
 def sessions(self):return self._get("/api/admin/sessions")
 def logs(self):return self._get("/api/admin/logs")
 def bans(self):return self._get("/api/admin/bans")
 def add_ban(self,hwid=None,ip=None,player_id=None,reason="Banned via Discord"):return self._post("/api/admin/bans",{"hwid":hwid,"ip":ip,"playerId":player_id,"reason":reason})
 def remove_ban(self,ban_id):return self._delete(f"/api/admin/bans/{ban_id}")
 def clear_bans(self):return self._post("/api/admin/bans/clear")
 def whitelist(self):return self._get("/api/admin/whitelist")
 def add_whitelist(self,wtype,value):return self._post("/api/admin/whitelist",{"type":wtype,"value":value})
 def remove_whitelist(self,wtype,value):return self._post("/api/admin/whitelist/remove",{"type":wtype,"value":value})
 def suspended(self):return self._get("/api/admin/suspended")
 def suspend(self,stype,value,reason="Suspended via Discord",duration=None):return self._post("/api/admin/suspend",{"type":stype,"value":value,"reason":reason,"duration":duration})
 def unsuspend(self,stype,value):return self._post("/api/admin/unsuspend",{"type":stype,"value":value})
 def kill_session(self,session_id,reason="Killed via Discord"):return self._post("/api/admin/kill-session",{"sessionId":session_id,"reason":reason})
 def clear_sessions(self):return self._post("/api/admin/sessions/clear")
 def clear_logs(self):return self._post("/api/admin/logs/clear")
 def clear_cache(self):return self._post("/api/admin/cache/clear")
 def keepalive(self):
  try:
   r=get_requests().get(f"{self.url}/api/keepalive",timeout=10)
   return r.json()if r.status_code==200 else{"success":False,"error":f"HTTP {r.status_code}"}
  except Exception as e:return{"success":False,"error":str(e)}
 def get_script(self):return self._get("/api/admin/script")
shield=ShieldAPI(SHIELD_URL,SHIELD_ADMIN_KEY)
class Database:
 def __init__(self,path="bot.db"):
  self.conn=sqlite3.connect(path,check_same_thread=False);self.lock=threading.Lock()
  self.conn.executescript('CREATE TABLE IF NOT EXISTS user_prefs(uid INTEGER PRIMARY KEY,model TEXT DEFAULT "auto");CREATE TABLE IF NOT EXISTS stats(id INTEGER PRIMARY KEY,cmd TEXT,uid INTEGER,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS blacklist(uid INTEGER PRIMARY KEY);CREATE TABLE IF NOT EXISTS dump_cache(url TEXT PRIMARY KEY,content TEXT,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);')
 def get_model(self,uid):
  with self.lock:r=self.conn.execute('SELECT model FROM user_prefs WHERE uid=?',(uid,)).fetchone();return r[0]if r else"auto"
 def set_model(self,uid,model):
  with self.lock:self.conn.execute('INSERT OR REPLACE INTO user_prefs VALUES(?,?)',(uid,model));self.conn.commit()
 def stat(self,cmd,uid):
  with self.lock:self.conn.execute('INSERT INTO stats(cmd,uid) VALUES(?,?)',(cmd,uid));self.conn.commit()
 def banned(self,uid):
  with self.lock:return self.conn.execute('SELECT 1 FROM blacklist WHERE uid=?',(uid,)).fetchone()is not None
 def add_blacklist(self,uid):
  with self.lock:self.conn.execute('INSERT OR IGNORE INTO blacklist VALUES(?)',(uid,));self.conn.commit()
 def remove_blacklist(self,uid):
  with self.lock:self.conn.execute('DELETE FROM blacklist WHERE uid=?',(uid,));self.conn.commit()
 def cache_dump(self,url,content):
  with self.lock:h=hashlib.md5(url.encode()).hexdigest();self.conn.execute('INSERT OR REPLACE INTO dump_cache VALUES(?,?,CURRENT_TIMESTAMP)',(h,content[:500000]));self.conn.commit()
 def get_cached_dump(self,url):
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
class Msg:
 role:str;content:str;ts:float
class Memory:
 def __init__(self):self.data=defaultdict(list);self.lock=threading.Lock()
 def add(self,uid,role,content):
  with self.lock:now=time.time();self.data[uid]=[m for m in self.data[uid]if now-m.ts<1800];self.data[uid].append(Msg(role,content[:1500],now))
  if len(self.data[uid])>15:self.data[uid]=self.data[uid][-15:]
 def get(self,uid):
  with self.lock:now=time.time();self.data[uid]=[m for m in self.data[uid]if now-m.ts<1800];return[{"role":m.role,"content":m.content}for m in self.data[uid]]
 def clear(self,uid):
  with self.lock:self.data[uid]=[]
mem=Memory()
SYSTEM_PROMPT='Kamu adalah AI Assistant yang helpful dan friendly. Jawab dalam Bahasa Indonesia kecuali diminta lain.'
OR_MODELS={"llama":"meta-llama/llama-4-scout:free","gemini":"google/gemini-2.5-flash-preview:free","qwen":"qwen/qwen3-235b-a22b:free","deepseek":"deepseek/deepseek-r1:free","mistral":"mistralai/mistral-small-3.1-24b-instruct:free"}
CF_MODELS={"llama":"@cf/meta/llama-3.3-70b-instruct-fp8-fast"}
MODEL_NAMES={"auto":"🚀 Auto","groq":"⚡ Groq","cerebras":"🧠 Cerebras","cloudflare":"☁️ Cloudflare","sambanova":"🦣 SambaNova","cohere":"🔷 Cohere","together":"🤝 Together","pollinations":"🌸 Pollinations","or_llama":"🦙 OR-Llama4","or_gemini":"🔵 OR-Gemini","or_qwen":"🟣 OR-Qwen3","or_deepseek":"🌊 OR-DeepSeek"}
CURL_PROFILES=["chrome120","chrome119","chrome116","chrome110","chrome107","chrome104","edge101","safari15_5"]
EXECUTOR_UA=["Roblox/WinInet","roblox/wininetmore","Synapse X/1.0","KRNL/1.0","Fluxus/1.0","ScriptWare/1.0","Electron/1.0","Delta/1.0","Hydrogen/1.0","Solara/1.0","Wave/1.0","Celery/1.0","Trigon/1.0","Codex/1.0"]
BROWSER_UA=["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36","Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36","Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0","Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15","Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"]
def gen_hwid():return hashlib.md5(f"{random.randint(100000,999999)}".encode()).hexdigest().upper()
def gen_executor_headers():
 hwid=gen_hwid();uid=str(random.randint(100000000,9999999999));pid=str(random.randint(1000000000,9999999999));jid=hashlib.md5(f"{time.time()}".encode()).hexdigest()[:32]
 return{"User-Agent":random.choice(EXECUTOR_UA),"Accept":"*/*","Accept-Language":"en-US,en;q=0.9","Accept-Encoding":"gzip, deflate, br","Connection":"keep-alive","x-hwid":hwid,"x-roblox-id":uid,"x-place-id":pid,"x-job-id":jid,"x-session-id":hashlib.md5(f"{hwid}{uid}".encode()).hexdigest()[:32],"Roblox-Place-Id":pid,"Roblox-Game-Id":pid,"Roblox-Session-Id":jid,"Cache-Control":"no-cache","Pragma":"no-cache"}
def gen_browser_headers():
 ua=random.choice(BROWSER_UA);cv=re.search(r'Chrome/(\d+)',ua);cv=cv.group(1)if cv else"120"
 return{"User-Agent":ua,"Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8","Accept-Language":"en-US,en;q=0.9","Accept-Encoding":"gzip, deflate, br","Connection":"keep-alive","Upgrade-Insecure-Requests":"1","Sec-Fetch-Dest":"document","Sec-Fetch-Mode":"navigate","Sec-Fetch-Site":"none","Sec-Fetch-User":"?1","sec-ch-ua":f'"Chromium";v="{cv}", "Google Chrome";v="{cv}", "Not?A_Brand";v="99"',"sec-ch-ua-mobile":"?0","sec-ch-ua-platform":'"Windows"',"Cache-Control":"max-age=0","DNT":"1"}
def gen_minimal_headers():return{"User-Agent":random.choice(BROWSER_UA),"Accept":"*/*","Accept-Encoding":"gzip, deflate","Connection":"keep-alive"}
class AdvancedDumper:
 def __init__(self):self.session_cookies={};self.last_success_method=None
 def detect_protection(self,resp_text,status_code):
  txt=resp_text[:2000].lower()if resp_text else""
  if status_code==403:return"blocked"
  if status_code==503 and("cloudflare"in txt or"cf-ray"in txt):return"cloudflare"
  if"just a moment"in txt or"checking your browser"in txt:return"cloudflare"
  if"captcha"in txt or"recaptcha"in txt:return"captcha"
  if"rate limit"in txt or status_code==429:return"ratelimit"
  if"access denied"in txt or"forbidden"in txt:return"blocked"
  if"--[["in txt and len(txt)<500 and"protected"in txt.lower():return"fakescript"
  return None
 def is_valid_content(self,content):
  if not content or len(content.strip())<10:return False
  txt=content[:1000].lower()
  if"<!doctype"in txt and"cloudflare"in txt:return False
  if"checking your browser"in txt:return False
  if"access denied"in txt and len(content)<500:return False
  return True
 def try_curl_executor(self,url,timeout=25):
  curl=get_curl()
  if not curl:return None,"curl not available"
  for profile in random.sample(CURL_PROFILES,min(4,len(CURL_PROFILES))):
   try:
    headers=gen_executor_headers();resp=curl.get(url,headers=headers,impersonate=profile,timeout=timeout,allow_redirects=True)
    if resp.status_code==200 and self.is_valid_content(resp.text):self.last_success_method=f"curl_executor_{profile}";return resp.text,None
    prot=self.detect_protection(resp.text,resp.status_code)
    if prot=="fakescript":continue
    if prot:return None,prot
   except Exception as e:
    if"timeout"in str(e).lower():continue
    logger.debug(f"curl_executor {profile}: {e}")
  return None,"all profiles failed"
 def try_curl_browser(self,url,timeout=25):
  curl=get_curl()
  if not curl:return None,"curl not available"
  for profile in random.sample(CURL_PROFILES,min(3,len(CURL_PROFILES))):
   try:
    headers=gen_browser_headers();resp=curl.get(url,headers=headers,impersonate=profile,timeout=timeout,allow_redirects=True)
    if resp.status_code==200 and self.is_valid_content(resp.text):self.last_success_method=f"curl_browser_{profile}";return resp.text,None
    prot=self.detect_protection(resp.text,resp.status_code)
    if prot:return None,prot
   except Exception as e:logger.debug(f"curl_browser {profile}: {e}")
  return None,"browser profiles failed"
 def try_cloudscraper(self,url,timeout=30):
  cs=get_cloudscraper()
  if not cs:return None,"cloudscraper not available"
  try:
   headers=gen_browser_headers()
   for k in["sec-ch-ua","sec-ch-ua-mobile","sec-ch-ua-platform"]:
    if k in headers:del headers[k]
   resp=cs.get(url,headers=headers,timeout=timeout,allow_redirects=True)
   if resp.status_code==200 and self.is_valid_content(resp.text):self.last_success_method="cloudscraper";return resp.text,None
   prot=self.detect_protection(resp.text,resp.status_code)
   if prot:return None,prot
  except Exception as e:logger.debug(f"cloudscraper: {e}");return None,str(e)
  return None,"cloudscraper failed"
 def try_requests_session(self,url,timeout=20):
  req=get_requests()
  if not req:return None,"requests not available"
  try:
   session=req.Session()
   for h_type in["executor","browser","minimal"]:
    headers=gen_executor_headers()if h_type=="executor"else gen_browser_headers()if h_type=="browser"else gen_minimal_headers()
    try:
     resp=session.get(url,headers=headers,timeout=timeout,allow_redirects=True,verify=True)
     if resp.status_code==200 and self.is_valid_content(resp.text):self.last_success_method=f"requests_{h_type}";return resp.text,None
    except:continue
  except Exception as e:logger.debug(f"requests: {e}");return None,str(e)
  return None,"requests failed"
 def try_raw_request(self,url,timeout=15):
  req=get_requests()
  if not req:return None,"requests not available"
  try:
   resp=req.get(url,headers={"User-Agent":random.choice(EXECUTOR_UA)},timeout=timeout,allow_redirects=True)
   if resp.status_code==200 and self.is_valid_content(resp.text):self.last_success_method="raw";return resp.text,None
  except Exception as e:return None,str(e)
  return None,"raw failed"
 def dump(self,url,use_cache=True):
  if use_cache:
   cached=db.get_cached_dump(url)
   if cached:return{"success":True,"content":cached,"method":"cache","cached":True}
  methods=[("curl_executor",self.try_curl_executor),("curl_browser",self.try_curl_browser),("cloudscraper",self.try_cloudscraper),("requests",self.try_requests_session),("raw",self.try_raw_request)]
  if self.last_success_method:
   for i,(name,_)in enumerate(methods):
    if self.last_success_method.startswith(name):methods.insert(0,methods.pop(i));break
  errors=[];last_protection=None
  for name,method in methods:
   try:
    content,error=method(url)
    if content:
     if use_cache:db.cache_dump(url,content)
     return{"success":True,"content":content,"method":self.last_success_method or name,"cached":False}
    if error:errors.append(f"{name}:{error}")
    if error in["cloudflare","captcha","blocked"]:last_protection=error
   except Exception as e:errors.append(f"{name}:exception:{str(e)[:30]}")
  return{"success":False,"error":last_protection or"all methods failed","details":errors[:5],"method":None}
dumper=AdvancedDumper()
def call_groq(msgs):
 cl=get_groq()
 if not cl:return None
 try:r=cl.chat.completions.create(messages=msgs,model="llama-3.3-70b-versatile",temperature=0.7,max_tokens=2000);return r.choices[0].message.content
 except Exception as e:logger.error(f"Groq:{e}");return None
def call_cerebras(msgs):
 if not KEY_CEREBRAS:return None
 try:
  r=get_requests().post("https://api.cerebras.ai/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_CEREBRAS}","Content-Type":"application/json"},json={"model":"llama-3.3-70b","messages":msgs,"temperature":0.7,"max_tokens":2000},timeout=30)
  if r.status_code==200:return r.json()["choices"][0]["message"]["content"]
  return None
 except Exception as e:logger.error(f"Cerebras:{e}");return None
def call_cloudflare(msgs):
 if not CF_ACCOUNT_ID or not CF_API_TOKEN:return None
 try:
  url=f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{CF_MODELS['llama']}"
  r=get_requests().post(url,headers={"Authorization":f"Bearer {CF_API_TOKEN}","Content-Type":"application/json"},json={"messages":msgs,"max_tokens":2000},timeout=60)
  if r.status_code==200:
   data=r.json()
   if data.get("success")and"result"in data:resp=data["result"].get("response","");return resp.strip()if resp else None
  return None
 except Exception as e:logger.error(f"Cloudflare:{e}");return None
def call_openrouter(msgs,mk="llama"):
 if not KEY_OPENROUTER:return None
 try:
  mid=OR_MODELS.get(mk,OR_MODELS["llama"])
  r=get_requests().post("https://openrouter.ai/api/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_OPENROUTER}","Content-Type":"application/json","HTTP-Referer":"https://github.com"},json={"model":mid,"messages":msgs,"temperature":0.7,"max_tokens":2000},timeout=60)
  if r.status_code==200:
   data=r.json()
   if"choices"in data and data["choices"]:return data["choices"][0]["message"]["content"]
  return None
 except Exception as e:logger.error(f"OR:{e}");return None
def call_sambanova(msgs):
 if not KEY_SAMBANOVA:return None
 try:
  r=get_requests().post("https://api.sambanova.ai/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_SAMBANOVA}","Content-Type":"application/json"},json={"model":"Meta-Llama-3.3-70B-Instruct","messages":msgs,"temperature":0.7,"max_tokens":2000},timeout=60)
  if r.status_code==200:return r.json()["choices"][0]["message"]["content"]
  return None
 except Exception as e:logger.error(f"SN:{e}");return None
def call_cohere(msgs):
 if not KEY_COHERE:return None
 try:
  preamble,hist,messages="",[], []
  for m in msgs:
   if m["role"]=="system":preamble=m["content"]
   else:messages.append(m)
  for m in messages[:-1]:hist.append({"role":"USER"if m["role"]=="user"else"CHATBOT","message":m["content"]})
  user_msg=messages[-1]["content"]if messages else""
  payload={"model":"command-r-plus","message":user_msg,"temperature":0.7}
  if preamble:payload["preamble"]=preamble
  if hist:payload["chat_history"]=hist
  r=get_requests().post("https://api.cohere.com/v2/chat",headers={"Authorization":f"Bearer {KEY_COHERE}","Content-Type":"application/json"},json=payload,timeout=60)
  if r.status_code==200:return r.json().get("text","")
  return None
 except Exception as e:logger.error(f"Cohere:{e}");return None
def call_together(msgs):
 if not KEY_TOGETHER:return None
 try:
  r=get_requests().post("https://api.together.xyz/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_TOGETHER}","Content-Type":"application/json"},json={"model":"meta-llama/Llama-3.3-70B-Instruct-Turbo","messages":msgs,"temperature":0.7,"max_tokens":2000},timeout=60)
  if r.status_code==200:return r.json()["choices"][0]["message"]["content"]
  return None
 except Exception as e:logger.error(f"Together:{e}");return None
def call_pollinations(prompt):
 try:
  r=get_requests().get(f"https://text.pollinations.ai/{prompt}",timeout=60)
  if r.status_code==200 and r.text.strip():return r.text.strip()
  return None
 except Exception as e:logger.error(f"Pollinations:{e}");return None
def call_ai(model,msgs,prompt=""):
 if model=="groq":return call_groq(msgs),"Groq"
 elif model=="cerebras":return call_cerebras(msgs),"Cerebras"
 elif model=="cloudflare":return call_cloudflare(msgs),"Cloudflare"
 elif model=="sambanova":return call_sambanova(msgs),"SambaNova"
 elif model=="cohere":return call_cohere(msgs),"Cohere"
 elif model=="together":return call_together(msgs),"Together"
 elif model=="pollinations":return call_pollinations(prompt),"Pollinations"
 elif model.startswith("or_"):mk=model[3:];return call_openrouter(msgs,mk),f"OR-{mk.title()}"
 return None,"none"
def ask_ai(prompt,uid=None,model=None):
 user_model=db.get_model(uid)if uid else"auto"
 selected=model if model and model!="auto"else(user_model if user_model!="auto"else"auto")
 msgs=[{"role":"system","content":SYSTEM_PROMPT}]
 if uid:h=mem.get(uid);msgs.extend(h[-6:])if h else None
 msgs.append({"role":"user","content":prompt})
 result,used=None,"none"
 if selected!="auto":
  result,used=call_ai(selected,msgs,prompt)
  if not result:
   for fn,nm in[(lambda:call_groq(msgs),"Groq"),(lambda:call_cerebras(msgs),"Cerebras"),(lambda:call_cloudflare(msgs),"Cloudflare"),(lambda:call_pollinations(prompt),"Pollinations")]:
    try:result=fn()
    except:continue
    if result:used=f"{nm}(fb)";break
 else:
  for fn,nm in[(lambda:call_groq(msgs),"Groq"),(lambda:call_cerebras(msgs),"Cerebras"),(lambda:call_cloudflare(msgs),"Cloudflare"),(lambda:call_openrouter(msgs,"llama"),"OR"),(lambda:call_sambanova(msgs),"SN"),(lambda:call_pollinations(prompt),"Poll")]:
   try:result=fn()
   except:continue
   if result:used=nm;break
 if not result:return"❌ Semua AI tidak tersedia.","none"
 if uid:mem.add(uid,"user",prompt[:500]);mem.add(uid,"assistant",result[:500])
 return result,used
def split_msg(text,limit=1900):
 if not text or not str(text).strip():return["(kosong)"]
 text=str(text).strip()[:3800]
 if len(text)<=limit:return[text]
 chunks=[]
 while text:
  if len(text)<=limit:chunks.append(text);break
  idx=text.rfind('\n',0,limit)
  if idx<=0:idx=text.rfind(' ',0,limit)
  if idx<=0:idx=limit
  chunks.append(text[:idx].strip());text=text[idx:].lstrip()
 return chunks if chunks else["(kosong)"]
async def send_ai_response(channel,user,content,used):
 try:
  if not content or not content.strip():content="(Response kosong)"
  chunks=split_msg(content);embed=discord.Embed(color=0x5865F2);embed.set_footer(text=f"🤖 {used} | {user.display_name}")
  await channel.send(content=chunks[0],embed=embed if len(chunks)==1 else None)
  for c in chunks[1:]:
   if c.strip():await channel.send(c)
  return True
 except Exception as e:logger.error(f"Send error:{e}");return False
def format_timestamp(ts):
 if not ts:return"N/A"
 try:
  if isinstance(ts,str):return ts[:19].replace("T"," ")
  return str(ts)
 except:return str(ts)
@bot.event
async def on_ready():
 logger.info(f'🔥 {bot.user} | {len(bot.guilds)} servers')
 await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening,name=f"{PREFIX}help"))
@bot.event
async def on_command_error(ctx,error):
 if isinstance(error,commands.CommandNotFound):return
 logger.error(f"Command error:{error}")
@bot.event
async def on_message(msg):
 if msg.author.bot:return
 if bot.user.mentioned_in(msg)and not msg.mention_everyone:
  content=msg.content.replace(f'<@{bot.user.id}>','').replace(f'<@!{bot.user.id}>','').strip()
  if content:
   if db.banned(msg.author.id):return
   ok,rem=rl.check(msg.author.id,"mention",5)
   if not ok:await msg.channel.send(f"⏳ {msg.author.mention} tunggu {rem:.0f}s");return
   async with msg.channel.typing():result,used=ask_ai(content,msg.author.id);await send_ai_response(msg.channel,msg.author,result,used);db.stat("ai",msg.author.id)
  else:m=db.get_model(msg.author.id);await msg.channel.send(f"👋 {msg.author.mention} Model:**{MODEL_NAMES.get(m,m)}**\nKetik pertanyaan setelah mention!")
  return
 await bot.process_commands(msg)
@bot.command(name="ai",aliases=["ask","a","tanya"])
async def cmd_ai(ctx,*,prompt:str=None):
 if db.banned(ctx.author.id):return
 ok,rem=rl.check(ctx.author.id,"ai",5)
 if not ok:return await ctx.send(f"⏳ {ctx.author.mention} tunggu {rem:.0f}s")
 if not prompt:return await ctx.send(f"❌ Gunakan:`{PREFIX}ai <pertanyaan>`")
 async with ctx.typing():result,used=ask_ai(prompt,ctx.author.id);await send_ai_response(ctx.channel,ctx.author,result,used);db.stat("ai",ctx.author.id)
@bot.command(name="model",aliases=["m"])
async def cmd_model(ctx,*,model:str=None):
 if not model:
  cur=db.get_model(ctx.author.id);e=discord.Embed(title="🤖 Model AI",color=0x3498DB)
  e.add_field(name="Model Kamu",value=f"**{MODEL_NAMES.get(cur,cur)}**",inline=False)
  e.add_field(name="Tersedia",value="\n".join([f"`{k}` → {v}"for k,v in MODEL_NAMES.items()]),inline=False)
  e.set_footer(text=f"Ganti:{PREFIX}model <nama>");return await ctx.send(embed=e)
 model=model.lower().strip()
 if model not in MODEL_NAMES:return await ctx.send(f"❌ Model tidak valid! Pilihan:`{', '.join(MODEL_NAMES.keys())}`")
 db.set_model(ctx.author.id,model);await ctx.send(f"✅ {ctx.author.mention} Model:**{MODEL_NAMES.get(model,model)}**")
@bot.command(name="clear",aliases=["reset"])
async def cmd_clear(ctx):mem.clear(ctx.author.id);await ctx.send(f"🧹 {ctx.author.mention} Memory dihapus!")
@bot.command(name="ping",aliases=["p"])
async def cmd_ping(ctx):
 m=db.get_model(ctx.author.id);e=discord.Embed(title="🏓 Pong!",color=0x00FF00)
 e.add_field(name="Latency",value=f"`{round(bot.latency*1000)}ms`")
 e.add_field(name="Model",value=f"`{MODEL_NAMES.get(m,m)}`")
 e.add_field(name="Shield",value=f"`{'✅'if SHIELD_URL else'❌'}`")
 await ctx.send(embed=e)
@bot.command(name="help",aliases=["h"])
async def cmd_help(ctx):
 e=discord.Embed(title="📚 Bot Help",color=0x5865F2)
 e.add_field(name="🤖 AI Chat",value=f"`{PREFIX}ai <teks>`\n`@bot <teks>`",inline=False)
 e.add_field(name="⚙️ Settings",value=f"`{PREFIX}model` - Lihat/ganti\n`{PREFIX}clear` - Hapus memory",inline=False)
 e.add_field(name="🔧 Tools",value=f"`{PREFIX}dump <url>` - Advanced dump\n`{PREFIX}dumpinfo` - Dump methods",inline=False)
 e.add_field(name="🛡️ Shield",value=f"`{PREFIX}shield help` - Shield commands",inline=False)
 await ctx.send(embed=e)
@bot.command(name="dump",aliases=["dl","get","fetch"])
async def cmd_dump(ctx,url:str=None,*,flags:str=""):
 if not url:return await ctx.send(f"❌ Gunakan:`{PREFIX}dump <url>`")
 ok,rem=rl.check(ctx.author.id,"dump",8)
 if not ok:return await ctx.send(f"⏳ Tunggu {rem:.0f}s")
 if not url.startswith(("http://","https://")):url="https://"+url
 use_cache="--nocache"not in flags.lower()
 msg=await ctx.send("🔄 **Dumping...**")
 async with ctx.typing():
  try:
   start=time.time();result=dumper.dump(url,use_cache=use_cache);elapsed=time.time()-start
   if result["success"]:
    content=result["content"];ext="lua"
    if"<!DOCTYPE"in content[:300].upper()or"<html"in content[:300].lower():ext="html"
    elif content.strip().startswith("{")or content.strip().startswith("["):ext="json"
    elif"local "in content[:500]or"function"in content[:500]:ext="lua"
    elif"def "in content[:500]or"import "in content[:500]:ext="py"
    size=len(content);size_str=f"{size:,}b"if size<1024 else f"{size/1024:.1f}KB"if size<1048576 else f"{size/1048576:.1f}MB"
    e=discord.Embed(title="✅ Dump Success",color=0x00FF00)
    e.add_field(name="📦 Size",value=f"`{size_str}`",inline=True)
    e.add_field(name="📄 Type",value=f"`.{ext}`",inline=True)
    e.add_field(name="⚡ Method",value=f"`{result['method']}`",inline=True)
    e.add_field(name="⏱️ Time",value=f"`{elapsed:.2f}s`",inline=True)
    e.add_field(name="💾 Cached",value=f"`{'Yes'if result.get('cached')else'No'}`",inline=True)
    await msg.delete();db.stat("dump",ctx.author.id)
    filename=f"dump_{hashlib.md5(url.encode()).hexdigest()[:8]}.{ext}"
    await ctx.send(embed=e,file=discord.File(io.BytesIO(content.encode('utf-8',errors='replace')),filename))
   else:
    e=discord.Embed(title="❌ Dump Failed",color=0xFF0000)
    e.add_field(name="🚫 Error",value=f"`{result['error']}`",inline=False)
    if result.get("details"):e.add_field(name="📋 Details",value=f"```{chr(10).join(result['details'][:3])}```",inline=False)
    await msg.edit(content=None,embed=e)
  except Exception as ex:logger.error(f"Dump error:{ex}");await msg.edit(content=f"❌ Error:`{str(ex)[:100]}`")
@bot.command(name="dumpinfo",aliases=["di"])
async def cmd_dumpinfo(ctx):
 e=discord.Embed(title="🔧 Dump Methods",color=0x3498DB)
 e.add_field(name="Methods",value="1️⃣ curl_cffi+Executor\n2️⃣ curl_cffi+Browser\n3️⃣ Cloudscraper\n4️⃣ Requests\n5️⃣ Raw",inline=False)
 e.add_field(name="Bypass",value="✅ UA check\n✅ Headers\n✅ Some CF\n❌ Captcha\n❌ JS Challenge",inline=False)
 last=dumper.last_success_method
 if last:e.add_field(name="Last Success",value=f"`{last}`",inline=False)
 await ctx.send(embed=e)
@bot.group(name="shield",aliases=["sh","s"],invoke_without_command=True)
async def cmd_shield(ctx):
 if ctx.invoked_subcommand is None:
  if not SHIELD_URL:return await ctx.send("❌ Shield not configured. Set `SHIELD_URL` and `SHIELD_ADMIN_KEY`")
  e=discord.Embed(title="🛡️ Shield Commands",color=0x5865F2)
  e.add_field(name="📊 Info",value=f"`{PREFIX}shield stats` - Server stats\n`{PREFIX}shield sessions` - Active sessions\n`{PREFIX}shield logs` - Recent logs\n`{PREFIX}shield keepalive` - Check status",inline=False)
  e.add_field(name="🚫 Bans",value=f"`{PREFIX}shield bans` - List bans\n`{PREFIX}shield ban <type> <value>` - Add ban\n`{PREFIX}shield unban <id>` - Remove ban\n`{PREFIX}shield clearbans` - Clear all",inline=False)
  e.add_field(name="📋 Whitelist",value=f"`{PREFIX}shield wl` - List whitelist\n`{PREFIX}shield wladd <type> <value>`\n`{PREFIX}shield wlremove <type> <value>`",inline=False)
  e.add_field(name="⏸️ Suspend",value=f"`{PREFIX}shield suspended` - List\n`{PREFIX}shield suspend <type> <value>`\n`{PREFIX}shield unsuspend <type> <value>`",inline=False)
  e.add_field(name="🔧 Manage",value=f"`{PREFIX}shield kill <sid>` - Kill session\n`{PREFIX}shield clearsessions`\n`{PREFIX}shield clearlogs`\n`{PREFIX}shield clearcache`",inline=False)
  e.add_field(name="📜 Script",value=f"`{PREFIX}shield script` - Get protected script",inline=False)
  e.set_footer(text=f"Server: {SHIELD_URL[:50]}...")
  await ctx.send(embed=e)
@cmd_shield.command(name="stats",aliases=["st","status"])
async def shield_stats(ctx):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only!")
 async with ctx.typing():
  r=shield.stats()
  if not r.get("success"):return await ctx.send(f"❌ Error: `{r.get('error','Unknown')}`")
  s=r.get("stats",{});ka=r.get("keepAlive",{})
  e=discord.Embed(title="🛡️ Shield Stats",color=0x00FF00)
  e.add_field(name="📊 Totals",value=f"Executions: `{s.get('totalExecutions',0)}`\nBans: `{s.get('totalBans',0)}`\nSuspicious: `{s.get('totalSuspicious',0)}`",inline=True)
  e.add_field(name="🔄 Sessions",value=f"Active: `{r.get('sessions',0)}`",inline=True)
  e.add_field(name="⏰ KeepAlive",value=f"Count: `{ka.get('count',0)}`\nLast: `{format_timestamp(ka.get('lastPing'))}`",inline=True)
  e.set_footer(text=f"Updated: {format_timestamp(r.get('ts'))}")
  await ctx.send(embed=e)
@cmd_shield.command(name="sessions",aliases=["sess","se"])
async def shield_sessions(ctx):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only!")
 async with ctx.typing():
  r=shield.sessions()
  if not r.get("success"):return await ctx.send(f"❌ Error: `{r.get('error','Unknown')}`")
  sessions=r.get("sessions",[])
  if not sessions:return await ctx.send("📭 No active sessions")
  e=discord.Embed(title=f"🔄 Active Sessions ({len(sessions)})",color=0x3498DB)
  for s in sessions[:10]:
   sid=s.get("sessionId","?")[:8];uid=s.get("userId","?");age=s.get("age",0)
   e.add_field(name=f"🔹 {sid}...",value=f"User: `{uid}`\nAge: `{age}s`\nIP: `{s.get('ip','?')[:15]}`",inline=True)
  if len(sessions)>10:e.set_footer(text=f"+{len(sessions)-10} more sessions")
  await ctx.send(embed=e)
@cmd_shield.command(name="logs",aliases=["log","l"])
async def shield_logs(ctx):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only!")
 async with ctx.typing():
  r=shield.logs()
  if not r.get("success"):return await ctx.send(f"❌ Error: `{r.get('error','Unknown')}`")
  logs=r.get("logs",[])
  if not logs:return await ctx.send("📭 No logs")
  e=discord.Embed(title=f"📋 Recent Logs ({len(logs)})",color=0x3498DB)
  desc=""
  for l in logs[:15]:
   act=l.get("action","?");ok="✅"if l.get("success")else"❌";ts=format_timestamp(l.get("ts"))[:10]
   desc+=f"{ok} `{act}` - {ts}\n"
  e.description=desc[:2000]
  await ctx.send(embed=e)
@cmd_shield.command(name="bans",aliases=["ban","b"])
async def shield_bans(ctx,action:str=None,btype:str=None,*,value:str=None):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only!")
 if not action:
  async with ctx.typing():
   r=shield.bans()
   if not r.get("success"):return await ctx.send(f"❌ Error: `{r.get('error','Unknown')}`")
   bans=r.get("bans",[])
   if not bans:return await ctx.send("📭 No bans")
   e=discord.Embed(title=f"🚫 Bans ({len(bans)})",color=0xFF0000)
   desc=""
   for b in bans[:20]:
    bid=b.get("banId","?");reason=b.get("reason","?")[:20]
    hwid=b.get("hwid","");pid=b.get("playerId","");ip=b.get("ip","")
    target=hwid[:8]if hwid else pid if pid else ip[:15]if ip else"?"
    desc+=f"`{bid}` - {target}... ({reason})\n"
   e.description=desc[:2000]
   e.set_footer(text=f"Unban: {PREFIX}shield unban <banId>")
   await ctx.send(embed=e)
 elif action.lower()in["add","new","create"]:
  if not btype or not value:return await ctx.send(f"❌ Usage: `{PREFIX}shield bans add <hwid|userid|ip> <value> [reason]`")
  parts=value.split(" ",1);val=parts[0];reason=parts[1]if len(parts)>1 else"Banned via Discord"
  async with ctx.typing():
   if btype.lower()in["hwid","h"]:r=shield.add_ban(hwid=val,reason=reason)
   elif btype.lower()in["userid","user","uid","u","player","pid"]:r=shield.add_ban(player_id=val,reason=reason)
   elif btype.lower()in["ip","i"]:r=shield.add_ban(ip=val,reason=reason)
   else:return await ctx.send("❌ Type must be: hwid, userid, or ip")
   if r.get("success"):await ctx.send(f"✅ Banned! ID: `{r.get('banId','?')}`")
   else:await ctx.send(f"❌ Error: `{r.get('error','Unknown')}`")
@cmd_shield.command(name="unban",aliases=["ub","removeban"])
async def shield_unban(ctx,ban_id:str=None):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only!")
 if not ban_id:return await ctx.send(f"❌ Usage: `{PREFIX}shield unban <banId>`")
 async with ctx.typing():
  r=shield.remove_ban(ban_id)
  if r.get("success"):await ctx.send(f"✅ Unbanned: `{ban_id}`")
  else:await ctx.send(f"❌ Error: `{r.get('error','Unknown')}`")
@cmd_shield.command(name="clearbans",aliases=["cb"])
async def shield_clearbans(ctx):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only!")
 async with ctx.typing():
  r=shield.clear_bans()
  if r.get("success"):await ctx.send(f"✅ Cleared {r.get('cleared',0)} bans")
  else:await ctx.send(f"❌ Error: `{r.get('error','Unknown')}`")
@cmd_shield.command(name="wl",aliases=["whitelist","w"])
async def shield_whitelist(ctx):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only!")
 async with ctx.typing():
  r=shield.whitelist()
  if not r.get("success"):return await ctx.send(f"❌ Error: `{r.get('error','Unknown')}`")
  wl=r.get("whitelist",{})
  e=discord.Embed(title="📋 Whitelist",color=0x00FF00)
  uids=wl.get("userIds",[]);hwids=wl.get("hwids",[]);ips=wl.get("ips",[]);owners=wl.get("owners",[])
  e.add_field(name=f"👤 Users ({len(uids)})",value=", ".join([f"`{x}`"for x in uids[:10]])or"None",inline=False)
  e.add_field(name=f"🔑 HWIDs ({len(hwids)})",value=", ".join([f"`{x[:8]}...`"for x in hwids[:5]])or"None",inline=False)
  e.add_field(name=f"🌐 IPs ({len(ips)})",value=", ".join([f"`{x}`"for x in ips[:5]])or"None",inline=False)
  e.add_field(name=f"👑 Owners ({len(owners)})",value=", ".join([f"`{x}`"for x in owners])or"None",inline=False)
  await ctx.send(embed=e)
@cmd_shield.command(name="wladd",aliases=["whitelistadd","wa"])
async def shield_wladd(ctx,wtype:str=None,*,value:str=None):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only!")
 if not wtype or not value:return await ctx.send(f"❌ Usage: `{PREFIX}shield wladd <userId|hwid|ip> <value>`")
 async with ctx.typing():
  r=shield.add_whitelist(wtype.lower(),value)
  if r.get("success"):await ctx.send(f"✅ {r.get('msg','Added')}")
  else:await ctx.send(f"❌ Error: `{r.get('error','Unknown')}`")
@cmd_shield.command(name="wlremove",aliases=["whitelistremove","wr"])
async def shield_wlremove(ctx,wtype:str=None,*,value:str=None):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only!")
 if not wtype or not value:return await ctx.send(f"❌ Usage: `{PREFIX}shield wlremove <userId|hwid|ip> <value>`")
 async with ctx.typing():
  r=shield.remove_whitelist(wtype.lower(),value)
  if r.get("success"):await ctx.send(f"✅ {r.get('msg','Removed')}")
  else:await ctx.send(f"❌ Error: `{r.get('error','Unknown')}`")
@cmd_shield.command(name="suspended",aliases=["susp","suspensions"])
async def shield_suspended(ctx):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only!")
 async with ctx.typing():
  r=shield.suspended()
  if not r.get("success"):return await ctx.send(f"❌ Error: `{r.get('error','Unknown')}`")
  susp=r.get("suspended",[])
  if not susp:return await ctx.send("📭 No suspensions")
  e=discord.Embed(title=f"⏸️ Suspensions ({len(susp)})",color=0xFFA500)
  for s in susp[:10]:
   stype=s.get("type","?");val=str(s.get("value","?"))[:15];reason=s.get("reason","?")[:30]
   e.add_field(name=f"🔸 {stype}: {val}",value=f"Reason: {reason}",inline=True)
  await ctx.send(embed=e)
@cmd_shield.command(name="suspend",aliases=["sus"])
async def shield_suspend(ctx,stype:str=None,value:str=None,*,reason:str="Suspended via Discord"):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only!")
 if not stype or not value:return await ctx.send(f"❌ Usage: `{PREFIX}shield suspend <hwid|userId|session> <value> [reason]`")
 async with ctx.typing():
  r=shield.suspend(stype.lower(),value,reason)
  if r.get("success"):await ctx.send(f"✅ {r.get('msg','Suspended')}")
  else:await ctx.send(f"❌ Error: `{r.get('error','Unknown')}`")
@cmd_shield.command(name="unsuspend",aliases=["unsus"])
async def shield_unsuspend(ctx,stype:str=None,value:str=None):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only!")
 if not stype or not value:return await ctx.send(f"❌ Usage: `{PREFIX}shield unsuspend <hwid|userId|session> <value>`")
 async with ctx.typing():
  r=shield.unsuspend(stype.lower(),value)
  if r.get("success"):await ctx.send(f"✅ {r.get('msg','Unsuspended')}")
  else:await ctx.send(f"❌ Error: `{r.get('error','Unknown')}`")
@cmd_shield.command(name="kill",aliases=["killsession","ks"])
async def shield_kill(ctx,session_id:str=None,*,reason:str="Killed via Discord"):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only!")
 if not session_id:return await ctx.send(f"❌ Usage: `{PREFIX}shield kill <sessionId> [reason]`")
 async with ctx.typing():
  r=shield.kill_session(session_id,reason)
  if r.get("success"):await ctx.send(f"✅ {r.get('msg','Session killed')}")
  else:await ctx.send(f"❌ Error: `{r.get('error','Unknown')}`")
@cmd_shield.command(name="clearsessions",aliases=["cs"])
async def shield_clearsessions(ctx):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only!")
 async with ctx.typing():
  r=shield.clear_sessions()
  if r.get("success"):await ctx.send(f"✅ Cleared {r.get('cleared',0)} sessions")
  else:await ctx.send(f"❌ Error: `{r.get('error','Unknown')}`")
@cmd_shield.command(name="clearlogs",aliases=["cl"])
async def shield_clearlogs(ctx):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only!")
 async with ctx.typing():
  r=shield.clear_logs()
  if r.get("success"):await ctx.send("✅ Logs cleared")
  else:await ctx.send(f"❌ Error: `{r.get('error','Unknown')}`")
@cmd_shield.command(name="clearcache",aliases=["cc"])
async def shield_clearcache(ctx):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only!")
 async with ctx.typing():
  r=shield.clear_cache()
  if r.get("success"):await ctx.send("✅ Cache cleared")
  else:await ctx.send(f"❌ Error: `{r.get('error','Unknown')}`")
@cmd_shield.command(name="keepalive",aliases=["ka","ping","health"])
async def shield_keepalive(ctx):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only!")
 async with ctx.typing():
  start=time.time();r=shield.keepalive();elapsed=(time.time()-start)*1000
  if r.get("status")=="alive":
   e=discord.Embed(title="✅ Shield Online",color=0x00FF00)
   e.add_field(name="⏱️ Latency",value=f"`{elapsed:.0f}ms`",inline=True)
   e.add_field(name="🔄 Uptime",value=f"`{r.get('stats',{}).get('uptimeFormatted','?')}`",inline=True)
   e.add_field(name="💾 Memory",value=f"`{r.get('stats',{}).get('memory','?')}`",inline=True)
   e.add_field(name="📊 Pings",value=f"`{r.get('stats',{}).get('pingCount',0)}`",inline=True)
   e.add_field(name="🔌 Sessions",value=f"`{r.get('stats',{}).get('sessions',0)}`",inline=True)
   e.add_field(name="🗄️ DB",value=f"`{r.get('db','?')}`",inline=True)
   await ctx.send(embed=e)
  else:await ctx.send(f"❌ Shield offline: `{r.get('error','Unknown')}`")
@cmd_shield.command(name="script",aliases=["sc","getscript","download"])
async def shield_script(ctx):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only!")
 async with ctx.typing():
  r=shield.get_script()
  if not r.get("success"):return await ctx.send(f"❌ Error: `{r.get('error','Unknown')}`")
  script=r.get("script","")
  if not script:return await ctx.send("❌ No script configured")
  size=len(script);size_str=f"{size:,}b"if size<1024 else f"{size/1024:.1f}KB"
  e=discord.Embed(title="📜 Protected Script",color=0x00FF00)
  e.add_field(name="Size",value=f"`{size_str}`",inline=True)
  e.add_field(name="Lines",value=f"`{script.count(chr(10))+1}`",inline=True)
  await ctx.send(embed=e,file=discord.File(io.BytesIO(script.encode()),"script.lua"))
@bot.command(name="testai")
async def cmd_testai(ctx):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only!")
 await ctx.send("🔄 Testing AI providers...")
 async with ctx.typing():
  results=[];test=[{"role":"user","content":"Say:OK"}]
  for name,fn in[("Groq",lambda:call_groq(test)),("Cerebras",lambda:call_cerebras(test)),("Cloudflare",lambda:call_cloudflare(test)),("SambaNova",lambda:call_sambanova(test)),("Together",lambda:call_together(test)),("OR-Llama",lambda:call_openrouter(test,"llama")),("OR-Gemini",lambda:call_openrouter(test,"gemini")),("Cohere",lambda:call_cohere(test)),("Pollinations",lambda:call_pollinations("Say OK"))]:
   try:r=fn();results.append(f"✅ **{name}**"if r else f"❌ **{name}**")
   except:results.append(f"❌ **{name}**")
  e=discord.Embed(title="🔧 AI Status",description="\n".join(results),color=0x3498DB);await ctx.send(embed=e)
@bot.command(name="testdump",aliases=["td"])
async def cmd_testdump(ctx):
 if ctx.author.id not in OWNER_IDS:return await ctx.send("❌ Owner only!")
 test_urls=["https://httpbin.org/get","https://raw.githubusercontent.com/electron/electron/main/README.md"]
 await ctx.send("🔄 Testing dump...")
 async with ctx.typing():
  results=[]
  for url in test_urls:
   r=dumper.dump(url,use_cache=False)
   results.append(f"✅ `{url[:30]}` - {r['method']}"if r["success"]else f"❌ `{url[:30]}` - {r['error']}")
  e=discord.Embed(title="🔧 Dump Test",description="\n".join(results),color=0x3498DB)
  e.add_field(name="Libraries",value=f"curl_cffi:`{'✅'if get_curl()else'❌'}` cloudscraper:`{'✅'if get_cloudscraper()else'❌'}`")
  await ctx.send(embed=e)
@bot.command(name="blacklist")
async def cmd_blacklist(ctx,action:str=None,user:discord.User=None):
 if ctx.author.id not in OWNER_IDS:return
 if not action or not user:return await ctx.send(f"❌ `{PREFIX}blacklist <add/remove> @user`")
 if action.lower()in["add","ban"]:db.add_blacklist(user.id);await ctx.send(f"✅ {user.mention} blocked")
 elif action.lower()in["remove","unban"]:db.remove_blacklist(user.id);await ctx.send(f"✅ {user.mention} unblocked")
if __name__=="__main__":
 keep_alive()
 print("="*50)
 print("🚀 Bot Starting...")
 print(f"📦 Prefix: {PREFIX}")
 print(f"👑 Owners: {OWNER_IDS}")
 print(f"🛡️ Shield: {'✅ '+SHIELD_URL[:30]if SHIELD_URL else'❌ Not configured'}")
 print("🔑 AI Keys:")
 for n,k in[("Groq",KEY_GROQ),("Cerebras",KEY_CEREBRAS),("Cloudflare",CF_API_TOKEN),("OpenRouter",KEY_OPENROUTER),("SambaNova",KEY_SAMBANOVA),("Cohere",KEY_COHERE),("Together",KEY_TOGETHER)]:print(f"   {n}:{'✅'if k else'❌'}")
 print("🔧 Dump:")
 print(f"   curl_cffi:{'✅'if get_curl()else'❌'} cloudscraper:{'✅'if get_cloudscraper()else'❌'}")
 print("="*50)
 bot.run(DISCORD_TOKEN,log_handler=None)
