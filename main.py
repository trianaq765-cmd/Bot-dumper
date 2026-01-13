import discord,os,io,re,time,json,logging,sqlite3,random,threading,hashlib,asyncio
from collections import defaultdict
from dataclasses import dataclass
from discord.ext import commands
from discord import ui
from urllib.parse import quote
from functools import wraps
from datetime import datetime
try:
 from flask import Flask,request,jsonify,render_template_string
 HAS_FLASK=True
except:
 HAS_FLASK=False
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
WEB_ADMIN_KEY=os.getenv("WEB_ADMIN_KEY",os.getenv("ADMIN_KEY","admin123"))
WEB_PORT=int(os.getenv("PORT",8080))
if not DISCORD_TOKEN:print("DISCORD_TOKEN Missing");exit(1)
intents=discord.Intents.default()
intents.message_content=True
bot=commands.Bot(command_prefix=PREFIX,intents=intents,help_command=None)
class WebConfig:
 def __init__(self,path="bot_config.db"):
  self.conn=sqlite3.connect(path,check_same_thread=False)
  self.lock=threading.Lock()
  self._init()
 def _init(self):
  with self.lock:
   self.conn.executescript('''CREATE TABLE IF NOT EXISTS api_keys(name TEXT PRIMARY KEY,value TEXT NOT NULL,description TEXT,is_active INTEGER DEFAULT 1,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS ai_models(id TEXT PRIMARY KEY,provider TEXT NOT NULL,name TEXT NOT NULL,model_id TEXT NOT NULL,endpoint TEXT,category TEXT DEFAULT 'main',emoji TEXT DEFAULT '🤖',description TEXT,is_active INTEGER DEFAULT 1,priority INTEGER DEFAULT 100);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT,action TEXT,target TEXT,details TEXT,timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP);''')
   self.conn.commit()
 def get_key(self,name):
  with self.lock:r=self.conn.execute('SELECT value FROM api_keys WHERE name=? AND is_active=1',(name,)).fetchone();return r[0]if r else None
 def get_all_keys(self,masked=True):
  with self.lock:
   rows=self.conn.execute('SELECT name,value,description,is_active,updated_at FROM api_keys ORDER BY name').fetchall()
   result=[]
   for r in rows:
    v=r[1]
    if masked and v and len(v)>12:v=v[:4]+"*"*(len(v)-8)+v[-4:]
    elif masked and v:v="*"*len(v)
    result.append({"name":r[0],"value":v,"description":r[2]or"","is_active":bool(r[3]),"updated_at":r[4]})
   return result
 def set_key(self,name,value,desc=None):
  with self.lock:
   self.conn.execute('INSERT OR REPLACE INTO api_keys(name,value,description,is_active,updated_at)VALUES(?,?,?,1,CURRENT_TIMESTAMP)',(name,value,desc))
   self.conn.commit()
   self._log("SET_KEY",name)
   env_map={"groq":"GROQ_API_KEY","openrouter":"OPENROUTER_API_KEY","cerebras":"CEREBRAS_API_KEY","sambanova":"SAMBANOVA_API_KEY","cohere":"COHERE_API_KEY","cloudflare_token":"CLOUDFLARE_API_TOKEN","cloudflare_account":"CLOUDFLARE_ACCOUNT_ID","together":"TOGETHER_API_KEY","tavily":"TAVILY_API_KEY","mistral":"MISTRAL_API_KEY","replicate":"REPLICATE_API_TOKEN","huggingface":"HUGGINGFACE_API_KEY","moonshot":"MOONSHOT_API_KEY"}
   if name in env_map:os.environ[env_map[name]]=value
   return True
 def del_key(self,name):
  with self.lock:self.conn.execute('DELETE FROM api_keys WHERE name=?',(name,));self.conn.commit();self._log("DEL_KEY",name);return True
 def get_model(self,mid):
  with self.lock:
   r=self.conn.execute('SELECT * FROM ai_models WHERE id=?',(mid,)).fetchone()
   if r:return{"id":r[0],"provider":r[1],"name":r[2],"model_id":r[3],"endpoint":r[4],"category":r[5],"emoji":r[6],"description":r[7],"is_active":bool(r[8]),"priority":r[9]}
   return None
 def get_all_models(self,category=None):
  with self.lock:
   if category:rows=self.conn.execute('SELECT * FROM ai_models WHERE category=? ORDER BY priority,name',(category,)).fetchall()
   else:rows=self.conn.execute('SELECT * FROM ai_models ORDER BY category,priority,name').fetchall()
   return[{"id":r[0],"provider":r[1],"name":r[2],"model_id":r[3],"endpoint":r[4],"category":r[5],"emoji":r[6],"description":r[7],"is_active":bool(r[8]),"priority":r[9]}for r in rows]
 def add_model(self,mid,provider,name,model_id,endpoint=None,category="main",emoji="🤖",desc="",priority=100):
  with self.lock:self.conn.execute('INSERT OR REPLACE INTO ai_models(id,provider,name,model_id,endpoint,category,emoji,description,priority)VALUES(?,?,?,?,?,?,?,?,?)',(mid,provider,name,model_id,endpoint,category,emoji,desc,priority));self.conn.commit();self._log("ADD_MODEL",mid);return True
 def update_model(self,mid,**kw):
  with self.lock:
   allowed=["provider","name","model_id","endpoint","category","emoji","description","is_active","priority"]
   updates=[(k,v)for k,v in kw.items()if k in allowed and v is not None]
   if not updates:return False
   s=",".join([f"{k}=?"for k,_ in updates])
   vals=[v for _,v in updates]+[mid]
   self.conn.execute(f'UPDATE ai_models SET {s} WHERE id=?',vals);self.conn.commit();self._log("UPD_MODEL",mid);return True
 def del_model(self,mid):
  with self.lock:self.conn.execute('DELETE FROM ai_models WHERE id=?',(mid,));self.conn.commit();self._log("DEL_MODEL",mid);return True
 def get_setting(self,key,default=None):
  with self.lock:r=self.conn.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone();return r[0]if r else default
 def set_setting(self,key,value):
  with self.lock:self.conn.execute('INSERT OR REPLACE INTO settings(key,value)VALUES(?,?)',(key,str(value)));self.conn.commit();return True
 def get_all_settings(self):
  with self.lock:return{r[0]:r[1]for r in self.conn.execute('SELECT key,value FROM settings').fetchall()}
 def _log(self,action,target,details=""):
  try:self.conn.execute('INSERT INTO audit_log(action,target,details)VALUES(?,?,?)',(action,target,details));self.conn.commit()
  except:pass
 def get_logs(self,limit=100):
  with self.lock:return[{"id":r[0],"action":r[1],"target":r[2],"details":r[3],"timestamp":r[4]}for r in self.conn.execute('SELECT id,action,target,details,timestamp FROM audit_log ORDER BY timestamp DESC LIMIT ?',(limit,)).fetchall()]
 def clear_logs(self):
  with self.lock:self.conn.execute('DELETE FROM audit_log');self.conn.commit();return True
 def init_defaults(self):
  if self.get_all_models():return False
  defaults=[("groq","groq","Groq","llama-3.3-70b-versatile",None,"main","⚡","Llama 3.3 70B",10),("cerebras","cerebras","Cerebras","llama-3.3-70b",None,"main","🧠","Llama 3.3 70B",20),("sambanova","sambanova","SambaNova","Meta-Llama-3.3-70B-Instruct",None,"main","🦣","Llama 3.3 70B",30),("cloudflare","cloudflare","Cloudflare","@cf/meta/llama-3.3-70b-instruct-fp8-fast",None,"main","☁️","Llama 3.3 70B",40),("cohere","cohere","Cohere","command-r-plus-08-2024",None,"main","🔷","Command R+",50),("mistral","mistral","Mistral","mistral-small-latest",None,"main","Ⓜ️","Mistral Small",60),("together","together","Together","meta-llama/Llama-3.3-70B-Instruct-Turbo",None,"main","🤝","Llama 3.3",70),("moonshot","moonshot","Moonshot","moonshot-v1-8k",None,"main","🌙","Kimi 128K",80),("huggingface","huggingface","HuggingFace","mistralai/Mixtral-8x7B-Instruct-v0.1",None,"main","🤗","Mixtral 8x7B",90),("replicate","replicate","Replicate","meta/meta-llama-3.1-405b-instruct",None,"main","🔄","Llama 405B",100),("tavily","tavily","Tavily","search",None,"main","🔍","Search+Web",110),("or_llama","openrouter","OR-Llama","meta-llama/llama-3.3-70b-instruct:free",None,"openrouter","🦙","Llama 3.3 70B",10),("or_gemini","openrouter","OR-Gemini","google/gemini-2.0-flash-exp:free",None,"openrouter","💎","Gemini 2.0",20),("or_qwen","openrouter","OR-Qwen","qwen/qwen-2.5-72b-instruct:free",None,"openrouter","💻","Qwen 2.5 72B",30),("or_deepseek","openrouter","OR-DeepSeek","deepseek/deepseek-chat:free",None,"openrouter","🌊","DeepSeek",40),("or_mistral","openrouter","OR-Mistral","mistralai/mistral-nemo:free",None,"openrouter","🅼","Mistral Nemo",50),("p_openai","pollinations","Poll-OpenAI","openai-large",None,"pollinations","🤖","OpenAI Large",10),("p_claude","pollinations","Poll-Claude","claude-hybridspace",None,"pollinations","🎭","Claude",20),("p_gemini","pollinations","Poll-Gemini","gemini",None,"pollinations","💎","Gemini",30),("p_deepseek","pollinations","Poll-DeepSeek","deepseek",None,"pollinations","🐳","DeepSeek V3",40),("p_qwen","pollinations","Poll-Qwen","qwen-72b",None,"pollinations","📟","Qwen 72B",50),("p_llama","pollinations","Poll-Llama","llama-3.3-70b",None,"pollinations","🦙","Llama 3.3",60),("p_mistral","pollinations","Poll-Mistral","mistral",None,"pollinations","🅼","Mistral",70),("poll_free","pollinations","Poll-Free","free",None,"pollinations","🌸","Free Unlimited",80)]
  for m in defaults:self.add_model(*m)
  print(f"✅ Initialized {len(defaults)} models");return True
