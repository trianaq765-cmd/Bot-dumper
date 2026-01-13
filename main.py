import discord,os,io,re,time,json,logging,sqlite3,random,threading,hashlib,asyncio
from collections import defaultdict
from dataclasses import dataclass
from discord.ext import commands
from urllib.parse import quote
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
if not DISCORD_TOKEN:print("DISCORD_TOKEN Missing");exit(1)
intents=discord.Intents.default();intents.message_content=True
bot=commands.Bot(command_prefix=PREFIX,intents=intents,help_command=None)
_groq=None;_requests=None
_panel_config={"keys":{},"models":{},"settings":{},"user_models":{},"last_fetch":0}
_panel_lock=threading.Lock()
def get_requests():
 global _requests
 if _requests is None:import requests;_requests=requests
 return _requests
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
  except Exception as e:logger.warning(f"Panel fetch failed:{e}")
 return None
def get_api_key(name):
 config=fetch_panel_config()
 if config and name in config.get("keys",{}):return config["keys"][name]
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
DEFAULT_MODELS={"groq":{"e":"⚡","n":"Groq","d":"Llama 3.3 70B","c":"main","p":"groq","m":"llama-3.3-70b-versatile"},"cerebras":{"e":"🧠","n":"Cerebras","d":"Llama 3.3 70B","c":"main","p":"cerebras","m":"llama-3.3-70b"},"sambanova":{"e":"🦣","n":"SambaNova","d":"Llama 3.3 70B","c":"main","p":"sambanova","m":"Meta-Llama-3.3-70B-Instruct"},"cloudflare":{"e":"☁️","n":"Cloudflare","d":"Llama 3.3 70B","c":"main","p":"cloudflare","m":"@cf/meta/llama-3.3-70b-instruct-fp8-fast"},"cohere":{"e":"🔷","n":"Cohere","d":"Command R+","c":"main","p":"cohere","m":"command-r-plus-08-2024"},"mistral":{"e":"Ⓜ️","n":"Mistral","d":"Mistral Small","c":"main","p":"mistral","m":"mistral-small-latest"},"together":{"e":"🤝","n":"Together","d":"Llama 3.3 Turbo","c":"main","p":"together","m":"meta-llama/Llama-3.3-70B-Instruct-Turbo"},"moonshot":{"e":"🌙","n":"Moonshot","d":"Kimi 128K","c":"main","p":"moonshot","m":"moonshot-v1-8k"},"huggingface":{"e":"🤗","n":"HuggingFace","d":"Mixtral 8x7B","c":"main","p":"huggingface","m":"mistralai/Mixtral-8x7B-Instruct-v0.1"},"replicate":{"e":"🔄","n":"Replicate","d":"Llama 405B","c":"main","p":"replicate","m":"meta/meta-llama-3.1-405b-instruct"},"tavily":{"e":"🔍","n":"Tavily","d":"Web Search","c":"main","p":"tavily","m":"search"},"or_llama":{"e":"🦙","n":"OR-Llama","d":"Llama 3.3 70B","c":"openrouter","p":"openrouter","m":"meta-llama/llama-3.3-70b-instruct:free"},"or_gemini":{"e":"💎","n":"OR-Gemini","d":"Gemini 2.0","c":"openrouter","p":"openrouter","m":"google/gemini-2.0-flash-exp:free"},"or_qwen":{"e":"💻","n":"OR-Qwen","d":"Qwen 2.5 72B","c":"openrouter","p":"openrouter","m":"qwen/qwen-2.5-72b-instruct:free"},"or_deepseek":{"e":"🌊","n":"OR-DeepSeek","d":"DeepSeek","c":"openrouter","p":"openrouter","m":"deepseek/deepseek-chat:free"},"or_mistral":{"e":"🅼","n":"OR-Mistral","d":"Mistral Nemo","c":"openrouter","p":"openrouter","m":"mistralai/mistral-nemo:free"},"pf_openai":{"e":"🆓","n":"PollFree-OpenAI","d":"OpenAI Free","c":"pollinations_free","p":"pollinations_free","m":"openai"},"pf_claude":{"e":"🆓","n":"PollFree-Claude","d":"Claude Free","c":"pollinations_free","p":"pollinations_free","m":"claude"},"pf_gemini":{"e":"🆓","n":"PollFree-Gemini","d":"Gemini Free","c":"pollinations_free","p":"pollinations_free","m":"gemini"},"pf_deepseek":{"e":"🆓","n":"PollFree-DeepSeek","d":"DeepSeek Free","c":"pollinations_free","p":"pollinations_free","m":"deepseek"},"pf_qwen":{"e":"🆓","n":"PollFree-Qwen","d":"Qwen 72B Free","c":"pollinations_free","p":"pollinations_free","m":"qwen-72b"},"pf_llama":{"e":"🆓","n":"PollFree-Llama","d":"Llama 3.3 Free","c":"pollinations_free","p":"pollinations_free","m":"llama"},"poll_free":{"e":"🌸","n":"PollFree-Auto","d":"Auto Select Free","c":"pollinations_free","p":"pollinations_free","m":"auto"},"pa_openai":{"e":"🔑","n":"PollAPI-OpenAI","d":"OpenAI API","c":"pollinations_api","p":"pollinations_api","m":"openai"},"pa_claude":{"e":"🔑","n":"PollAPI-Claude","d":"Claude API","c":"pollinations_api","p":"pollinations_api","m":"claude"},"pa_gemini":{"e":"🔑","n":"PollAPI-Gemini","d":"Gemini API","c":"pollinations_api","p":"pollinations_api","m":"gemini"},"pa_mistral":{"e":"🔑","n":"PollAPI-Mistral","d":"Mistral API","c":"pollinations_api","p":"pollinations_api","m":"mistral"},"pa_deepseek":{"e":"🔑","n":"PollAPI-DeepSeek","d":"DeepSeek API","c":"pollinations_api","p":"pollinations_api","m":"deepseek"}}
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
 def __init__(self,url,key):self.url=url;self.key=key
 def _h(self):return{"x-admin-key":self.key,"Content-Type":"application/json"}
 def _get(self,ep):
  if not self.url:return{"success":False}
  try:r=get_requests().get(f"{self.url}{ep}",headers=self._h(),timeout=15);return r.json()if r.status_code==200 else{"success":False}
  except:return{"success":False}
 def _post(self,ep,data=None):
  if not self.url:return{"success":False}
  try:r=get_requests().post(f"{self.url}{ep}",headers=self._h(),json=data or{},timeout=15);return r.json()if r.status_code in[200,201]else{"success":False}
  except:return{"success":False}
 def health(self):
  try:r=get_requests().get(f"{self.url}/api/keepalive",timeout=10);return{"success":r.status_code==200}
  except:return{"success":False}
 def stats(self):return self._get("/api/admin/stats")
 def bans(self):return self._get("/api/admin/bans")
 def add_ban(self,hwid=None,ip=None,pid=None,reason="Via Discord"):
  d={"reason":reason}
  if hwid:d["hwid"]=hwid
  if ip:d["ip"]=ip
  if pid:d["playerId"]=pid
  return self._post("/api/admin/bans",d)
