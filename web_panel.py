import os,json,threading,sqlite3,hashlib
from datetime import datetime
from functools import wraps
try:
 from flask import Flask,request,jsonify,render_template_string
 HAS_FLASK=True
except:
 HAS_FLASK=False
 print("⚠️ Flask not installed")
class ConfigManager:
 def __init__(self,path="bot_config.db"):
  self.path=path
  self.conn=sqlite3.connect(path,check_same_thread=False)
  self.lock=threading.Lock()
  self._init()
 def _init(self):
  with self.lock:
   self.conn.executescript('''
CREATE TABLE IF NOT EXISTS api_keys(
 name TEXT PRIMARY KEY,
 value TEXT NOT NULL,
 description TEXT,
 is_active INTEGER DEFAULT 1,
 updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ai_models(
 id TEXT PRIMARY KEY,
 provider TEXT NOT NULL,
 name TEXT NOT NULL,
 model_id TEXT NOT NULL,
 endpoint TEXT,
 category TEXT DEFAULT 'main',
 emoji TEXT DEFAULT '🤖',
 description TEXT,
 is_active INTEGER DEFAULT 1,
 priority INTEGER DEFAULT 100
);
CREATE TABLE IF NOT EXISTS settings(
 key TEXT PRIMARY KEY,
 value TEXT
);
CREATE TABLE IF NOT EXISTS audit_log(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 action TEXT,
 target TEXT,
 details TEXT,
 ip TEXT,
 timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);''')
   self.conn.commit()
 def get_key(self,name):
  with self.lock:
   r=self.conn.execute('SELECT value FROM api_keys WHERE name=? AND is_active=1',(name,)).fetchone()
   return r[0]if r else None
 def get_all_keys(self,masked=True):
  with self.lock:
   rows=self.conn.execute('SELECT name,value,description,is_active,updated_at FROM api_keys ORDER BY name').fetchall()
   result=[]
   for r in rows:
    v=r[1]
    if masked and v:
     if len(v)>12:v=v[:4]+"*"*(len(v)-8)+v[-4:]
     else:v="*"*len(v)
    result.append({"name":r[0],"value":v,"description":r[2]or"","is_active":bool(r[3]),"updated_at":r[4]})
   return result
 def set_key(self,name,value,desc=None):
  with self.lock:
   existing=self.conn.execute('SELECT description FROM api_keys WHERE name=?',(name,)).fetchone()
   if desc is None and existing:desc=existing[0]
   self.conn.execute('INSERT OR REPLACE INTO api_keys(name,value,description,is_active,updated_at)VALUES(?,?,?,1,CURRENT_TIMESTAMP)',(name,value,desc))
   self.conn.commit()
   self._log("SET_KEY",name)
   self._sync_env(name,value)
   return True
 def del_key(self,name):
  with self.lock:
   self.conn.execute('DELETE FROM api_keys WHERE name=?',(name,))
   self.conn.commit()
   self._log("DEL_KEY",name)
   return True
 def toggle_key(self,name,active):
  with self.lock:
   self.conn.execute('UPDATE api_keys SET is_active=?,updated_at=CURRENT_TIMESTAMP WHERE name=?',(1 if active else 0,name))
   self.conn.commit()
   return True
 def _sync_env(self,name,value):
  env_map={"groq":"GROQ_API_KEY","openrouter":"OPENROUTER_API_KEY","cerebras":"CEREBRAS_API_KEY","sambanova":"SAMBANOVA_API_KEY","cohere":"COHERE_API_KEY","cloudflare_token":"CLOUDFLARE_API_TOKEN","cloudflare_account":"CLOUDFLARE_ACCOUNT_ID","together":"TOGETHER_API_KEY","tavily":"TAVILY_API_KEY","mistral":"MISTRAL_API_KEY","replicate":"REPLICATE_API_TOKEN","huggingface":"HUGGINGFACE_API_KEY","moonshot":"MOONSHOT_API_KEY","pollinations":"POLLINATIONS_API_KEY"}
  if name in env_map:os.environ[env_map[name]]=value
 def get_model(self,mid):
  with self.lock:
   r=self.conn.execute('SELECT * FROM ai_models WHERE id=?',(mid,)).fetchone()
   if r:return{"id":r[0],"provider":r[1],"name":r[2],"model_id":r[3],"endpoint":r[4],"category":r[5],"emoji":r[6],"description":r[7],"is_active":bool(r[8]),"priority":r[9]}
   return None
 def get_all_models(self,category=None,active_only=False):
  with self.lock:
   q='SELECT * FROM ai_models'
   params=[]
   conds=[]
   if category:conds.append('category=?');params.append(category)
   if active_only:conds.append('is_active=1')
   if conds:q+=' WHERE '+' AND '.join(conds)
   q+=' ORDER BY category,priority,name'
   rows=self.conn.execute(q,params).fetchall()
   return[{"id":r[0],"provider":r[1],"name":r[2],"model_id":r[3],"endpoint":r[4],"category":r[5],"emoji":r[6],"description":r[7],"is_active":bool(r[8]),"priority":r[9]}for r in rows]
 def add_model(self,mid,provider,name,model_id,endpoint=None,category="main",emoji="🤖",desc="",priority=100):
  with self.lock:
   self.conn.execute('INSERT OR REPLACE INTO ai_models(id,provider,name,model_id,endpoint,category,emoji,description,priority)VALUES(?,?,?,?,?,?,?,?,?)',(mid,provider,name,model_id,endpoint,category,emoji,desc,priority))
   self.conn.commit()
   self._log("ADD_MODEL",mid,f"{provider}/{model_id}")
   return True
 def update_model(self,mid,**kwargs):
  with self.lock:
   allowed=["provider","name","model_id","endpoint","category","emoji","description","is_active","priority"]
   updates=[(k,v)for k,v in kwargs.items()if k in allowed and v is not None]
   if not updates:return False
   set_clause=",".join([f"{k}=?"for k,_ in updates])
   values=[v for _,v in updates]+[mid]
   self.conn.execute(f'UPDATE ai_models SET {set_clause} WHERE id=?',values)
   self.conn.commit()
   self._log("UPD_MODEL",mid,str(kwargs))
   return True
 def del_model(self,mid):
  with self.lock:
   self.conn.execute('DELETE FROM ai_models WHERE id=?',(mid,))
   self.conn.commit()
   self._log("DEL_MODEL",mid)
   return True
 def get_setting(self,key,default=None):
  with self.lock:
   r=self.conn.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
   return r[0]if r else default
 def set_setting(self,key,value):
  with self.lock:
   self.conn.execute('INSERT OR REPLACE INTO settings(key,value)VALUES(?,?)',(key,str(value)))
   self.conn.commit()
   return True
 def get_all_settings(self):
  with self.lock:
   return{r[0]:r[1]for r in self.conn.execute('SELECT key,value FROM settings').fetchall()}
 def _log(self,action,target,details="",ip=""):
  try:self.conn.execute('INSERT INTO audit_log(action,target,details,ip)VALUES(?,?,?,?)',(action,target,details,ip));self.conn.commit()
  except:pass
 def get_logs(self,limit=100):
  with self.lock:
   rows=self.conn.execute('SELECT id,action,target,details,ip,timestamp FROM audit_log ORDER BY timestamp DESC LIMIT ?',(limit,)).fetchall()
   return[{"id":r[0],"action":r[1],"target":r[2],"details":r[3],"ip":r[4],"timestamp":r[5]}for r in rows]
 def clear_logs(self):
  with self.lock:
   self.conn.execute('DELETE FROM audit_log')
   self.conn.commit()
   return True
 def init_default_models(self):
  if self.get_all_models():return False
  defaults=[
   ("groq","groq","Groq","llama-3.3-70b-versatile",None,"main","⚡","Llama 3.3 70B - Fast",10),
   ("cerebras","cerebras","Cerebras","llama-3.3-70b",None,"main","🧠","Llama 3.3 70B",20),
   ("sambanova","sambanova","SambaNova","Meta-Llama-3.3-70B-Instruct",None,"main","🦣","Llama 3.3 70B",30),
   ("cloudflare","cloudflare","Cloudflare","@cf/meta/llama-3.3-70b-instruct-fp8-fast",None,"main","☁️","Llama 3.3 70B",40),
   ("cohere","cohere","Cohere","command-r-plus-08-2024",None,"main","🔷","Command R+",50),
   ("mistral","mistral","Mistral","mistral-small-latest",None,"main","Ⓜ️","Mistral Small",60),
   ("together","together","Together","meta-llama/Llama-3.3-70B-Instruct-Turbo",None,"main","🤝","Llama 3.3 Turbo",70),
   ("moonshot","moonshot","Moonshot","moonshot-v1-8k",None,"main","🌙","Kimi 128K",80),
   ("huggingface","huggingface","HuggingFace","mistralai/Mixtral-8x7B-Instruct-v0.1",None,"main","🤗","Mixtral 8x7B",90),
   ("replicate","replicate","Replicate","meta/meta-llama-3.1-405b-instruct",None,"main","🔄","Llama 405B",100),
   ("tavily","tavily","Tavily","search",None,"main","🔍","Search + Web",110),
   ("or_llama","openrouter","OR-Llama","meta-llama/llama-3.3-70b-instruct:free",None,"openrouter","🦙","Llama 3.3 70B Free",10),
   ("or_gemini","openrouter","OR-Gemini","google/gemini-2.0-flash-exp:free",None,"openrouter","💎","Gemini 2.0 Free",20),
   ("or_qwen","openrouter","OR-Qwen","qwen/qwen-2.5-72b-instruct:free",None,"openrouter","💻","Qwen 2.5 72B Free",30),
   ("or_deepseek","openrouter","OR-DeepSeek","deepseek/deepseek-chat:free",None,"openrouter","🌊","DeepSeek Chat Free",40),
   ("or_mistral","openrouter","OR-Mistral","mistralai/mistral-nemo:free",None,"openrouter","🅼","Mistral Nemo Free",50),
   ("p_openai","pollinations","Poll-OpenAI","openai-large",None,"pollinations","🤖","OpenAI Large",10),
   ("p_claude","pollinations","Poll-Claude","claude-hybridspace",None,"pollinations","🎭","Claude Hybrid",20),
   ("p_gemini","pollinations","Poll-Gemini","gemini",None,"pollinations","💎","Gemini",30),
   ("p_deepseek","pollinations","Poll-DeepSeek","deepseek",None,"pollinations","🐳","DeepSeek V3",40),
   ("p_qwen","pollinations","Poll-Qwen","qwen-72b",None,"pollinations","📟","Qwen 72B",50),
   ("p_llama","pollinations","Poll-Llama","llama-3.3-70b",None,"pollinations","🦙","Llama 3.3",60),
   ("p_mistral","pollinations","Poll-Mistral","mistral",None,"pollinations","🅼","Mistral",70),
   ("poll_free","pollinations","Poll-Free","free",None,"pollinations","🌸","Free Unlimited",80),
  ]
  for m in defaults:self.add_model(*m)
  print(f"✅ Initialized {len(defaults)} default models")
  return True