webconfig=WebConfig()
DASHBOARD='''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>🤖 Bot Panel</title><style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:system-ui;background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;min-height:100vh;padding:20px}.container{max-width:1200px;margin:0 auto}h1{text-align:center;margin-bottom:30px;background:linear-gradient(90deg,#00d4ff,#00ff88);-webkit-background-clip:text;-webkit-text-fill-color:transparent}.tabs{display:flex;gap:10px;justify-content:center;margin-bottom:20px;flex-wrap:wrap}.tab{padding:12px 24px;background:rgba(255,255,255,0.1);border:none;color:#fff;border-radius:10px;cursor:pointer}.tab:hover,.tab.active{background:linear-gradient(135deg,#00d4ff,#00ff88);color:#000}.panel{display:none;background:rgba(255,255,255,0.05);padding:25px;border-radius:15px}.panel.active{display:block}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:20px;margin-top:20px}.card{background:rgba(255,255,255,0.08);padding:20px;border-radius:12px;border:1px solid rgba(255,255,255,0.1)}.card:hover{border-color:#00d4ff}.card h3{margin-bottom:12px;display:flex;align-items:center;gap:8px}.card code{background:#0a0a1a;padding:3px 8px;border-radius:5px;font-size:0.85em;word-break:break-all}.badge{padding:4px 10px;border-radius:15px;font-size:0.75em}.badge-main{background:#4caf50}.badge-openrouter{background:#2196f3}.badge-pollinations{background:#9c27b0}.status{width:10px;height:10px;border-radius:50%;margin-left:auto}.status.on{background:#4caf50}.status.off{background:#f44336}.btn{padding:10px 18px;border:none;border-radius:8px;cursor:pointer;margin:3px;font-size:0.9em}.btn-primary{background:#00d4ff;color:#000}.btn-success{background:#4caf50;color:#fff}.btn-danger{background:#f44336;color:#fff}.btn-secondary{background:rgba(255,255,255,0.1);color:#fff}.btn:hover{opacity:0.85}input,select,textarea{width:100%;padding:12px;margin:8px 0;background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.2);color:#fff;border-radius:8px}input:focus,select:focus{border-color:#00d4ff;outline:none}label{color:#aaa;font-size:0.9em}.modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.85);justify-content:center;align-items:center;z-index:100;padding:20px}.modal.show{display:flex}.modal-box{background:#1a1a2e;padding:30px;border-radius:15px;width:100%;max-width:450px;max-height:80vh;overflow-y:auto}.modal-header{display:flex;justify-content:space-between;margin-bottom:20px}.close{background:none;border:none;color:#fff;font-size:28px;cursor:pointer}table{width:100%;border-collapse:collapse;margin-top:15px}th,td{padding:12px;text-align:left;border-bottom:1px solid rgba(255,255,255,0.1)}th{background:rgba(0,0,0,0.3)}.alert{padding:15px;border-radius:10px;margin-bottom:20px}.alert-success{background:rgba(76,175,80,0.2);border:1px solid #4caf50}.alert-error{background:rgba(244,67,54,0.2);border:1px solid #f44336}.header-row{display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;flex-wrap:wrap;gap:10px}</style></head><body><div class="container"><h1>🤖 Bot Control Panel</h1><div class="tabs"><button class="tab active" onclick="showTab('keys')">🔑 API Keys</button><button class="tab" onclick="showTab('models')">🤖 Models</button><button class="tab" onclick="showTab('settings')">⚙️ Settings</button><button class="tab" onclick="showTab('logs')">📋 Logs</button></div><div id="alert"></div><div id="keys" class="panel active"><div class="header-row"><h2>🔑 API Keys</h2><button class="btn btn-primary" onclick="openModal('keyModal')">+ Add Key</button></div><div id="keysList" class="grid"></div></div><div id="models" class="panel"><div class="header-row"><h2>🤖 AI Models</h2><div><select id="catFilter" onchange="loadModels()" style="width:auto;margin-right:10px"><option value="">All</option><option value="main">Main</option><option value="openrouter">OpenRouter</option><option value="pollinations">Pollinations</option></select><button class="btn btn-primary" onclick="openModal('modelModal')">+ Add Model</button></div></div><div id="modelsList" class="grid"></div></div><div id="settings" class="panel"><h2 style="margin-bottom:20px">⚙️ Settings</h2><div class="grid"><div class="card"><h3>🌍 Default Model</h3><select id="defaultModel" onchange="saveSetting('default_model',this.value)"></select></div><div class="card"><h3>📝 Bot Prefix</h3><input id="prefix" value="." maxlength="3"><button class="btn btn-success" onclick="saveSetting('bot_prefix',document.getElementById('prefix').value)" style="margin-top:10px">Save</button></div><div class="card"><h3>🔄 Init Models</h3><p style="color:#888;margin:10px 0">Load default AI models</p><button class="btn btn-secondary" onclick="initModels()">Initialize</button></div></div></div><div id="logs" class="panel"><div class="header-row"><h2>📋 Audit Logs</h2><button class="btn btn-danger" onclick="clearLogs()">Clear All</button></div><table><thead><tr><th>Time</th><th>Action</th><th>Target</th><th>Details</th></tr></thead><tbody id="logsTable"></tbody></table></div></div><div id="keyModal" class="modal"><div class="modal-box"><div class="modal-header"><h3>🔑 Add API Key</h3><button class="close" onclick="closeModal('keyModal')">&times;</button></div><form onsubmit="addKey(event)"><label>Provider</label><select id="keyName" required><option value="">Select...</option><option value="groq">Groq</option><option value="openrouter">OpenRouter</option><option value="cerebras">Cerebras</option><option value="sambanova">SambaNova</option><option value="cohere">Cohere</option><option value="cloudflare_token">Cloudflare Token</option><option value="cloudflare_account">Cloudflare Account</option><option value="together">Together</option><option value="tavily">Tavily</option><option value="mistral">Mistral</option><option value="replicate">Replicate</option><option value="huggingface">HuggingFace</option><option value="moonshot">Moonshot</option></select><label>API Key</label><input type="password" id="keyValue" required placeholder="sk-xxx..."><label>Description</label><input id="keyDesc" placeholder="Optional"><button type="submit" class="btn btn-success" style="width:100%;margin-top:15px">Save Key</button></form></div></div><div id="modelModal" class="modal"><div class="modal-box"><div class="modal-header"><h3>🤖 Add Model</h3><button class="close" onclick="closeModal('modelModal')">&times;</button></div><form onsubmit="addModel(event)"><label>Model ID</label><input id="mId" required placeholder="my_model"><label>Provider</label><select id="mProvider" required><option value="">Select...</option><option value="groq">Groq</option><option value="openrouter">OpenRouter</option><option value="cerebras">Cerebras</option><option value="sambanova">SambaNova</option><option value="cloudflare">Cloudflare</option><option value="cohere">Cohere</option><option value="mistral">Mistral</option><option value="together">Together</option><option value="pollinations">Pollinations</option><option value="huggingface">HuggingFace</option><option value="replicate">Replicate</option><option value="moonshot">Moonshot</option><option value="tavily">Tavily</option></select><label>Display Name</label><input id="mName" required placeholder="My Model"><label>API Model ID</label><input id="mModelId" required placeholder="llama-3.3-70b"><label>Category</label><select id="mCat"><option value="main">Main</option><option value="openrouter">OpenRouter</option><option value="pollinations">Pollinations</option></select><label>Emoji</label><input id="mEmoji" value="🤖" maxlength="4"><label>Description</label><input id="mDesc" placeholder="Description"><button type="submit" class="btn btn-success" style="width:100%;margin-top:15px">Add Model</button></form></div></div><div id="editModal" class="modal"><div class="modal-box"><div class="modal-header"><h3>✏️ Edit Model</h3><button class="close" onclick="closeModal('editModal')">&times;</button></div><form onsubmit="updateModel(event)"><input type="hidden" id="eId"><label>Provider</label><select id="eProvider"><option value="groq">Groq</option><option value="openrouter">OpenRouter</option><option value="cerebras">Cerebras</option><option value="sambanova">SambaNova</option><option value="cloudflare">Cloudflare</option><option value="cohere">Cohere</option><option value="mistral">Mistral</option><option value="together">Together</option><option value="pollinations">Pollinations</option><option value="huggingface">HuggingFace</option><option value="replicate">Replicate</option><option value="moonshot">Moonshot</option><option value="tavily">Tavily</option></select><label>Display Name</label><input id="eName" required><label>API Model ID</label><input id="eModelId" required><label>Category</label><select id="eCat"><option value="main">Main</option><option value="openrouter">OpenRouter</option><option value="pollinations">Pollinations</option></select><label>Emoji</label><input id="eEmoji" maxlength="4"><label>Description</label><input id="eDesc"><button type="submit" class="btn btn-success" style="width:100%;margin-top:15px">Update</button></form></div></div><script>const API='/api',KEY='{{key}}',H={'Content-Type':'application/json','X-Admin-Key':KEY};function showTab(id){document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));document.getElementById(id).classList.add('active');event.target.classList.add('active');if(id==='keys')loadKeys();if(id==='models')loadModels();if(id==='settings')loadSettings();if(id==='logs')loadLogs()}function openModal(id){document.getElementById(id).classList.add('show')}function closeModal(id){document.getElementById(id).classList.remove('show')}function alert(m,t='success'){document.getElementById('alert').innerHTML=`<div class="alert alert-${t}">${t==='success'?'✅':'❌'} ${m}</div>`;setTimeout(()=>document.getElementById('alert').innerHTML='',4000)}async function api(e,m='GET',d=null){const o={method:m,headers:H};if(d)o.body=JSON.stringify(d);try{const r=await fetch(API+e,o);return await r.json()}catch(x){return{success:false,error:x.message}}}async function loadKeys(){const d=await api('/keys');const c=document.getElementById('keysList');if(!d.keys||!d.keys.length){c.innerHTML='<p style="color:#888">No API keys yet. Click + Add Key</p>';return}c.innerHTML=d.keys.map(k=>`<div class="card"><h3>🔑 ${k.name}<span class="status ${k.is_active?'on':'off'}"></span></h3><p><code>${k.value}</code></p><p style="color:#666;font-size:0.85em">${k.description||''}</p><div style="margin-top:12px"><button class="btn btn-secondary" onclick="editKey('${k.name}')">Edit</button><button class="btn btn-danger" onclick="delKey('${k.name}')">Delete</button></div></div>`).join('')}async function addKey(e){e.preventDefault();const d=await api('/keys','POST',{name:document.getElementById('keyName').value,value:document.getElementById('keyValue').value,description:document.getElementById('keyDesc').value});if(d.success){alert('Key added!');closeModal('keyModal');loadKeys()}else alert(d.error,'error')}async function editKey(n){const v=prompt('New API key for '+n+':');if(v){await api('/keys/'+n,'PUT',{value:v});alert('Updated!');loadKeys()}}async function delKey(n){if(confirm('Delete '+n+'?')){await api('/keys/'+n,'DELETE');alert('Deleted!');loadKeys()}}async function loadModels(){const cat=document.getElementById('catFilter').value;const d=await api('/models'+(cat?'?category='+cat:''));const c=document.getElementById('modelsList');if(!d.models||!d.models.length){c.innerHTML='<p style="color:#888">No models. Click + Add or use Initialize in Settings</p>';return}c.innerHTML=d.models.map(m=>`<div class="card"><h3>${m.emoji} ${m.name}<span class="badge badge-${m.category}">${m.category}</span><span class="status ${m.is_active?'on':'off'}"></span></h3><p><b>ID:</b> <code>${m.id}</code></p><p><b>Provider:</b> ${m.provider}</p><p><b>Model:</b> <code>${m.model_id}</code></p><p style="color:#666">${m.description||''}</p><div style="margin-top:12px"><button class="btn btn-secondary" onclick='editM(${JSON.stringify(m)})'>Edit</button><button class="btn btn-${m.is_active?"danger":"success"}" onclick="toggleM('${m.id}',${!m.is_active})">${m.is_active?'Disable':'Enable'}</button><button class="btn btn-danger" onclick="delM('${m.id}')">Del</button></div></div>`).join('')}async function addModel(e){e.preventDefault();const d=await api('/models','POST',{id:document.getElementById('mId').value,provider:document.getElementById('mProvider').value,name:document.getElementById('mName').value,model_id:document.getElementById('mModelId').value,category:document.getElementById('mCat').value,emoji:document.getElementById('mEmoji').value||'🤖',description:document.getElementById('mDesc').value});if(d.success){alert('Model added!');closeModal('modelModal');loadModels()}else alert(d.error,'error')}function editM(m){document.getElementById('eId').value=m.id;document.getElementById('eProvider').value=m.provider;document.getElementById('eName').value=m.name;document.getElementById('eModelId').value=m.model_id;document.getElementById('eCat').value=m.category;document.getElementById('eEmoji').value=m.emoji;document.getElementById('eDesc').value=m.description||'';openModal('editModal')}async function updateModel(e){e.preventDefault();const id=document.getElementById('eId').value;const d=await api('/models/'+id,'PUT',{provider:document.getElementById('eProvider').value,name:document.getElementById('eName').value,model_id:document.getElementById('eModelId').value,category:document.getElementById('eCat').value,emoji:document.getElementById('eEmoji').value,description:document.getElementById('eDesc').value});if(d.success){alert('Updated!');closeModal('editModal');loadModels()}else alert(d.error,'error')}async function toggleM(id,a){await api('/models/'+id,'PUT',{is_active:a?1:0});loadModels()}async function delM(id){if(confirm('Delete '+id+'?')){await api('/models/'+id,'DELETE');loadModels()}}async function initModels(){if(confirm('Initialize default models?')){const d=await api('/models/init','POST');alert(d.message||'Done!');loadModels()}}async function loadSettings(){const[m,s]=await Promise.all([api('/models'),api('/settings')]);const sel=document.getElementById('defaultModel');if(m.models)sel.innerHTML=m.models.map(x=>`<option value="${x.id}">${x.emoji} ${x.name}</option>`).join('');if(s.settings?.default_model)sel.value=s.settings.default_model;if(s.settings?.bot_prefix)document.getElementById('prefix').value=s.settings.bot_prefix}async function saveSetting(k,v){await api('/settings','POST',{[k]:v});alert(k+' saved!')}async function loadLogs(){const d=await api('/logs');document.getElementById('logsTable').innerHTML=(d.logs||[]).map(l=>`<tr><td>${l.timestamp||''}</td><td><code>${l.action}</code></td><td>${l.target}</td><td style="color:#666">${l.details||''}</td></tr>`).join('')||'<tr><td colspan="4" style="color:#666;text-align:center">No logs</td></tr>'}async function clearLogs(){if(confirm('Clear all logs?')){await api('/logs','DELETE');loadLogs()}}document.querySelectorAll('.modal').forEach(m=>m.onclick=e=>{if(e.target===m)m.classList.remove('show')});loadKeys()</script></body></html>'''
def create_flask_app():
 if not HAS_FLASK:return None
 app=Flask(__name__)
 def auth(f):
  @wraps(f)
  def w(*a,**k):
   key=request.headers.get('X-Admin-Key')or request.args.get('key')
   if key!=WEB_ADMIN_KEY:return jsonify({"success":False,"error":"Unauthorized"}),401
   return f(*a,**k)
  return w
 @app.route('/')
 def index():
  key=request.args.get('key','')
  if key!=WEB_ADMIN_KEY:return'<html><head><title>Login</title><style>body{font-family:system-ui;background:#1a1a2e;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}.box{background:rgba(255,255,255,0.05);padding:40px;border-radius:15px;text-align:center}input{padding:15px;width:220px;border-radius:8px;border:1px solid #333;background:#0a0a1a;color:#fff;margin:10px 0}button{padding:15px 40px;background:#00d4ff;border:none;border-radius:8px;cursor:pointer;font-weight:bold}</style></head><body><form class="box" method="get"><h2>🔐 Login</h2><input name="key" type="password" placeholder="Admin Key" required><br><button>Enter</button></form></body></html>'
  return render_template_string(DASHBOARD,key=WEB_ADMIN_KEY)
 @app.route('/health')
 def health():return jsonify({"status":"ok","timestamp":datetime.now().isoformat()})
 @app.route('/api/keys',methods=['GET'])
 @auth
 def get_keys():return jsonify({"success":True,"keys":webconfig.get_all_keys()})
 @app.route('/api/keys',methods=['POST'])
 @auth
 def add_key():d=request.json or{};webconfig.set_key(d.get('name',''),d.get('value',''),d.get('description'));return jsonify({"success":True})
 @app.route('/api/keys/<name>',methods=['PUT'])
 @auth
 def upd_key(name):d=request.json or{};webconfig.set_key(name,d.get('value',''),d.get('description'));return jsonify({"success":True})
 @app.route('/api/keys/<name>',methods=['DELETE'])
 @auth
 def del_key(name):webconfig.del_key(name);return jsonify({"success":True})
 @app.route('/api/models',methods=['GET'])
 @auth
 def get_models():return jsonify({"success":True,"models":webconfig.get_all_models(request.args.get('category'))})
 @app.route('/api/models',methods=['POST'])
 @auth
 def add_model():d=request.json or{};webconfig.add_model(d.get('id'),d.get('provider'),d.get('name'),d.get('model_id'),d.get('endpoint'),d.get('category','main'),d.get('emoji','🤖'),d.get('description',''));return jsonify({"success":True})
 @app.route('/api/models/init',methods=['POST'])
 @auth
 def init_models():r=webconfig.init_defaults();return jsonify({"success":True,"message":"Initialized"if r else"Already exists"})
 @app.route('/api/models/<mid>',methods=['PUT'])
 @auth
 def upd_model(mid):webconfig.update_model(mid,**(request.json or{}));return jsonify({"success":True})
 @app.route('/api/models/<mid>',methods=['DELETE'])
 @auth
 def del_model(mid):webconfig.del_model(mid);return jsonify({"success":True})
 @app.route('/api/settings',methods=['GET'])
 @auth
 def get_settings():return jsonify({"success":True,"settings":webconfig.get_all_settings()})
 @app.route('/api/settings',methods=['POST'])
 @auth
 def save_settings():
  for k,v in(request.json or{}).items():webconfig.set_setting(k,v)
  return jsonify({"success":True})
 @app.route('/api/logs',methods=['GET'])
 @auth
 def get_logs():return jsonify({"success":True,"logs":webconfig.get_logs()})
 @app.route('/api/logs',methods=['DELETE'])
 @auth
 def clr_logs():webconfig.clear_logs();return jsonify({"success":True})
 return app