shield=ShieldAPI(SHIELD_URL,SHIELD_ADMIN_KEY)
class Database:
 def __init__(self,path="bot.db"):
  self.conn=sqlite3.connect(path,check_same_thread=False);self.lock=threading.Lock()
  self.conn.executescript('''CREATE TABLE IF NOT EXISTS stats(id INTEGER PRIMARY KEY,cmd TEXT,uid INTEGER,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS blacklist(uid INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS user_prefs(uid INTEGER PRIMARY KEY,img_model TEXT DEFAULT "flux");
CREATE TABLE IF NOT EXISTS dump_cache(url TEXT PRIMARY KEY,content TEXT,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);''')
 def stat(self,cmd,uid):
  with self.lock:self.conn.execute('INSERT INTO stats(cmd,uid)VALUES(?,?)',(cmd,uid));self.conn.commit()
 def banned(self,uid):
  with self.lock:return self.conn.execute('SELECT 1 FROM blacklist WHERE uid=?',(uid,)).fetchone()is not None
 def ban(self,uid):
  with self.lock:self.conn.execute('INSERT OR IGNORE INTO blacklist VALUES(?)',(uid,));self.conn.commit()
 def unban(self,uid):
  with self.lock:self.conn.execute('DELETE FROM blacklist WHERE uid=?',(uid,));self.conn.commit()
 def get_img(self,uid):
  with self.lock:r=self.conn.execute('SELECT img_model FROM user_prefs WHERE uid=?',(uid,)).fetchone();return r[0]if r else"flux"
 def set_img(self,uid,m):
  with self.lock:self.conn.execute('INSERT OR REPLACE INTO user_prefs VALUES(?,?)',(uid,m));self.conn.commit()
 def get_stats(self):
  with self.lock:
   total=self.conn.execute('SELECT COUNT(*)FROM stats').fetchone()[0]
   today=self.conn.execute('SELECT COUNT(*)FROM stats WHERE ts>datetime("now","-1 day")').fetchone()[0]
   return{"total":total,"today":today}
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
def get_system_prompt():
 p=get_panel_setting("system_prompt")
 return p if p else"You are a helpful AI assistant. Default: Bahasa Indonesia."
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
async def send_ai_response(ch,content,model_id):
 info=get_model_info(model_id)
 chunks=split_msg(content)
 footer=f"\n\n─────────────────────\n{info['e']} **{info['n']}** • `{info['m'][:30]}`"
 if len(chunks)==1:await ch.send(f"{chunks[0]}{footer}")
 else:
  for i,c in enumerate(chunks):
   if i==len(chunks)-1:await ch.send(f"{c}{footer}")
   else:await ch.send(c)