config=ConfigManager()
DASHBOARD_HTML='''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>🤖 Bot Control Panel</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);color:#fff;min-height:100vh}
.container{max-width:1400px;margin:0 auto;padding:20px}
header{text-align:center;padding:30px 0;border-bottom:1px solid rgba(255,255,255,0.1);margin-bottom:30px}
header h1{font-size:2.5em;background:linear-gradient(90deg,#00d4ff,#00ff88);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:10px}
header p{color:#888;font-size:0.95em}
.tabs{display:flex;gap:10px;justify-content:center;margin-bottom:30px;flex-wrap:wrap}
.tab{padding:12px 28px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);color:#fff;border-radius:10px;cursor:pointer;font-size:1em;transition:all 0.3s}
.tab:hover{background:rgba(0,212,255,0.2);border-color:#00d4ff}
.tab.active{background:linear-gradient(135deg,#00d4ff,#00ff88);color:#000;border-color:transparent;font-weight:600}
.panel{display:none;animation:fadeIn 0.3s}
.panel.active{display:block}
@keyframes fadeIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
.header-row{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;flex-wrap:wrap;gap:15px}
.header-row h2{font-size:1.5em;display:flex;align-items:center;gap:10px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:20px}
.card{background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:15px;padding:20px;transition:all 0.3s}
.card:hover{border-color:#00d4ff;transform:translateY(-3px);box-shadow:0 10px 30px rgba(0,212,255,0.1)}
.card h3{font-size:1.1em;margin-bottom:12px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.card p{color:#aaa;font-size:0.9em;margin:5px 0}
.card code{background:rgba(0,0,0,0.3);padding:3px 8px;border-radius:5px;font-size:0.85em;word-break:break-all;color:#00d4ff}
.badge{padding:4px 10px;border-radius:20px;font-size:0.75em;font-weight:600;text-transform:uppercase}
.badge-main{background:linear-gradient(135deg,#4caf50,#2e7d32)}
.badge-openrouter{background:linear-gradient(135deg,#2196f3,#1565c0)}
.badge-pollinations{background:linear-gradient(135deg,#9c27b0,#6a1b9a)}
.status{width:10px;height:10px;border-radius:50%;margin-left:auto;flex-shrink:0}
.status.on{background:#4caf50;box-shadow:0 0 10px #4caf50}
.status.off{background:#f44336;box-shadow:0 0 10px #f44336}
.btn{padding:10px 20px;border:none;border-radius:8px;cursor:pointer;font-size:0.9em;font-weight:500;transition:all 0.3s;display:inline-flex;align-items:center;gap:6px}
.btn-primary{background:linear-gradient(135deg,#00d4ff,#0099cc);color:#000}
.btn-success{background:linear-gradient(135deg,#4caf50,#2e7d32);color:#fff}
.btn-danger{background:linear-gradient(135deg,#f44336,#c62828);color:#fff}
.btn-secondary{background:rgba(255,255,255,0.1);color:#fff;border:1px solid rgba(255,255,255,0.2)}
.btn:hover{transform:scale(1.02);opacity:0.9}
.btn-sm{padding:6px 12px;font-size:0.8em}
input,select,textarea{width:100%;padding:12px 15px;margin:8px 0;background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.15);color:#fff;border-radius:8px;font-size:0.95em;transition:border-color 0.3s}
input:focus,select:focus,textarea:focus{outline:none;border-color:#00d4ff}
input::placeholder{color:#666}
label{display:block;margin-bottom:5px;color:#aaa;font-size:0.9em}
.form-group{margin-bottom:15px}
.modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.85);justify-content:center;align-items:center;z-index:1000;padding:20px}
.modal.show{display:flex}
.modal-box{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid rgba(255,255,255,0.1);border-radius:20px;padding:30px;width:100%;max-width:500px;max-height:85vh;overflow-y:auto;animation:modalIn 0.3s}
@keyframes modalIn{from{opacity:0;transform:scale(0.9)}to{opacity:1;transform:scale(1)}}
.modal-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:25px;padding-bottom:15px;border-bottom:1px solid rgba(255,255,255,0.1)}
.modal-header h3{font-size:1.3em}
.close{background:none;border:none;color:#fff;font-size:28px;cursor:pointer;opacity:0.7;transition:opacity 0.3s}
.close:hover{opacity:1}
table{width:100%;border-collapse:collapse;margin-top:20px}
th,td{padding:15px;text-align:left;border-bottom:1px solid rgba(255,255,255,0.1)}
th{background:rgba(0,0,0,0.3);font-weight:600;color:#00d4ff}
tr:hover{background:rgba(255,255,255,0.03)}
.alert{padding:15px 20px;border-radius:10px;margin-bottom:20px;display:flex;align-items:center;gap:10px;animation:slideIn 0.3s}
@keyframes slideIn{from{opacity:0;transform:translateX(-20px)}to{opacity:1;transform:translateX(0)}}
.alert-success{background:rgba(76,175,80,0.2);border:1px solid #4caf50;color:#81c784}
.alert-error{background:rgba(244,67,54,0.2);border:1px solid #f44336;color:#ef9a9a}
.search-box{position:relative;max-width:300px}
.search-box input{padding-left:40px}
.search-box::before{content:"🔍";position:absolute;left:12px;top:50%;transform:translateY(-50%);font-size:1em}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:15px;margin-bottom:30px}
.stat-card{background:rgba(255,255,255,0.05);border-radius:12px;padding:20px;text-align:center}
.stat-card .number{font-size:2em;font-weight:700;background:linear-gradient(90deg,#00d4ff,#00ff88);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.stat-card .label{color:#888;font-size:0.85em;margin-top:5px}
.empty-state{text-align:center;padding:60px 20px;color:#666}
.empty-state .icon{font-size:4em;margin-bottom:20px;opacity:0.5}
@media(max-width:768px){
 .container{padding:15px}
 header h1{font-size:1.8em}
 .grid{grid-template-columns:1fr}
 .tabs{gap:8px}
 .tab{padding:10px 18px;font-size:0.9em}
}
</style>
</head>
<body>
<div class="container">
<header>
<h1>🤖 Bot Control Panel</h1>
<p>Manage API Keys, AI Models & Settings</p>
</header>
<div class="tabs">
<button class="tab active" onclick="showTab('keys')">🔑 API Keys</button>
<button class="tab" onclick="showTab('models')">🤖 AI Models</button>
<button class="tab" onclick="showTab('settings')">⚙️ Settings</button>
<button class="tab" onclick="showTab('logs')">📋 Logs</button>
</div>
<div id="alert"></div>
<!-- API Keys Panel -->
<div id="keys" class="panel active">
<div class="header-row">
<h2>🔑 API Keys</h2>
<button class="btn btn-primary" onclick="openModal('addKeyModal')">+ Add Key</button>
</div>
<div id="keysList" class="grid"></div>
</div>
<!-- AI Models Panel -->
<div id="models" class="panel">
<div class="header-row">
<h2>🤖 AI Models</h2>
<div style="display:flex;gap:10px;flex-wrap:wrap">
<select id="categoryFilter" onchange="loadModels()" style="width:auto">
<option value="">All Categories</option>
<option value="main">Main</option>
<option value="openrouter">OpenRouter</option>
<option value="pollinations">Pollinations</option>
</select>
<button class="btn btn-primary" onclick="openModal('addModelModal')">+ Add Model</button>
</div>
</div>
<div id="modelsList" class="grid"></div>
</div>
<!-- Settings Panel -->
<div id="settings" class="panel">
<div class="header-row">
<h2>⚙️ Settings</h2>
</div>
<div class="grid">
<div class="card">
<h3>🌍 Default Model</h3>
<p>Model used for public users</p>
<select id="defaultModel" onchange="saveSetting('default_model',this.value)" style="margin-top:10px"></select>
</div>
<div class="card">
<h3>📝 Bot Prefix</h3>
<p>Command prefix for the bot</p>
<div style="display:flex;gap:10px;margin-top:10px">
<input type="text" id="botPrefix" placeholder="." maxlength="5" style="flex:1">
<button class="btn btn-success btn-sm" onclick="saveSetting('bot_prefix',document.getElementById('botPrefix').value)">Save</button>
</div>
</div>
<div class="card">
<h3>🔄 Initialize Models</h3>
<p>Load default AI models configuration</p>
<button class="btn btn-secondary" onclick="initModels()" style="margin-top:10px">Initialize Defaults</button>
</div>
<div class="card">
<h3>🗑️ Clear Logs</h3>
<p>Remove all audit logs</p>
<button class="btn btn-danger" onclick="clearLogs()" style="margin-top:10px">Clear All Logs</button>
</div>
</div>
</div>
<!-- Logs Panel -->
<div id="logs" class="panel">
<div class="header-row">
<h2>📋 Audit Logs</h2>
<button class="btn btn-secondary" onclick="loadLogs()">🔄 Refresh</button>
</div>
<table>
<thead><tr><th>Time</th><th>Action</th><th>Target</th><th>Details</th></tr></thead>
<tbody id="logsTable"></tbody>
</table>
</div>
</div>
<!-- Add Key Modal -->
<div id="addKeyModal" class="modal">
<div class="modal-box">
<div class="modal-header">
<h3>🔑 Add API Key</h3>
<button class="close" onclick="closeModal('addKeyModal')">&times;</button>
</div>
<form onsubmit="addKey(event)">
<div class="form-group">
<label>Provider</label>
<select id="keyName" required>
<option value="">Select provider...</option>
<option value="groq">Groq</option>
<option value="openrouter">OpenRouter</option>
<option value="cerebras">Cerebras</option>
<option value="sambanova">SambaNova</option>
<option value="cohere">Cohere</option>
<option value="cloudflare_token">Cloudflare Token</option>
<option value="cloudflare_account">Cloudflare Account ID</option>
<option value="together">Together</option>
<option value="tavily">Tavily</option>
<option value="mistral">Mistral</option>
<option value="replicate">Replicate</option>
<option value="huggingface">HuggingFace</option>
<option value="moonshot">Moonshot</option>
<option value="pollinations">Pollinations</option>
</select>
</div>
<div class="form-group">
<label>API Key Value</label>
<input type="password" id="keyValue" required placeholder="sk-xxxx... or paste your key">
</div>
<div class="form-group">
<label>Description (optional)</label>
<input type="text" id="keyDesc" placeholder="e.g., Main production key">
</div>
<button type="submit" class="btn btn-success" style="width:100%;margin-top:10px">💾 Save Key</button>
</form>
</div>
</div>
<!-- Edit Key Modal -->
<div id="editKeyModal" class="modal">
<div class="modal-box">
<div class="modal-header">
<h3>✏️ Edit API Key</h3>
<button class="close" onclick="closeModal('editKeyModal')">&times;</button>
</div>
<form onsubmit="updateKey(event)">
<input type="hidden" id="editKeyName">
<div class="form-group">
<label>Provider</label>
<input type="text" id="editKeyProvider" disabled>
</div>
<div class="form-group">
<label>New API Key Value</label>
<input type="password" id="editKeyValue" required placeholder="Enter new key value">
</div>
<div class="form-group">
<label>Description</label>
<input type="text" id="editKeyDesc" placeholder="Description">
</div>
<button type="submit" class="btn btn-success" style="width:100%;margin-top:10px">💾 Update Key</button>
</form>
</div>
</div>
<!-- Add Model Modal -->
<div id="addModelModal" class="modal">
<div class="modal-box">
<div class="modal-header">
<h3>🤖 Add AI Model</h3>
<button class="close" onclick="closeModal('addModelModal')">&times;</button>
</div>
<form onsubmit="addModel(event)">
<div class="form-group">
<label>Model ID (unique identifier)</label>
<input type="text" id="modelId" required placeholder="e.g., my_gpt4 or custom_llama">
</div>
<div class="form-group">
<label>Provider</label>
<select id="modelProvider" required>
<option value="">Select provider...</option>
<option value="groq">Groq</option>
<option value="openrouter">OpenRouter</option>
<option value="cerebras">Cerebras</option>
<option value="sambanova">SambaNova</option>
<option value="cloudflare">Cloudflare</option>
<option value="cohere">Cohere</option>
<option value="mistral">Mistral</option>
<option value="together">Together</option>
<option value="pollinations">Pollinations</option>
<option value="huggingface">HuggingFace</option>
<option value="replicate">Replicate</option>
<option value="moonshot">Moonshot</option>
<option value="tavily">Tavily</option>
</select>
</div>
<div class="form-group">
<label>Display Name</label>
<input type="text" id="modelName" required placeholder="e.g., GPT-4 Turbo">
</div>
<div class="form-group">
<label>API Model ID</label>
<input type="text" id="modelApiId" required placeholder="e.g., gpt-4-turbo or llama-3.3-70b">
</div>
<div class="form-group">
<label>Category</label>
<select id="modelCategory">
<option value="main">Main</option>
<option value="openrouter">OpenRouter</option>
<option value="pollinations">Pollinations</option>
</select>
</div>
<div class="form-group">
<label>Emoji</label>
<input type="text" id="modelEmoji" placeholder="🤖" maxlength="4" value="🤖">
</div>
<div class="form-group">
<label>Description</label>
<input type="text" id="modelDesc" placeholder="e.g., Fast and accurate model">
</div>
<button type="submit" class="btn btn-success" style="width:100%;margin-top:10px">💾 Add Model</button>
</form>
</div>
</div>
<!-- Edit Model Modal -->
<div id="editModelModal" class="modal">
<div class="modal-box">
<div class="modal-header">
<h3>✏️ Edit AI Model</h3>
<button class="close" onclick="closeModal('editModelModal')">&times;</button>
</div>
<form onsubmit="updateModel(event)">
<input type="hidden" id="editModelId">
<div class="form-group">
<label>Model ID</label>
<input type="text" id="editModelIdDisplay" disabled>
</div>
<div class="form-group">
<label>Provider</label>
<select id="editModelProvider">
<option value="groq">Groq</option>
<option value="openrouter">OpenRouter</option>
<option value="cerebras">Cerebras</option>
<option value="sambanova">SambaNova</option>
<option value="cloudflare">Cloudflare</option>
<option value="cohere">Cohere</option>
<option value="mistral">Mistral</option>
<option value="together">Together</option>
<option value="pollinations">Pollinations</option>
<option value="huggingface">HuggingFace</option>
<option value="replicate">Replicate</option>
<option value="moonshot">Moonshot</option>
<option value="tavily">Tavily</option>
</select>
</div>
<div class="form-group">
<label>Display Name</label>
<input type="text" id="editModelName" required>
</div>
<div class="form-group">
<label>API Model ID</label>
<input type="text" id="editModelApiId" required>
</div>
<div class="form-group">
<label>Category</label>
<select id="editModelCategory">
<option value="main">Main</option>
<option value="openrouter">OpenRouter</option>
<option value="pollinations">Pollinations</option>
</select>
</div>
<div class="form-group">
<label>Emoji</label>
<input type="text" id="editModelEmoji" maxlength="4">
</div>
<div class="form-group">
<label>Description</label>
<input type="text" id="editModelDesc">
</div>
<button type="submit" class="btn btn-success" style="width:100%;margin-top:10px">💾 Update Model</button>
</form>
</div>
</div>
<script>
const API='/api';
const KEY='{{admin_key}}';
const headers={'Content-Type':'application/json','X-Admin-Key':KEY};
function showTab(id){
 document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
 document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
 document.getElementById(id).classList.add('active');
 event.target.classList.add('active');
 if(id==='keys')loadKeys();
 if(id==='models')loadModels();
 if(id==='settings')loadSettings();
 if(id==='logs')loadLogs();
}
function openModal(id){document.getElementById(id).classList.add('show')}
function closeModal(id){document.getElementById(id).classList.remove('show')}
function showAlert(msg,type='success'){
 const alert=document.getElementById('alert');
 alert.innerHTML=`<div class="alert alert-${type}">${type==='success'?'✅':'❌'} ${msg}</div>`;
 setTimeout(()=>alert.innerHTML='',5000);
}
async function api(endpoint,method='GET',data=null){
 const opts={method,headers};
 if(data)opts.body=JSON.stringify(data);
 try{
  const r=await fetch(API+endpoint,opts);
  return await r.json();
 }catch(e){
  return{success:false,error:e.message};
 }
}
// Keys
async function loadKeys(){
 const d=await api('/keys');
 const container=document.getElementById('keysList');
 if(!d.keys||d.keys.length===0){
  container.innerHTML='<div class="empty-state"><div class="icon">🔑</div><p>No API keys configured yet</p></div>';
  return;
 }
 container.innerHTML=d.keys.map(k=>`
  <div class="card">
   <h3>
    🔑 ${k.name}
    <span class="status ${k.is_active?'on':'off'}"></span>
   </h3>
   <p><code>${k.value}</code></p>
   <p style="color:#666;font-size:0.85em">${k.description||'No description'}</p>
   <p style="color:#444;font-size:0.8em">Updated: ${k.updated_at||'N/A'}</p>
   <div style="margin-top:15px;display:flex;gap:8px;flex-wrap:wrap">
    <button class="btn btn-secondary btn-sm" onclick="editKey('${k.name}','${k.description||''}')">✏️ Edit</button>
    <button class="btn btn-danger btn-sm" onclick="deleteKey('${k.name}')">🗑️ Delete</button>
   </div>
  </div>
 `).join('');
}
async function addKey(e){
 e.preventDefault();
 const name=document.getElementById('keyName').value;
 const value=document.getElementById('keyValue').value;
 const desc=document.getElementById('keyDesc').value;
 const d=await api('/keys','POST',{name,value,description:desc});
 if(d.success){
  showAlert('API Key added successfully!');
  closeModal('addKeyModal');
  document.getElementById('keyName').value='';
  document.getElementById('keyValue').value='';
  document.getElementById('keyDesc').value='';
  loadKeys();
 }else{
  showAlert(d.error||'Failed to add key','error');
 }
}
function editKey(name,desc){
 document.getElementById('editKeyName').value=name;
 document.getElementById('editKeyProvider').value=name;
 document.getElementById('editKeyDesc').value=desc;
 document.getElementById('editKeyValue').value='';
 openModal('editKeyModal');
}
async function updateKey(e){
 e.preventDefault();
 const name=document.getElementById('editKeyName').value;
 const value=document.getElementById('editKeyValue').value;
 const desc=document.getElementById('editKeyDesc').value;
 const d=await api(`/keys/${name}`,'PUT',{value,description:desc});
 if(d.success){
  showAlert('API Key updated!');
  closeModal('editKeyModal');
  loadKeys();
 }else{
  showAlert(d.error||'Failed','error');
 }
}
async function deleteKey(name){
 if(!confirm(`Delete API key "${name}"?`))return;
 const d=await api(`/keys/${name}`,'DELETE');
 if(d.success){
  showAlert('Key deleted!');
  loadKeys();
 }else{
  showAlert(d.error||'Failed','error');
 }
}
// Models
async function loadModels(){
 const category=document.getElementById('categoryFilter').value;
 const url=category?`/models?category=${category}`:'/models';
 const d=await api(url);
 const container=document.getElementById('modelsList');
 if(!d.models||d.models.length===0){
  container.innerHTML='<div class="empty-state"><div class="icon">🤖</div><p>No models configured</p><p style="margin-top:10px"><button class="btn btn-primary" onclick="initModels()">Initialize Default Models</button></p></div>';
  return;
 }
 container.innerHTML=d.models.map(m=>`
  <div class="card">
   <h3>
    ${m.emoji} ${m.name}
    <span class="badge badge-${m.category}">${m.category}</span>
    <span class="status ${m.is_active?'on':'off'}"></span>
   </h3>
   <p><b>ID:</b> <code>${m.id}</code></p>
   <p><b>Provider:</b> ${m.provider}</p>
   <p><b>Model:</b> <code>${m.model_id}</code></p>
   <p style="color:#666">${m.description||''}</p>
   <div style="margin-top:15px;display:flex;gap:8px;flex-wrap:wrap">
    <button class="btn btn-secondary btn-sm" onclick='editModel(${JSON.stringify(m)})'>✏️ Edit</button>
    <button class="btn btn-${m.is_active?'warning':'success'} btn-sm" onclick="toggleModel('${m.id}',${!m.is_active})">${m.is_active?'⏸️ Disable':'▶️ Enable'}</button>
    <button class="btn btn-danger btn-sm" onclick="deleteModel('${m.id}')">🗑️</button>
   </div>
  </div>
 `).join('');
}
async function addModel(e){
 e.preventDefault();
 const data={
  id:document.getElementById('modelId').value,
  provider:document.getElementById('modelProvider').value,
  name:document.getElementById('modelName').value,
  model_id:document.getElementById('modelApiId').value,
  category:document.getElementById('modelCategory').value,
  emoji:document.getElementById('modelEmoji').value||'🤖',
  description:document.getElementById('modelDesc').value
 };
 const d=await api('/models','POST',data);
 if(d.success){
  showAlert('Model added!');
  closeModal('addModelModal');
  ['modelId','modelProvider','modelName','modelApiId','modelDesc'].forEach(id=>document.getElementById(id).value='');
  document.getElementById('modelEmoji').value='🤖';
  loadModels();
 }else{
  showAlert(d.error||'Failed','error');
 }
}
function editModel(m){
 document.getElementById('editModelId').value=m.id;
 document.getElementById('editModelIdDisplay').value=m.id;
 document.getElementById('editModelProvider').value=m.provider;
 document.getElementById('editModelName').value=m.name;
 document.getElementById('editModelApiId').value=m.model_id;
 document.getElementById('editModelCategory').value=m.category;
 document.getElementById('editModelEmoji').value=m.emoji;
 document.getElementById('editModelDesc').value=m.description||'';
 openModal('editModelModal');
}
async function updateModel(e){
 e.preventDefault();
 const id=document.getElementById('editModelId').value;
 const data={
  provider:document.getElementById('editModelProvider').value,
  name:document.getElementById('editModelName').value,
  model_id:document.getElementById('editModelApiId').value,
  category:document.getElementById('editModelCategory').value,
  emoji:document.getElementById('editModelEmoji').value,
  description:document.getElementById('editModelDesc').value
 };
 const d=await api(`/models/${id}`,'PUT',data);
 if(d.success){
  showAlert('Model updated!');
  closeModal('editModelModal');
  loadModels();
 }else{
  showAlert(d.error||'Failed','error');
 }
}
async function toggleModel(id,active){
 const d=await api(`/models/${id}`,'PUT',{is_active:active?1:0});
 if(d.success){
  showAlert(`Model ${active?'enabled':'disabled'}!`);
  loadModels();
 }
}
async function deleteModel(id){
 if(!confirm(`Delete model "${id}"?`))return;
 const d=await api(`/models/${id}`,'DELETE');
 if(d.success){
  showAlert('Model deleted!');
  loadModels();
 }else{
  showAlert(d.error||'Failed','error');
 }
}
async function initModels(){
 if(!confirm('Initialize default models? This will add all default AI models.'))return;
 const d=await api('/models/init','POST');
 showAlert(d.message||'Models initialized!');
 loadModels();
}
// Settings
async function loadSettings(){
 const[models,settings]=await Promise.all([api('/models'),api('/settings')]);
 const sel=document.getElementById('defaultModel');
 if(models.models){
  sel.innerHTML=models.models.map(m=>`<option value="${m.id}">${m.emoji} ${m.name}</option>`).join('');
  if(settings.settings&&settings.settings.default_model){
   sel.value=settings.settings.default_model;
  }
 }
 if(settings.settings&&settings.settings.bot_prefix){
  document.getElementById('botPrefix').value=settings.settings.bot_prefix;
 }
}
async function saveSetting(key,value){
 const d=await api('/settings','POST',{[key]:value});
 if(d.success){
  showAlert(`Setting "${key}" saved!`);
 }else{
  showAlert(d.error||'Failed','error');
 }
}
// Logs
async function loadLogs(){
 const d=await api('/logs');
 const tbody=document.getElementById('logsTable');
 if(!d.logs||d.logs.length===0){
  tbody.innerHTML='<tr><td colspan="4" style="text-align:center;color:#666">No logs yet</td></tr>';
  return;
 }
 tbody.innerHTML=d.logs.map(l=>`
  <tr>
   <td style="white-space:nowrap">${l.timestamp||'N/A'}</td>
   <td><code>${l.action}</code></td>
   <td>${l.target}</td>
   <td style="color:#666;font-size:0.9em">${l.details||'-'}</td>
  </tr>
 `).join('');
}
async function clearLogs(){
 if(!confirm('Clear all audit logs?'))return;
 const d=await api('/logs','DELETE');
 if(d.success){
  showAlert('Logs cleared!');
  loadLogs();
 }
}
// Close modal on outside click
document.querySelectorAll('.modal').forEach(modal=>{
 modal.addEventListener('click',e=>{
  if(e.target===modal)modal.classList.remove('show');
 });
});
// Init
loadKeys();
</script>
</body>
</html>'''
def create_app(admin_key=None):
 if not HAS_FLASK:return None
 app=Flask(__name__)
 ADMIN_KEY=admin_key or os.getenv("WEB_ADMIN_KEY",os.getenv("ADMIN_KEY","admin123"))
 def require_auth(f):
  @wraps(f)
  def decorated(*args,**kwargs):
   key=request.headers.get('X-Admin-Key')or request.args.get('key')
   if key!=ADMIN_KEY:return jsonify({"success":False,"error":"Unauthorized"}),401
   return f(*args,**kwargs)
  return decorated
 @app.route('/')
 def index():
  key=request.args.get('key','')
  if key!=ADMIN_KEY:
   return'''<!DOCTYPE html><html><head><title>Login</title>
<style>body{font-family:system-ui;background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}
.box{background:rgba(255,255,255,0.05);padding:40px;border-radius:20px;text-align:center;border:1px solid rgba(255,255,255,0.1)}
h2{margin-bottom:20px}input{padding:15px;width:250px;border-radius:10px;border:1px solid rgba(255,255,255,0.2);background:rgba(0,0,0,0.3);color:#fff;font-size:1em;margin-bottom:15px}
button{padding:15px 40px;background:linear-gradient(135deg,#00d4ff,#00ff88);border:none;border-radius:10px;cursor:pointer;font-weight:bold;font-size:1em}</style></head>
<body><form class="box" method="get"><h2>🔐 Admin Login</h2><input name="key" type="password" placeholder="Enter Admin Key" required><br><button type="submit">Login</button></form></body></html>'''
  return render_template_string(DASHBOARD_HTML,admin_key=ADMIN_KEY)
 @app.route('/health')
 def health():return jsonify({"status":"ok","timestamp":datetime.now().isoformat()})
 @app.route('/api/keys',methods=['GET'])
 @require_auth
 def get_keys():return jsonify({"success":True,"keys":config.get_all_keys()})
 @app.route('/api/keys',methods=['POST'])
 @require_auth
 def add_key():
  d=request.json or{}
  if not d.get('name')or not d.get('value'):return jsonify({"success":False,"error":"name and value required"})
  config.set_key(d['name'],d['value'],d.get('description'))
  return jsonify({"success":True})
 @app.route('/api/keys/<name>',methods=['PUT'])
 @require_auth
 def update_key(name):
  d=request.json or{}
  if not d.get('value'):return jsonify({"success":False,"error":"value required"})
  config.set_key(name,d['value'],d.get('description'))
  return jsonify({"success":True})
 @app.route('/api/keys/<name>',methods=['DELETE'])
 @require_auth
 def delete_key(name):
  config.del_key(name)
  return jsonify({"success":True})
 @app.route('/api/models',methods=['GET'])
 @require_auth
 def get_models():
  category=request.args.get('category')
  return jsonify({"success":True,"models":config.get_all_models(category=category)})
 @app.route('/api/models',methods=['POST'])
 @require_auth
 def add_model():
  d=request.json or{}
  required=['id','provider','name','model_id']
  if not all(d.get(k)for k in required):return jsonify({"success":False,"error":f"Required: {required}"})
  config.add_model(d['id'],d['provider'],d['name'],d['model_id'],d.get('endpoint'),d.get('category','main'),d.get('emoji','🤖'),d.get('description',''),d.get('priority',100))
  return jsonify({"success":True})
 @app.route('/api/models/init',methods=['POST'])
 @require_auth
 def init_models():
  result=config.init_default_models()
  return jsonify({"success":True,"message":"Models initialized"if result else"Models already exist"})
 @app.route('/api/models/<mid>',methods=['PUT'])
 @require_auth
 def update_model(mid):
  d=request.json or{}
  config.update_model(mid,**d)
  return jsonify({"success":True})
 @app.route('/api/models/<mid>',methods=['DELETE'])
 @require_auth
 def delete_model(mid):
  config.del_model(mid)
  return jsonify({"success":True})
 @app.route('/api/settings',methods=['GET'])
 @require_auth
 def get_settings():return jsonify({"success":True,"settings":config.get_all_settings()})
 @app.route('/api/settings',methods=['POST'])
 @require_auth
 def save_settings():
  d=request.json or{}
  for k,v in d.items():config.set_setting(k,v)
  return jsonify({"success":True})
 @app.route('/api/logs',methods=['GET'])
 @require_auth
 def get_logs():return jsonify({"success":True,"logs":config.get_logs()})
 @app.route('/api/logs',methods=['DELETE'])
 @require_auth
 def clear_logs():
  config.clear_logs()
  return jsonify({"success":True})
 return app
def start_web_panel(host="0.0.0.0",port=8080,admin_key=None):
 app=create_app(admin_key)
 if not app:
  print("❌ Flask not installed, web panel disabled")
  return None
 config.init_default_models()
 def run():
  import logging
  log=logging.getLogger('werkzeug')
  log.setLevel(logging.ERROR)
  app.run(host=host,port=port,debug=False,use_reloader=False,threaded=True)
 t=threading.Thread(target=run,daemon=True)
 t.start()
 key=admin_key or os.getenv("WEB_ADMIN_KEY",os.getenv("ADMIN_KEY","admin123"))
 print(f"🌐 Web Panel started: http://{host}:{port}?key={key}")
 return app
def get_key(name):
 return config.get_key(name)
def get_model(mid):
 return config.get_model(mid)
def get_all_models(category=None):
 return config.get_all_models(category)
def get_setting(key,default=None):
 return config.get_setting(key,default)