_groq=None
_requests=None
_curl=None
_cloudscraper=None
def get_groq():
 global _groq
 if _groq is None:
  k=get_api_key("groq")
  if k:
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
 k=webconfig.get_key(name)
 if k:return k
 mapping={"groq":KEY_GROQ,"openrouter":KEY_OPENROUTER,"cerebras":KEY_CEREBRAS,"sambanova":KEY_SAMBANOVA,"cohere":KEY_COHERE,"cloudflare_token":CF_API_TOKEN,"cloudflare_account":CF_ACCOUNT_ID,"together":KEY_TOGETHER,"tavily":KEY_TAVILY,"mistral":KEY_MISTRAL,"replicate":KEY_REPLICATE,"huggingface":KEY_HUGGINGFACE,"moonshot":KEY_MOONSHOT,"pollinations":KEY_POLLINATIONS}
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
 def add_ban(self,hwid=None,ip=None,pid=None,reason="Via Discord"):d={"reason":reason};d.update({"hwid":hwid}if hwid else{});d.update({"ip":ip}if ip else{});d.update({"playerId":pid}if pid else{});return self._post("/api/admin/bans",d)
 def rem_ban(self,bid):return self._del(f"/api/admin/bans/{bid}")
 def add_wl(self,t,v):return self._post("/api/admin/whitelist",{"type":t,"value":v})
 def rem_wl(self,t,v):return self._post("/api/admin/whitelist/remove",{"type":t,"value":v})
 def suspend(self,t,v,reason="Via Discord",dur=None):d={"type":t,"value":v,"reason":reason};d.update({"duration":dur}if dur else{});return self._post("/api/admin/suspend",d)
 def unsuspend(self,t,v):return self._post("/api/admin/unsuspend",{"type":t,"value":v})
 def kill(self,sid,reason="Via Discord"):return self._post("/api/admin/kill-session",{"sessionId":sid,"reason":reason})
 def clear_sessions(self):return self._post("/api/admin/sessions/clear",{})
 def clear_logs(self):return self._post("/api/admin/logs/clear",{})
 def clear_cache(self):return self._post("/api/admin/cache/clear",{})