@bot.event
async def on_ready():
 logger.info(f"Bot ready:{bot.user}|Servers:{len(bot.guilds)}");fetch_panel_config()
 await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening,name=f"{PREFIX}help"))
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
   if not ok:return await msg.channel.send(f"⏳ Wait {rem:.0f}s",delete_after=3)
   async with msg.channel.typing():
    resp,used=ask_ai(content,msg.author.id)
    await send_ai_response(msg.channel,resp,used)
    db.stat("ai",msg.author.id)
  return
 await bot.process_commands(msg)
@bot.command(name="ai",aliases=["a","chat"])
async def cmd_ai(ctx,*,prompt:str=None):
 if db.banned(ctx.author.id):return
 if not prompt:return await ctx.send(f"Usage:`{PREFIX}ai <question>`",delete_after=10)
 ok,rem=rl.check(ctx.author.id,"ai",5)
 if not ok:return await ctx.send(f"⏳ Wait {rem:.0f}s",delete_after=3)
 async with ctx.typing():
  resp,used=ask_ai(prompt,ctx.author.id)
  await send_ai_response(ctx.channel,resp,used)
  db.stat("ai",ctx.author.id)
 try:await ctx.message.delete()
 except:pass
@bot.command(name="cm",aliases=["currentmodel","mymodel"])
async def cmd_cm(ctx):
 model_id=get_model_for_user(ctx.author.id)
 info=get_model_info(model_id)
 embed=discord.Embed(title="🤖 Your Current Model",color=0x5865F2)
 embed.add_field(name="Model",value=f"{info['e']} **{info['n']}**",inline=True)
 embed.add_field(name="Provider",value=f"`{info['p']}`",inline=True)
 embed.add_field(name="Category",value=f"`{info['c']}`",inline=True)
 embed.add_field(name="API Model",value=f"`{info['m']}`",inline=False)
 embed.add_field(name="Description",value=info.get('d','N/A'),inline=False)
 embed.set_footer(text=f"Change model via Web Panel: {CONFIG_PANEL_URL or'Not configured'}")
 await ctx.send(embed=embed)