shield=ShieldAPI(SHIELD_URL,SHIELD_ADMIN_KEY)
class Database:
 def __init__(self,path="bot.db"):
  self.conn=sqlite3.connect(path,check_same_thread=False);self.lock=threading.Lock()
  self.conn.executescript('''CREATE TABLE IF NOT EXISTS user_prefs(uid INTEGER PRIMARY KEY,model TEXT DEFAULT "groq",img_model TEXT DEFAULT "flux");CREATE TABLE IF NOT EXISTS bot_settings(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE IF NOT EXISTS stats(id INTEGER PRIMARY KEY,cmd TEXT,uid INTEGER,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS blacklist(uid INTEGER PRIMARY KEY);CREATE TABLE IF NOT EXISTS allowed_users(uid INTEGER PRIMARY KEY,allowed_models TEXT DEFAULT "groq");CREATE TABLE IF NOT EXISTS dump_cache(url TEXT PRIMARY KEY,content TEXT,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);''')
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
MODELS={"groq":{"e":"⚡","n":"Groq","d":"Llama 3.3 70B","c":"main","p":"groq","m":"llama-3.3-70b-versatile"},"cerebras":{"e":"🧠","n":"Cerebras","d":"Llama 3.3 70B","c":"main","p":"cerebras","m":"llama-3.3-70b"},"sambanova":{"e":"🦣","n":"SambaNova","d":"Llama 3.3 70B","c":"main","p":"sambanova","m":"Meta-Llama-3.3-70B-Instruct"},"cloudflare":{"e":"☁️","n":"Cloudflare","d":"Llama 3.3 70B","c":"main","p":"cloudflare","m":"@cf/meta/llama-3.3-70b-instruct-fp8-fast"},"cohere":{"e":"🔷","n":"Cohere","d":"Command R+","c":"main","p":"cohere","m":"command-r-plus-08-2024"},"mistral":{"e":"Ⓜ️","n":"Mistral","d":"Mistral Small","c":"main","p":"mistral","m":"mistral-small-latest"},"together":{"e":"🤝","n":"Together","d":"Llama 3.3","c":"main","p":"together","m":"meta-llama/Llama-3.3-70B-Instruct-Turbo"},"moonshot":{"e":"🌙","n":"Moonshot","d":"Kimi 128K","c":"main","p":"moonshot","m":"moonshot-v1-8k"},"huggingface":{"e":"🤗","n":"HuggingFace","d":"Mixtral 8x7B","c":"main","p":"huggingface","m":"mistralai/Mixtral-8x7B-Instruct-v0.1"},"replicate":{"e":"🔄","n":"Replicate","d":"Llama 405B","c":"main","p":"replicate","m":"meta/meta-llama-3.1-405b-instruct"},"tavily":{"e":"🔍","n":"Tavily","d":"Search","c":"main","p":"tavily","m":"search"},"or_llama":{"e":"🦙","n":"OR-Llama","d":"Llama 3.3","c":"openrouter","p":"openrouter","m":"meta-llama/llama-3.3-70b-instruct:free"},"or_gemini":{"e":"💎","n":"OR-Gemini","d":"Gemini 2.0","c":"openrouter","p":"openrouter","m":"google/gemini-2.0-flash-exp:free"},"or_qwen":{"e":"💻","n":"OR-Qwen","d":"Qwen 2.5 72B","c":"openrouter","p":"openrouter","m":"qwen/qwen-2.5-72b-instruct:free"},"or_deepseek":{"e":"🌊","n":"OR-DeepSeek","d":"DeepSeek","c":"openrouter","p":"openrouter","m":"deepseek/deepseek-chat:free"},"or_mistral":{"e":"🅼","n":"OR-Mistral","d":"Mistral Nemo","c":"openrouter","p":"openrouter","m":"mistralai/mistral-nemo:free"},"p_openai":{"e":"🤖","n":"Poll-OpenAI","d":"OpenAI","c":"pollinations","p":"pollinations","m":"openai-large"},"p_claude":{"e":"🎭","n":"Poll-Claude","d":"Claude","c":"pollinations","p":"pollinations","m":"claude-hybridspace"},"p_gemini":{"e":"💎","n":"Poll-Gemini","d":"Gemini","c":"pollinations","p":"pollinations","m":"gemini"},"p_deepseek":{"e":"🐳","n":"Poll-DeepSeek","d":"DeepSeek V3","c":"pollinations","p":"pollinations","m":"deepseek"},"p_qwen":{"e":"📟","n":"Poll-Qwen","d":"Qwen 72B","c":"pollinations","p":"pollinations","m":"qwen-72b"},"p_llama":{"e":"🦙","n":"Poll-Llama","d":"Llama 3.3","c":"pollinations","p":"pollinations","m":"llama-3.3-70b"},"p_mistral":{"e":"🅼","n":"Poll-Mistral","d":"Mistral","c":"pollinations","p":"pollinations","m":"mistral"},"poll_free":{"e":"🌸","n":"Poll-Free","d":"Free","c":"pollinations","p":"pollinations","m":"free"}}
IMG_MODELS={"flux":("🎨","Flux","Standard"),"flux_pro":("⚡","Flux Pro","Pro"),"turbo":("🚀","Turbo","Fast"),"dalle":("🤖","DALL-E 3","OpenAI"),"sdxl":("🖼️","SDXL","SD")}
ALL_MODELS=list(MODELS.keys())
def is_owner(uid):return uid in OWNER_IDS
def get_public_default():return db.get_setting("public_default")or webconfig.get_setting("default_model")or"groq"
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
def call_moonshot(msgs):
 k=get_api_key("moonshot")
 if not k:return None
 try:r=get_requests().post("https://api.moonshot.cn/v1/chat/completions",headers={"Authorization":f"Bearer {k}","Content-Type":"application/json"},json={"model":MODELS["moonshot"]["m"],"messages":msgs,"max_tokens":4096},timeout=60);return r.json()["choices"][0]["message"]["content"]if r.status_code==200 else None
 except Exception as e:logger.error(f"Moonshot:{e}");return None
def call_huggingface(msgs):
 k=get_api_key("huggingface")
 if not k:return None
 try:prompt="\n".join([f"{m['role']}:{m['content']}"for m in msgs[-5:]]);r=get_requests().post(f"https://api-inference.huggingface.co/models/{MODELS['huggingface']['m']}",headers={"Authorization":f"Bearer {k}"},json={"inputs":prompt,"parameters":{"max_new_tokens":1000,"return_full_text":False}},timeout=60);d=r.json();return d[0].get("generated_text","").strip()if r.status_code==200 and isinstance(d,list)and d else None
 except Exception as e:logger.error(f"HF:{e}");return None
def call_replicate(msgs):
 k=get_api_key("replicate")
 if not k:return None
 try:
  prompt="\n".join([f"{m['role']}:{m['content']}"for m in msgs[-5:]]);r=get_requests().post(f"https://api.replicate.com/v1/models/{MODELS['replicate']['m']}/predictions",headers={"Authorization":f"Bearer {k}","Content-Type":"application/json"},json={"input":{"prompt":prompt,"max_tokens":2000}},timeout=15)
  if r.status_code in[200,201]:
   pred=r.json();url=f"https://api.replicate.com/v1/predictions/{pred.get('id')}"
   for _ in range(30):
    time.sleep(2);ch=get_requests().get(url,headers={"Authorization":f"Bearer {k}"},timeout=10)
    if ch.status_code==200:d=ch.json();
    if d.get("status")=="succeeded":return"".join(d.get("output",[]))
    if d.get("status")in["failed","canceled"]:return None
 except Exception as e:logger.error(f"Replicate:{e}")
 return None
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
 elif p=="moonshot":return call_moonshot(msgs),m.get("n","Moonshot")
 elif p=="huggingface":return call_huggingface(msgs),m.get("n","HuggingFace")
 elif p=="replicate":return call_replicate(msgs),m.get("n","Replicate")
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
  db.set_setting("public_default",self.values[0]);webconfig.set_setting("default_model",self.values[0]);m=MODELS.get(self.values[0],{})
  await i.response.send_message(f"✅ Default: {m.get('e','')} **{m.get('n','')}**",ephemeral=True)