@bot.command(name="models",aliases=["lm","listmodels"])
async def cmd_lm(ctx):
 models=get_models()
 cats={"main":[],"openrouter":[],"pollinations_free":[],"pollinations_api":[],"custom":[]}
 for mid,m in models.items():
  c=m.get("c","main")
  if c not in cats:cats[c]=[]
  cats[c].append(f"{m['e']} `{mid}`")
 embed=discord.Embed(title="📋 Available Models",color=0x5865F2)
 names={"main":"⚡ Main","openrouter":"🌐 OpenRouter","pollinations_free":"🆓 Poll Free","pollinations_api":"🔑 Poll API","custom":"⚙️ Custom"}
 for cat,items in cats.items():
  if items:
   val="\n".join(items[:6])
   if len(items)>6:val+=f"\n+{len(items)-6} more"
   embed.add_field(name=f"{names.get(cat,cat)} ({len(items)})",value=val,inline=True)
 embed.set_footer(text=f"Set model via Web Panel")
 await ctx.send(embed=embed)
@bot.command(name="imagine",aliases=["img","image"])
async def cmd_img(ctx,*,prompt:str=None):
 if not is_owner(ctx.author.id):return await ctx.send("❌ Owner only!",delete_after=5)
 if not prompt:return await ctx.send(f"Usage:`{PREFIX}img <prompt>`",delete_after=5)
 ok,rem=rl.check(ctx.author.id,"img",15)
 if not ok:return await ctx.send(f"⏳ Wait {rem:.0f}s",delete_after=3)
 model=db.get_img(ctx.author.id);info=IMG_MODELS.get(model,("🎨","Flux",""))
 st=await ctx.send(f"🎨 Generating with {info[0]} **{info[1]}**...")
 try:
  data,err=await gen_image(prompt,model)
  if data:
   f=discord.File(io.BytesIO(data),"image.png")
   embed=discord.Embed(title=f"🎨 {prompt[:80]}",color=0x5865F2)
   embed.set_image(url="attachment://image.png");embed.set_footer(text=f"{info[0]} {info[1]}")
   await ctx.send(embed=embed,file=f);await st.delete();db.stat("img",ctx.author.id)
  else:await st.edit(content=f"❌ Failed:{err}")
 except Exception as e:await st.edit(content=f"❌ Error:{str(e)[:50]}")
@bot.command(name="imgmodel",aliases=["im"])
async def cmd_im(ctx,model:str=None):
 if not is_owner(ctx.author.id):return await ctx.send("❌ Owner only!",delete_after=5)
 if model and model in IMG_MODELS:
  db.set_img(ctx.author.id,model);info=IMG_MODELS[model]
  return await ctx.send(f"✅ Image model: {info[0]} **{info[1]}**",delete_after=5)
 curr=db.get_img(ctx.author.id)
 embed=discord.Embed(title="🎨 Image Models",color=0x5865F2)
 for k,v in IMG_MODELS.items():embed.add_field(name=f"{v[0]} {v[1]}",value=f"{'✅'if k==curr else'⚪'} `{PREFIX}im {k}`",inline=True)
 await ctx.send(embed=embed)
@bot.command(name="shield",aliases=["sh"])
async def cmd_shield(ctx):
 if not is_owner(ctx.author.id):return await ctx.send("❌ Owner only!",delete_after=5)
 st=shield.health()
 embed=discord.Embed(title="🛡️ Shield",color=0x2ECC71 if st.get("success")else 0xE74C3C)
 embed.add_field(name="Status",value="🟢 ONLINE"if st.get("success")else"🔴 OFFLINE",inline=True)
 if st.get("success"):
  stats=shield.stats()
  if isinstance(stats,dict):
   for k,v in list(stats.items())[:6]:
    if k not in["success","error"]:embed.add_field(name=k.replace("_"," ").title(),value=f"`{v}`",inline=True)
 await ctx.send(embed=embed)