class DefaultView(ui.View):
 def __init__(self):super().__init__(timeout=None);self.add_item(DefaultSelect())
class ShieldInfoSelect(ui.Select):
 def __init__(self):super().__init__(placeholder="View...",options=[discord.SelectOption(label="Stats",value="stats",emoji="📊"),discord.SelectOption(label="Sessions",value="sessions",emoji="🔄"),discord.SelectOption(label="Logs",value="logs",emoji="📋"),discord.SelectOption(label="Bans",value="bans",emoji="🚫"),discord.SelectOption(label="Whitelist",value="wl",emoji="✅"),discord.SelectOption(label="Suspended",value="sus",emoji="⏸️"),discord.SelectOption(label="Health",value="health",emoji="💚"),discord.SelectOption(label="Bot Stats",value="botstats",emoji="📈"),discord.SelectOption(label="Script",value="script",emoji="📜")],custom_id="shinfo")
 async def callback(self,i:discord.Interaction):
  if not is_owner(i.user.id):return await i.response.send_message("❌ Owner only!",ephemeral=True)
  await i.response.defer(ephemeral=True);a=self.values[0];embed=discord.Embed(color=0x3498DB)
  if a=="stats":d=shield.stats();embed.title="📊 Shield Stats";embed.description="\n".join([f"**{k}:** `{v}`"for k,v in d.items()if k not in["success","error"]])if isinstance(d,dict)and d.get("success")is not False else f"❌ {d.get('error','No data')}"
  elif a=="sessions":d=shield.sessions();embed.title="🔄 Sessions";ss=d.get("sessions",[])if isinstance(d,dict)else[];embed.description="\n".join([f"• `{s.get('id','?')[:15]}` - {s.get('userId','?')}"for s in ss[:10]])if ss else"✅ No sessions"
  elif a=="logs":d=shield.logs();embed.title="📋 Logs";ll=d.get("logs",[])if isinstance(d,dict)else[];embed.description="\n".join([f"• `{l.get('time','?')[:16]}` {l.get('service','?')}"for l in ll[:10]])if ll else"✅ No logs"
  elif a=="bans":d=shield.bans();embed.title="🚫 Bans";bb=d.get("bans",[])if isinstance(d,dict)else[];embed.description="\n".join([f"• #{b.get('id','?')} `{b.get('type','?')}:{str(b.get('value','?'))[:15]}`"for b in bb[:10]])if bb else"✅ No bans"
  elif a=="wl":d=shield.whitelist();embed.title="✅ Whitelist";ww=d.get("whitelist",[])if isinstance(d,dict)else[];embed.description="\n".join([f"• `{w.get('type','?')}:{str(w.get('value','?'))[:15]}`"for w in ww[:10]])if ww else"ℹ️ Empty"
  elif a=="sus":d=shield.suspended();embed.title="⏸️ Suspended";ss=d.get("suspended",[])if isinstance(d,dict)else[];embed.description="\n".join([f"• `{s.get('type','?')}:{str(s.get('value','?'))[:15]}`"for s in ss[:10]])if ss else"✅ None"
    elif a=="health":d=shield.health();embed.title="💚 Health";embed.description="✅ **ONLINE**"if d.get("success")else"❌ **OFFLINE**";embed.color=0x2ECC71 if d.get("success")else 0xE74C3C
  elif a=="botstats":s=db.get_stats();embed.title="📈 Bot Stats";embed.add_field(name="Total",value=f"`{s['total']}`",inline=True);embed.add_field(name="Today",value=f"`{s['today']}`",inline=True);embed.add_field(name="Users",value=f"`{s['users']}`",inline=True)
  elif a=="script":d=shield.script();
   if d.get("success")and d.get("script"):f=discord.File(io.BytesIO(d["script"].encode()),"loader.lua");return await i.followup.send("📜 Script:",file=f,ephemeral=True)
   else:embed.title="📜 Script";embed.description=f"❌ {d.get('error','Not available')}"
  await i.followup.send(embed=embed,ephemeral=True)
class ShieldActionSelect(ui.Select):
 def __init__(self):super().__init__(placeholder="Actions...",options=[discord.SelectOption(label="Clear Sessions",value="clear_s",emoji="🧹"),discord.SelectOption(label="Clear Logs",value="clear_l",emoji="🗑️"),discord.SelectOption(label="Clear Cache",value="clear_c",emoji="💾")],custom_id="shact")
 async def callback(self,i:discord.Interaction):
  if not is_owner(i.user.id):return await i.response.send_message("❌ Owner only!",ephemeral=True)
  await i.response.defer(ephemeral=True);a=self.values[0]
  if a=="clear_s":r=shield.clear_sessions();msg="Sessions cleared"
  elif a=="clear_l":r=shield.clear_logs();msg="Logs cleared"
  elif a=="clear_c":r=shield.clear_cache();msg="Cache cleared"
  else:r={"success":False};msg="Unknown"
  await i.followup.send(f"✅ {msg}!"if r.get("success")is not False else f"❌ {r.get('error','Failed')}",ephemeral=True)
class ShieldView(ui.View):
 def __init__(self):super().__init__(timeout=None);self.add_item(ShieldInfoSelect());self.add_item(ShieldActionSelect())
class ShieldManageSelect(ui.Select):
 def __init__(self):super().__init__(placeholder="Manage...",options=[discord.SelectOption(label="Ban Player",value="ban_p",emoji="👤"),discord.SelectOption(label="Ban HWID",value="ban_h",emoji="💻"),discord.SelectOption(label="Ban IP",value="ban_i",emoji="🌐"),discord.SelectOption(label="Unban",value="unban",emoji="🔓"),discord.SelectOption(label="Add Whitelist",value="add_wl",emoji="➕"),discord.SelectOption(label="Remove Whitelist",value="rem_wl",emoji="➖"),discord.SelectOption(label="Suspend",value="sus",emoji="⏸️"),discord.SelectOption(label="Unsuspend",value="unsus",emoji="▶️"),discord.SelectOption(label="Kill Session",value="kill",emoji="💀")],custom_id="shmng")
 async def callback(self,i:discord.Interaction):
  if not is_owner(i.user.id):return await i.response.send_message("❌ Owner only!",ephemeral=True)
  a=self.values[0];titles={"ban_p":"Ban Player","ban_h":"Ban HWID","ban_i":"Ban IP","unban":"Unban","add_wl":"Add Whitelist","rem_wl":"Remove Whitelist","sus":"Suspend","unsus":"Unsuspend","kill":"Kill Session"}
  class ActionModal(ui.Modal,title=titles.get(a,"Action")):
   val=ui.TextInput(label="Value",placeholder="ID/HWID/IP...",required=True)
   reason=ui.TextInput(label="Reason",placeholder="Optional",required=False,default="Via Discord")
   def __init__(s,act):super().__init__();s.act=act
   async def on_submit(s,mi:discord.Interaction):
    v=s.val.value.strip();r=s.reason.value.strip()or"Via Discord";res={"success":False}
    if s.act=="ban_p":res=shield.add_ban(pid=v,reason=r)
    elif s.act=="ban_h":res=shield.add_ban(hwid=v,reason=r)
    elif s.act=="ban_i":res=shield.add_ban(ip=v,reason=r)
    elif s.act=="unban":res=shield.rem_ban(v)
    elif s.act=="add_wl":p=v.split(":",1);res=shield.add_wl(p[0]if len(p)>1 else"userId",p[-1])
    elif s.act=="rem_wl":p=v.split(":",1);res=shield.rem_wl(p[0]if len(p)>1 else"userId",p[-1])
    elif s.act=="sus":p=v.split(":",1);res=shield.suspend(p[0]if len(p)>1 else"userId",p[-1],r)
    elif s.act=="unsus":p=v.split(":",1);res=shield.unsuspend(p[0]if len(p)>1 else"userId",p[-1])
    elif s.act=="kill":res=shield.kill(v,r)
    await mi.response.send_message(f"✅ Done: `{v}`"if res.get("success")is not False else f"❌ {res.get('error','Failed')}",ephemeral=True)
  await i.response.send_modal(ActionModal(a))
class ShieldManageView(ui.View):
 def __init__(self):super().__init__(timeout=None);self.add_item(ShieldManageSelect())
def split_msg(txt,lim=1950):
 if not txt:return[""]
 chunks=[]
 while len(txt)>lim:sp=txt.rfind('\n',0,lim);sp=lim if sp==-1 else sp;chunks.append(txt[:sp]);txt=txt[sp:].lstrip()
 if txt:chunks.append(txt)
 return chunks
async def send_resp(ch,content):
 for c in split_msg(content):await ch.send(c)
@bot.event
async def on_ready():
 logger.info(f"Bot ready: {bot.user} | Servers: {len(bot.guilds)}")
 await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening,name=f"{PREFIX}help"))
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
@bot.command(name="ai",aliases=["a","chat"])
async def cmd_ai(ctx,*,prompt:str=None):
 if db.banned(ctx.author.id)or not prompt:return
 ok,_=rl.check(ctx.author.id,"ai",5)
 if ok:
  async with ctx.typing():resp,_=ask_ai(prompt,ctx.author.id);await send_resp(ctx.channel,resp);db.stat("ai",ctx.author.id)
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
 if result["success"]:
  content=result["content"];ext="lua"if"local "in content[:500]else"txt"
  f=discord.File(io.BytesIO(content.encode()),f"dump.{ext}")
  await ctx.send(f"✅ {result['method']} | {len(content):,} bytes",file=f);await st.delete();db.stat("dump",ctx.author.id)
 else:await st.edit(content=f"❌ {result.get('error')}")