@bot.command(name="sync",aliases=["resync"])
async def cmd_sync(ctx):
 if not is_owner(ctx.author.id):return await ctx.send("❌ Owner only!",delete_after=5)
 st=await ctx.send("🔄 Syncing...")
 config=fetch_panel_config(force=True)
 if config and config.get("last_fetch",0)>0:
  embed=discord.Embed(title="✅ Synced",color=0x2ECC71)
  embed.add_field(name="Keys",value=f"`{len(config.get('keys',{}))}`",inline=True)
  embed.add_field(name="Models",value=f"`{len(config.get('models',{}))}`",inline=True)
  embed.add_field(name="Users",value=f"`{len(config.get('user_models',{}))}`",inline=True)
  await st.edit(content=None,embed=embed)
 else:await st.edit(content="❌ Failed")
@bot.command(name="clear",aliases=["reset"])
async def cmd_clear(ctx):
 mem.clear(ctx.author.id);await ctx.send("🧹 Cleared!",delete_after=5)
@bot.command(name="ping",aliases=["p"])
async def cmd_ping(ctx):
 model_id=get_model_for_user(ctx.author.id);info=get_model_info(model_id)
 embed=discord.Embed(title="🏓 Pong!",color=0x2ECC71)
 embed.add_field(name="Latency",value=f"`{round(bot.latency*1000)}ms`",inline=True)
 embed.add_field(name="Model",value=f"{info['e']} {info['n']}",inline=True)
 await ctx.send(embed=embed)
@bot.command(name="status")
async def cmd_status(ctx):
 if not is_owner(ctx.author.id):return await ctx.send("❌ Owner only!",delete_after=5)
 config=fetch_panel_config();panel_ok=config and config.get("last_fetch",0)>0
 embed=discord.Embed(title="📊 Status",color=0x5865F2)
 embed.add_field(name="🌐 Panel",value=f"{'✅'if panel_ok else'❌'}",inline=True)
 embed.add_field(name="🛡️ Shield",value=f"{'✅'if shield.health().get('success')else'❌'}",inline=True)
 embed.add_field(name="📈 Commands",value=f"`{db.get_stats()['total']}`",inline=True)
 keys=["groq","cerebras","sambanova","openrouter","mistral","together","pollinations"]
 kst="\n".join([f"{'✅'if get_api_key(k)else'❌'} {k.title()}"for k in keys])
 embed.add_field(name="🔑 Keys",value=kst,inline=True)
 embed.add_field(name="⚙️ Config",value=f"Default:`{get_default_model()}`\nModels:`{len(get_models())}`\nServers:`{len(bot.guilds)}`",inline=True)
 await ctx.send(embed=embed)
@bot.command(name="testai")
async def cmd_testai(ctx):
 if not is_owner(ctx.author.id):return await ctx.send("❌ Owner only!",delete_after=5)
 st=await ctx.send("🔄 Testing...")
 test=[{"role":"user","content":"Say OK"}];results=[]
 providers=[("Groq",lambda:call_groq(test),get_api_key("groq")),("Cerebras",lambda:call_cerebras(test),get_api_key("cerebras")),("SambaNova",lambda:call_sambanova(test),get_api_key("sambanova")),("OR",lambda:call_openrouter(test,"or_gemini"),get_api_key("openrouter")),("PollFree",lambda:call_pollinations_free(test,"poll_free"),True)]
 for n,f,k in providers:
  if not k:results.append(f"⚪{n}");continue
  try:r=f();results.append(f"✅{n}"if r else f"❌{n}")
  except:results.append(f"❌{n}")
 embed=discord.Embed(title="🧪 Test",description=" | ".join(results),color=0x5865F2)
 await st.edit(content=None,embed=embed)