@bot.command(name="shield",aliases=["sh"])
async def cmd_shield(ctx):
 if not is_owner(ctx.author.id):return
 st=shield.health();embed=discord.Embed(title="🛡️ Shield",color=0x2ECC71 if st.get("success")else 0xE74C3C)
 embed.add_field(name="Status",value="🟢 ONLINE"if st.get("success")else"🔴 OFFLINE",inline=True)
 embed.add_field(name="URL",value=f"`{SHIELD_URL[:20]}...`"if len(SHIELD_URL)>20 else f"`{SHIELD_URL or'Not Set'}`",inline=True)
 await ctx.send(embed=embed,view=ShieldView())
@bot.command(name="shieldm",aliases=["sm"])
async def cmd_sm(ctx):
 if not is_owner(ctx.author.id):return
 embed=discord.Embed(title="⚙️ Shield Manage",description="Format: `type:value`\nTypes: `userId`, `hwid`, `ip`",color=0xE74C3C)
 await ctx.send(embed=embed,view=ShieldManageView())
@bot.command(name="clear",aliases=["reset"])
async def cmd_clear(ctx):mem.clear(ctx.author.id);await ctx.send("🧹 Cleared!",delete_after=5)
@bot.command(name="ping",aliases=["p"])
async def cmd_ping(ctx):await ctx.send(f"🏓 {round(bot.latency*1000)}ms")
@bot.command(name="status")
async def cmd_status(ctx):
 if not is_owner(ctx.author.id):return
 keys=[("Groq","groq"),("Cerebras","cerebras"),("SambaNova","sambanova"),("OpenRouter","openrouter"),("Cohere","cohere"),("Mistral","mistral"),("Together","together")]
 st="\n".join([f"{'✅'if get_api_key(k)else'❌'} {n}"for n,k in keys])
 embed=discord.Embed(title="📊 Status",color=0x5865F2)
 embed.add_field(name="🔑 API Keys",value=st,inline=True)
 embed.add_field(name="🌐 Web Panel",value=f"`https://bot-dumper.onrender.com`",inline=False)
 await ctx.send(embed=embed)
@bot.command(name="testai")
async def cmd_testai(ctx):
 if not is_owner(ctx.author.id):return
 st=await ctx.send("🔄 Testing...");test=[{"role":"user","content":"Say OK"}];results=[]
 providers=[("Groq",lambda:call_groq(test),get_api_key("groq")),("Cerebras",lambda:call_cerebras(test),get_api_key("cerebras")),("SambaNova",lambda:call_sambanova(test),get_api_key("sambanova")),("OR",lambda:call_openrouter(test,"or_gemini"),get_api_key("openrouter")),("Poll",lambda:call_pollinations(test,"poll_free"),True)]
 for n,f,k in providers:
  if not k:results.append(f"⚪{n}");continue
  try:r=f();results.append(f"✅{n}"if r else f"❌{n}")
  except:results.append(f"❌{n}")
 await st.edit(content=" | ".join(results))
@bot.command(name="blacklist",aliases=["bl"])
async def cmd_bl(ctx,action:str=None,user:discord.User=None):
 if not is_owner(ctx.author.id)or not action or not user:return
 if action=="add":db.ban(user.id);await ctx.send(f"✅ Banned {user}")
 elif action=="rem":db.unban(user.id);await ctx.send(f"✅ Unbanned {user}")
@bot.command(name="allowuser",aliases=["au"])
async def cmd_au(ctx,user:discord.User=None,*,models:str=None):
 if not is_owner(ctx.author.id):return
 if not user:return await ctx.send(f"Usage: `{PREFIX}au @user model1,model2`")
 if not models:return await ctx.send(f"📋 {user}: `{','.join(db.get_allowed(user.id))or'None'}`")
 if models.lower()=="reset":db.rem_allowed(user.id);return await ctx.send(f"✅ Reset {user}")
 valid=[m.strip()for m in models.split(",")if m.strip()in ALL_MODELS]
 if valid:db.set_allowed(user.id,valid);await ctx.send(f"✅ {user}: `{','.join(valid)}`")
@bot.command(name="stats")
async def cmd_stats(ctx):
 s=db.get_stats()
 await ctx.send(f"📈 Total: {s['total']} | Today: {s['today']} | Users: {s['users']}")
@bot.command(name="help",aliases=["h"])
async def cmd_help(ctx):
 embed=discord.Embed(title="📚 Help",color=0x5865F2)
 embed.add_field(name="AI",value=f"`{PREFIX}ai` `@mention`",inline=True)
 embed.add_field(name="Models",value=f"`{PREFIX}m` `{PREFIX}sd`",inline=True)
 embed.add_field(name="Image",value=f"`{PREFIX}img` `{PREFIX}im`",inline=True)
 embed.add_field(name="Utils",value=f"`{PREFIX}dump` `{PREFIX}clear` `{PREFIX}ping`",inline=True)
 if is_owner(ctx.author.id):embed.add_field(name="Admin",value=f"`{PREFIX}status` `{PREFIX}sh` `{PREFIX}sm` `{PREFIX}bl` `{PREFIX}au`",inline=True)
 embed.add_field(name="🌐 Web",value=f"`https://bot-dumper.onrender.com?key=***`",inline=False)
 await ctx.send(embed=embed)
if __name__=="__main__":
 keep_alive()
 webconfig.init_defaults()
 if HAS_FLASK:
  flask_app=create_flask_app()
  if flask_app:
   def run_flask():
    import logging as lg;lg.getLogger('werkzeug').setLevel(lg.ERROR)
    flask_app.run(host="0.0.0.0",port=WEB_PORT,debug=False,use_reloader=False,threaded=True)
   threading.Thread(target=run_flask,daemon=True).start()
   print(f"🌐 Web Panel: http://0.0.0.0:{WEB_PORT}?key={WEB_ADMIN_KEY}")
 print("="*50)
 print("🚀 Bot Starting...")
 print(f"👑 Owners: {OWNER_IDS}")
 print(f"🌍 Default: {get_public_default()}")
 print(f"🛡️ Shield: {'✅'if SHIELD_URL else'❌'}")
 print("-"*50)
 for n,k in[("Groq","groq"),("Cerebras","cerebras"),("SambaNova","sambanova"),("OpenRouter","openrouter"),("Cohere","cohere")]:
  print(f"   {'✅'if get_api_key(k)else'❌'} {n}")
 print("="*50)
 bot.run(DISCORD_TOKEN,log_handler=None)