@bot.command(name="blacklist",aliases=["bl","ban"])
async def cmd_bl(ctx,action:str=None,user:discord.User=None):
 if not is_owner(ctx.author.id):return
 if not action or not user:return await ctx.send(f"Usage:`{PREFIX}bl add/rem @user`",delete_after=10)
 if action in["add","ban"]:db.ban(user.id);await ctx.send(f"✅ Banned {user}",delete_after=5)
 elif action in["rem","remove","unban"]:db.unban(user.id);await ctx.send(f"✅ Unbanned {user}",delete_after=5)
@bot.command(name="stats")
async def cmd_stats(ctx):
 s=db.get_stats()
 embed=discord.Embed(title="📈 Stats",color=0x5865F2)
 embed.add_field(name="Total",value=f"`{s['total']}`",inline=True)
 embed.add_field(name="Today",value=f"`{s['today']}`",inline=True)
 await ctx.send(embed=embed)
@bot.command(name="help",aliases=["h"])
async def cmd_help(ctx):
 embed=discord.Embed(title="📚 Help",color=0x5865F2)
 embed.add_field(name="💬 AI",value=f"`{PREFIX}ai <text>`\n`@{bot.user.name} <text>`",inline=False)
 embed.add_field(name="🤖 Models",value=f"`{PREFIX}cm` - Current model\n`{PREFIX}models` - List all\n*Set via Web Panel*",inline=True)
 if is_owner(ctx.author.id):
  embed.add_field(name="🎨 Image",value=f"`{PREFIX}img <prompt>`\n`{PREFIX}im [model]`",inline=True)
  embed.add_field(name="⚙️ Admin",value=f"`{PREFIX}status` `{PREFIX}testai`\n`{PREFIX}sync` `{PREFIX}bl` `{PREFIX}stats`",inline=True)
  embed.add_field(name="🛡️ Shield",value=f"`{PREFIX}sh` - Status",inline=True)
 embed.add_field(name="🔧 Utility",value=f"`{PREFIX}clear` `{PREFIX}ping`",inline=True)
 embed.set_footer(text=f"🌐 Config Panel: {CONFIG_PANEL_URL[:30] if CONFIG_PANEL_URL else 'Not set'}...")
 await ctx.send(embed=embed)
@bot.command(name="panel")
async def cmd_panel(ctx):
 if CONFIG_PANEL_URL:
  embed=discord.Embed(title="🌐 Config Panel",description=f"Manage models, API keys, and settings via web panel.",color=0x5865F2)
  embed.add_field(name="URL",value=f"`{CONFIG_PANEL_URL}`",inline=False)
  embed.add_field(name="Features",value="• Set Default Model\n• Set User Models\n• Manage API Keys\n• Add Custom Models\n• Bot Settings",inline=False)
  await ctx.send(embed=embed)
 else:await ctx.send("❌ Panel not configured",delete_after=5)
def run_flask():
 from flask import Flask,jsonify
 app=Flask(__name__)
 @app.route('/')
 def home():return f"Bot {bot.user} running!"if bot.user else"Starting..."
 @app.route('/health')
 def health():return jsonify({"status":"ok"})
 port=int(os.getenv("PORT",8080));app.run(host="0.0.0.0",port=port,debug=False,use_reloader=False)
if __name__=="__main__":
 keep_alive();PORT=int(os.getenv("PORT",8080))
 threading.Thread(target=run_flask,daemon=True).start()
 print("="*50);print("🚀 Bot Starting...")
 print(f"👑 Owners: {OWNER_IDS}");print(f"🌍 Default: {get_default_model()}")
 print(f"🛡️ Shield: {'✅'if SHIELD_URL else'❌'}");print(f"🌐 Panel: {'✅'if CONFIG_PANEL_URL else'❌'}")
 print("-"*50)
 for n,k in[("Groq","groq"),("Cerebras","cerebras"),("SambaNova","sambanova"),("OpenRouter","openrouter"),("Mistral","mistral"),("Together","together"),("Pollinations","pollinations")]:print(f"   {'✅'if get_api_key(k)else'❌'} {n}")
 print("="*50);bot.run(DISCORD_TOKEN,log_handler=None)