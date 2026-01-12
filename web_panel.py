# web_panel.py - Web Panel untuk Discord Bot
import os, json, threading, sqlite3, hashlib
from datetime import datetime
from functools import wraps

try:
    from flask import Flask, request, jsonify, render_template_string
except ImportError:
    Flask = None
    print("⚠️ Flask belum terinstall. Jalankan: pip install flask")

class ConfigManager:
    """Manager untuk API Keys dan Models - disimpan di database"""
    
    def __init__(self, db_path="bot_config.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.lock = threading.Lock()
        self._init_db()
    
    def _init_db(self):
        with self.lock:
            self.conn.executescript('''
                CREATE TABLE IF NOT EXISTS api_keys (
                    name TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    description TEXT,
                    is_active INTEGER DEFAULT 1,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS ai_models (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    name TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    endpoint TEXT,
                    category TEXT DEFAULT 'stable',
                    emoji TEXT DEFAULT '🤖',
                    description TEXT,
                    is_active INTEGER DEFAULT 1,
                    priority INTEGER DEFAULT 100
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT,
                    target TEXT,
                    details TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            ''')
            self.conn.commit()
    
    # ===== API KEYS =====
    def get_key(self, name):
        """Ambil API key berdasarkan nama"""
        with self.lock:
            r = self.conn.execute(
                'SELECT value FROM api_keys WHERE name=? AND is_active=1', (name,)
            ).fetchone()
            return r[0] if r else None
    
    def get_all_keys(self, masked=True):
        """Ambil semua API keys"""
        with self.lock:
            rows = self.conn.execute('SELECT * FROM api_keys').fetchall()
            result = []
            for r in rows:
                value = r[1]
                if masked and value and len(value) > 8:
                    value = value[:4] + "*" * (len(value) - 8) + value[-4:]
                elif masked:
                    value = "****"
                result.append({
                    "name": r[0], "value": value, "description": r[2],
                    "is_active": bool(r[3]), "updated_at": r[4]
                })
            return result
    
    def set_key(self, name, value, description=None):
        """Simpan atau update API key"""
        with self.lock:
            self.conn.execute('''
                INSERT OR REPLACE INTO api_keys (name, value, description, updated_at)
                VALUES (?, ?, COALESCE(?, (SELECT description FROM api_keys WHERE name=?)), CURRENT_TIMESTAMP)
            ''', (name, value, description, name))
            self.conn.commit()
            # Update environment variable juga (untuk runtime)
            env_name = self._to_env_name(name)
            os.environ[env_name] = value
            self._log("SET_KEY", name)
            return True
    
    def delete_key(self, name):
        with self.lock:
            self.conn.execute('DELETE FROM api_keys WHERE name=?', (name,))
            self.conn.commit()
            self._log("DELETE_KEY", name)
            return True
    
    def _to_env_name(self, name):
        """Konversi nama key ke environment variable"""
        mapping = {
            "groq": "GROQ_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "cerebras": "CEREBRAS_API_KEY",
            "sambanova": "SAMBANOVA_API_KEY",
            "cohere": "COHERE_API_KEY",
            "cloudflare_token": "CLOUDFLARE_API_TOKEN",
            "cloudflare_account": "CLOUDFLARE_ACCOUNT_ID",
            "together": "TOGETHER_API_KEY",
            "tavily": "TAVILY_API_KEY",
            "mistral": "MISTRAL_API_KEY",
            "replicate": "REPLICATE_API_TOKEN",
            "huggingface": "HUGGINGFACE_API_KEY",
            "moonshot": "MOONSHOT_API_KEY",
        }
        return mapping.get(name, name.upper() + "_API_KEY")
    
    # ===== AI MODELS =====
    def get_model(self, model_id):
        """Ambil konfigurasi model"""
        with self.lock:
            r = self.conn.execute('SELECT * FROM ai_models WHERE id=?', (model_id,)).fetchone()
            if r:
                return {
                    "id": r[0], "provider": r[1], "name": r[2], "model_id": r[3],
                    "endpoint": r[4], "category": r[5], "emoji": r[6],
                    "description": r[7], "is_active": bool(r[8]), "priority": r[9]
                }
            return None
    
    def get_all_models(self, category=None, active_only=True):
        """Ambil semua models"""
        with self.lock:
            query = 'SELECT * FROM ai_models'
            params = []
            conditions = []
            
            if category:
                conditions.append('category=?')
                params.append(category)
            if active_only:
                conditions.append('is_active=1')
            
            if conditions:
                query += ' WHERE ' + ' AND '.join(conditions)
            query += ' ORDER BY category, priority, name'
            
            rows = self.conn.execute(query, params).fetchall()
            return [{
                "id": r[0], "provider": r[1], "name": r[2], "model_id": r[3],
                "endpoint": r[4], "category": r[5], "emoji": r[6],
                "description": r[7], "is_active": bool(r[8]), "priority": r[9]
            } for r in rows]
    
    def add_model(self, model_id, provider, name, api_model_id, 
                  endpoint=None, category="stable", emoji="🤖", description=""):
        """Tambah model baru"""
        with self.lock:
            self.conn.execute('''
                INSERT OR REPLACE INTO ai_models 
                (id, provider, name, model_id, endpoint, category, emoji, description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (model_id, provider, name, api_model_id, endpoint, category, emoji, description))
            self.conn.commit()
            self._log("ADD_MODEL", model_id, f"{provider}/{api_model_id}")
            return True
    
    def update_model(self, model_id, **kwargs):
        """Update model"""
        with self.lock:
            allowed = ["provider", "name", "model_id", "endpoint", "category", 
                      "emoji", "description", "is_active", "priority"]
            updates = [(k, v) for k, v in kwargs.items() if k in allowed]
            if not updates:
                return False
            
            set_clause = ", ".join([f"{k}=?" for k, _ in updates])
            values = [v for _, v in updates] + [model_id]
            
            self.conn.execute(f'UPDATE ai_models SET {set_clause} WHERE id=?', values)
            self.conn.commit()
            self._log("UPDATE_MODEL", model_id, str(kwargs))
            return True
    
    def delete_model(self, model_id):
        with self.lock:
            self.conn.execute('DELETE FROM ai_models WHERE id=?', (model_id,))
            self.conn.commit()
            self._log("DELETE_MODEL", model_id)
            return True
    
    # ===== SETTINGS =====
    def get_setting(self, key, default=None):
        with self.lock:
            r = self.conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
            return r[0] if r else default
    
    def set_setting(self, key, value):
        with self.lock:
            self.conn.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, str(value)))
            self.conn.commit()
            return True
    
    def get_all_settings(self):
        with self.lock:
            return {r[0]: r[1] for r in self.conn.execute('SELECT * FROM settings')}
    
    # ===== AUDIT LOG =====
    def _log(self, action, target, details=""):
        self.conn.execute(
            'INSERT INTO audit_log (action, target, details) VALUES (?,?,?)',
            (action, target, details)
        )
        self.conn.commit()
    
    def get_logs(self, limit=50):
        with self.lock:
            rows = self.conn.execute(
                'SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?', (limit,)
            ).fetchall()
            return [{"id": r[0], "action": r[1], "target": r[2], 
                    "details": r[3], "timestamp": r[4]} for r in rows]
    
    # ===== INIT DEFAULT MODELS =====
    def init_default_models(self):
        """Inisialisasi model default jika belum ada"""
        if self.get_all_models(active_only=False):
            return  # Sudah ada models
        
        defaults = [
            # Stable
            ("groq", "groq", "Groq", "llama-3.3-70b-versatile", None, "stable", "⚡", "Llama 3.3 70B"),
            ("cerebras", "cerebras", "Cerebras", "llama-3.3-70b", None, "stable", "🧠", "Llama 3.3 70B"),
            ("cloudflare", "cloudflare", "Cloudflare", "@cf/meta/llama-3.3-70b-instruct-fp8-fast", None, "stable", "☁️", "Llama 3.3 70B"),
            ("sambanova", "sambanova", "SambaNova", "Meta-Llama-3.3-70B-Instruct", None, "stable", "🦣", "Llama 3.3 70B"),
            ("tavily", "tavily", "Tavily", "search", None, "stable", "🔍", "Search + Web"),
            ("poll_free", "pollinations", "Poll-Free", "free", None, "stable", "🌸", "Free Unlimited"),
            # Experimental
            ("cohere", "cohere", "Cohere", "command-r-plus-08-2024", None, "experimental", "🔷", "Command R+"),
            ("mistral", "mistral", "Mistral", "mistral-small-latest", None, "experimental", "Ⓜ️", "Mistral Small"),
            ("together", "together", "Together", "meta-llama/Llama-3.3-70B-Instruct-Turbo", None, "experimental", "🤝", "Llama 3.3"),
            # OpenRouter
            ("or_llama", "openrouter", "OR-Llama", "meta-llama/llama-3.3-70b-instruct:free", None, "openrouter", "🦙", "Llama 3.3 70B"),
            ("or_gemini", "openrouter", "OR-Gemini", "google/gemini-2.0-flash-exp:free", None, "openrouter", "🔵", "Gemini 2.0"),
            ("or_deepseek", "openrouter", "OR-DeepSeek", "deepseek/deepseek-chat:free", None, "openrouter", "🌊", "DeepSeek"),
            # Pollinations
            ("p_openai", "pollinations", "Poll-OpenAI", "openai-large", None, "pollinations", "🤖", "OpenAI Large"),
            ("p_claude", "pollinations", "Poll-Claude", "claude-hybridspace", None, "pollinations", "🎭", "Claude Hybrid"),
        ]
        
        for m in defaults:
            self.add_model(*m)
        print(f"✅ Initialized {len(defaults)} default models")


# ===== FLASK WEB APP =====
config = ConfigManager()

def create_app(admin_key=None):
    if Flask is None:
        return None
    
    app = Flask(__name__)
    ADMIN_KEY = admin_key or os.getenv("WEB_ADMIN_KEY", "changeme123")
    
    # HTML Dashboard
    DASHBOARD = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 Bot Panel</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:system-ui;background:#0f0f23;color:#fff;min-height:100vh;padding:20px}
        .container{max-width:1200px;margin:0 auto}
        h1{text-align:center;margin-bottom:30px;color:#00d4ff}
        .tabs{display:flex;gap:10px;justify-content:center;margin-bottom:20px;flex-wrap:wrap}
        .tab{padding:10px 20px;background:#1a1a3e;border:none;color:#fff;border-radius:8px;cursor:pointer}
        .tab:hover,.tab.active{background:#00d4ff;color:#000}
        .panel{display:none;background:#1a1a3e;padding:20px;border-radius:12px}
        .panel.active{display:block}
        .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:15px;margin-top:20px}
        .card{background:#252550;padding:15px;border-radius:10px;border:1px solid #333}
        .card h3{margin-bottom:10px;display:flex;align-items:center;gap:8px}
        .card code{background:#0a0a1a;padding:2px 6px;border-radius:4px;font-size:12px;word-break:break-all}
        .badge{padding:3px 8px;border-radius:10px;font-size:11px}
        .badge-stable{background:#2e7d32}.badge-experimental{background:#f57c00}
        .badge-openrouter{background:#1976d2}.badge-pollinations{background:#7b1fa2}
        .status{width:8px;height:8px;border-radius:50%;margin-left:auto}
        .status.on{background:#4caf50}.status.off{background:#f44336}
        input,select,textarea{width:100%;padding:10px;margin:5px 0;background:#0a0a1a;border:1px solid #333;color:#fff;border-radius:6px}
        input:focus,select:focus{border-color:#00d4ff;outline:none}
        .btn{padding:8px 16px;border:none;border-radius:6px;cursor:pointer;margin:3px}
        .btn-primary{background:#00d4ff;color:#000}.btn-danger{background:#e53935;color:#fff}
        .btn-success{background:#43a047;color:#fff}
        .btn:hover{opacity:0.85}
        .modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.8);justify-content:center;align-items:center;z-index:100}
        .modal.show{display:flex}
        .modal-box{background:#1a1a3e;padding:25px;border-radius:12px;width:90%;max-width:450px}
        .modal-header{display:flex;justify-content:space-between;margin-bottom:15px}
        .close{background:none;border:none;color:#fff;font-size:24px;cursor:pointer}
        table{width:100%;border-collapse:collapse;margin-top:15px}
        th,td{padding:10px;text-align:left;border-bottom:1px solid #333}
        th{background:#0a0a1a}
        .alert{padding:12px;border-radius:8px;margin-bottom:15px}
        .alert-success{background:rgba(76,175,80,0.2);border:1px solid #4caf50}
        .alert-error{background:rgba(244,67,54,0.2);border:1px solid #f44336}
        .header-row{display:flex;justify-content:space-between;align-items:center;margin-bottom:15px}
    </style>
</head>
<body>
<div class="container">
    <h1>🤖 Bot Control Panel</h1>
    <div class="tabs">
        <button class="tab active" onclick="showTab('keys')">🔑 API Keys</button>
        <button class="tab" onclick="showTab('models')">🤖 Models</button>
        <button class="tab" onclick="showTab('settings')">⚙️ Settings</button>
        <button class="tab" onclick="showTab('logs')">📋 Logs</button>
    </div>
    <div id="alert"></div>
    
    <!-- API Keys -->
    <div id="keys" class="panel active">
        <div class="header-row">
            <h2>🔑 API Keys</h2>
            <button class="btn btn-primary" onclick="openModal('keyModal')">+ Add Key</button>
        </div>
        <div id="keysList" class="grid"></div>
    </div>
    
    <!-- Models -->
    <div id="models" class="panel">
        <div class="header-row">
            <h2>🤖 AI Models</h2>
            <button class="btn btn-primary" onclick="openModal('modelModal')">+ Add Model</button>
        </div>
        <div id="modelsList" class="grid"></div>
    </div>
    
    <!-- Settings -->
    <div id="settings" class="panel">
        <h2 style="margin-bottom:15px">⚙️ Settings</h2>
        <div class="grid">
            <div class="card">
                <h3>🌍 Default Model</h3>
                <select id="defaultModel" onchange="saveSetting('default_model',this.value)"></select>
            </div>
            <div class="card">
                <h3>📝 Bot Prefix</h3>
                <input id="prefix" value="." maxlength="3">
                <button class="btn btn-primary" onclick="saveSetting('prefix',document.getElementById('prefix').value)">Save</button>
            </div>
        </div>
    </div>
    
    <!-- Logs -->
    <div id="logs" class="panel">
        <h2 style="margin-bottom:15px">📋 Audit Logs</h2>
        <table><thead><tr><th>Time</th><th>Action</th><th>Target</th><th>Details</th></tr></thead>
        <tbody id="logsTable"></tbody></table>
    </div>
</div>

<!-- Add Key Modal -->
<div id="keyModal" class="modal">
    <div class="modal-box">
        <div class="modal-header"><h3>🔑 Add API Key</h3><button class="close" onclick="closeModal('keyModal')">&times;</button></div>
        <form onsubmit="addKey(event)">
            <label>Provider</label>
            <select id="keyName">
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
            </select>
            <label>API Key</label>
            <input type="password" id="keyValue" required placeholder="sk-xxx...">
            <label>Description (optional)</label>
            <input id="keyDesc" placeholder="My Groq key">
            <button type="submit" class="btn btn-success" style="width:100%;margin-top:10px">Save Key</button>
        </form>
    </div>
</div>

<!-- Add Model Modal -->
<div id="modelModal" class="modal">
    <div class="modal-box">
        <div class="modal-header"><h3>🤖 Add Model</h3><button class="close" onclick="closeModal('modelModal')">&times;</button></div>
        <form onsubmit="addModel(event)">
            <label>Model ID (unique)</label>
            <input id="mId" required placeholder="my_gpt4">
            <label>Provider</label>
            <select id="mProvider">
                <option value="groq">Groq</option>
                <option value="openrouter">OpenRouter</option>
                <option value="cerebras">Cerebras</option>
                <option value="sambanova">SambaNova</option>
                <option value="cloudflare">Cloudflare</option>
                <option value="cohere">Cohere</option>
                <option value="mistral">Mistral</option>
                <option value="together">Together</option>
                <option value="pollinations">Pollinations</option>
            </select>
            <label>Display Name</label>
            <input id="mName" required placeholder="GPT-4 Turbo">
            <label>API Model ID</label>
            <input id="mModelId" required placeholder="gpt-4-turbo">
            <label>Category</label>
            <select id="mCategory">
                <option value="stable">Stable</option>
                <option value="experimental">Experimental</option>
                <option value="openrouter">OpenRouter</option>
                <option value="pollinations">Pollinations</option>
            </select>
            <label>Emoji</label>
            <input id="mEmoji" value="🤖" maxlength="4">
            <label>Description</label>
            <input id="mDesc" placeholder="Fast and accurate">
            <button type="submit" class="btn btn-success" style="width:100%;margin-top:10px">Add Model</button>
        </form>
    </div>
</div>

<script>
const API = '/api';
const KEY = '{{ admin_key }}';
const headers = {'Content-Type':'application/json','X-Admin-Key':KEY};

function showTab(id) {
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    event.target.classList.add('active');
    if(id==='keys') loadKeys();
    if(id==='models') loadModels();
    if(id==='settings') loadSettings();
    if(id==='logs') loadLogs();
}

function openModal(id) { document.getElementById(id).classList.add('show'); }
function closeModal(id) { document.getElementById(id).classList.remove('show'); }

function alert(msg, type='success') {
    document.getElementById('alert').innerHTML = `<div class="alert alert-${type}">${msg}</div>`;
    setTimeout(() => document.getElementById('alert').innerHTML = '', 4000);
}

async function api(endpoint, method='GET', data=null) {
    const opts = {method, headers};
    if(data) opts.body = JSON.stringify(data);
    const r = await fetch(API + endpoint, opts);
    return r.json();
}

// Keys
async function loadKeys() {
    const d = await api('/keys');
    document.getElementById('keysList').innerHTML = d.keys.map(k => `
        <div class="card">
            <h3>🔑 ${k.name} <span class="status ${k.is_active?'on':'off'}"></span></h3>
            <p><code>${k.value}</code></p>
            <p style="color:#888;font-size:12px;margin-top:5px">${k.description||''}</p>
            <div style="margin-top:10px">
                <button class="btn btn-primary" onclick="editKey('${k.name}')">Edit</button>
                <button class="btn btn-danger" onclick="deleteKey('${k.name}')">Delete</button>
            </div>
        </div>
    `).join('');
}

async function addKey(e) {
    e.preventDefault();
    const d = await api('/keys', 'POST', {
        name: document.getElementById('keyName').value,
        value: document.getElementById('keyValue').value,
        description: document.getElementById('keyDesc').value
    });
    if(d.success) { alert('Key saved!'); closeModal('keyModal'); loadKeys(); }
    else alert(d.error, 'error');
}

async function editKey(name) {
    const v = prompt('Enter new API key:');
    if(v) {
        await api(`/keys/${name}`, 'PUT', {value: v});
        alert('Key updated!'); loadKeys();
    }
}

async function deleteKey(name) {
    if(confirm(`Delete ${name}?`)) {
        await api(`/keys/${name}`, 'DELETE');
        alert('Key deleted!'); loadKeys();
    }
}

// Models
async function loadModels() {
    const d = await api('/models');
    document.getElementById('modelsList').innerHTML = d.models.map(m => `
        <div class="card">
            <h3>${m.emoji} ${m.name} 
                <span class="badge badge-${m.category}">${m.category}</span>
                <span class="status ${m.is_active?'on':'off'}"></span>
            </h3>
            <p><b>Provider:</b> ${m.provider}</p>
            <p><b>Model:</b> <code>${m.model_id}</code></p>
            <p style="color:#888;font-size:12px">${m.description||''}</p>
            <div style="margin-top:10px">
                <button class="btn btn-primary" onclick="editModel('${m.id}')">Edit</button>
                <button class="btn btn-danger" onclick="deleteModel('${m.id}')">Delete</button>
            </div>
        </div>
    `).join('');
}

async function addModel(e) {
    e.preventDefault();
    const d = await api('/models', 'POST', {
        id: document.getElementById('mId').value,
        provider: document.getElementById('mProvider').value,
        name: document.getElementById('mName').value,
        model_id: document.getElementById('mModelId').value,
        category: document.getElementById('mCategory').value,
        emoji: document.getElementById('mEmoji').value,
        description: document.getElementById('mDesc').value
    });
    if(d.success) { alert('Model added!'); closeModal('modelModal'); loadModels(); }
    else alert(d.error, 'error');
}

async function editModel(id) {
    const v = prompt('Enter new Model API ID:');
    if(v) {
        await api(`/models/${id}`, 'PUT', {model_id: v});
        alert('Model updated!'); loadModels();
    }
}

async function deleteModel(id) {
    if(confirm(`Delete ${id}?`)) {
        await api(`/models/${id}`, 'DELETE');
        alert('Model deleted!'); loadModels();
    }
}

// Settings
async function loadSettings() {
    const models = await api('/models');
    const settings = await api('/settings');
    
    const sel = document.getElementById('defaultModel');
    sel.innerHTML = models.models.map(m => 
        `<option value="${m.id}">${m.emoji} ${m.name}</option>`
    ).join('');
    
    if(settings.settings.default_model) sel.value = settings.settings.default_model;
    if(settings.settings.prefix) document.getElementById('prefix').value = settings.settings.prefix;
}

async function saveSetting(key, value) {
    await api('/settings', 'POST', {[key]: value});
    alert(`${key} updated!`);
}

// Logs
async function loadLogs() {
    const d = await api('/logs');
    document.getElementById('logsTable').innerHTML = d.logs.map(l => 
        `<tr><td>${l.timestamp}</td><td>${l.action}</td><td>${l.target}</td><td>${l.details}</td></tr>`
    ).join('');
}

// Init
loadKeys();
</script>
</body>
</html>
'''
    
    def require_admin(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            key = request.headers.get('X-Admin-Key') or request.args.get('key')
            if key != ADMIN_KEY:
                return jsonify({"success": False, "error": "Unauthorized"}), 401
            return f(*args, **kwargs)
        return wrapper
    
    @app.route('/')
    def index():
        key = request.args.get('key', '')
        if key != ADMIN_KEY:
            return '''<form method="get" style="margin:100px auto;max-width:300px;text-align:center;font-family:system-ui">
                <h2>🔐 Login</h2><input name="key" type="password" placeholder="Admin Key" 
                style="padding:10px;width:100%;margin:10px 0"><button style="padding:10px 20px">Enter</button></form>'''
        return render_template_string(DASHBOARD, admin_key=ADMIN_KEY)
    
    @app.route('/api/keys', methods=['GET'])
    @require_admin
    def get_keys():
        return jsonify({"success": True, "keys": config.get_all_keys()})
    
    @app.route('/api/keys', methods=['POST'])
    @require_admin
    def add_key():
        d = request.json
        if not d or not d.get('name') or not d.get('value'):
            return jsonify({"success": False, "error": "name and value required"})
        config.set_key(d['name'], d['value'], d.get('description'))
        return jsonify({"success": True})
    
    @app.route('/api/keys/<name>', methods=['PUT'])
    @require_admin
    def update_key(name):
        d = request.json
        config.set_key(name, d['value'], d.get('description'))
        return jsonify({"success": True})
    
    @app.route('/api/keys/<name>', methods=['DELETE'])
    @require_admin
    def delete_key(name):
        config.delete_key(name)
        return jsonify({"success": True})
    
    @app.route('/api/models', methods=['GET'])
    @require_admin
    def get_models():
        return jsonify({"success": True, "models": config.get_all_models(active_only=False)})
    
    @app.route('/api/models', methods=['POST'])
    @require_admin
    def add_model():
        d = request.json
        config.add_model(d['id'], d['provider'], d['name'], d['model_id'],
                        d.get('endpoint'), d.get('category','stable'),
                        d.get('emoji','🤖'), d.get('description',''))
        return jsonify({"success": True})
    
    @app.route('/api/models/<mid>', methods=['PUT'])
    @require_admin
    def update_model(mid):
        config.update_model(mid, **request.json)
        return jsonify({"success": True})
    
    @app.route('/api/models/<mid>', methods=['DELETE'])
    @require_admin
    def delete_model(mid):
        config.delete_model(mid)
        return jsonify({"success": True})
    
    @app.route('/api/settings', methods=['GET'])
    @require_admin
    def get_settings():
        return jsonify({"success": True, "settings": config.get_all_settings()})
    
    @app.route('/api/settings', methods=['POST'])
    @require_admin
    def save_settings():
        for k, v in request.json.items():
            config.set_setting(k, v)
        return jsonify({"success": True})
    
    @app.route('/api/logs', methods=['GET'])
    @require_admin
    def get_logs():
        return jsonify({"success": True, "logs": config.get_logs()})
    
    @app.route('/health')
    def health():
        return jsonify({"status": "ok"})
    
    return app


def start_web_panel(host="0.0.0.0", port=5000, admin_key=None):
    """Start web panel di background thread"""
    app = create_app(admin_key)
    if not app:
        print("❌ Flask not installed")
        return None
    
    config.init_default_models()
    
    def run():
        import logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)
        app.run(host=host, port=port, debug=False, use_reloader=False)
    
    t = threading.Thread(target=run, daemon=True)
    t.start()
    
    key = admin_key or os.getenv("WEB_ADMIN_KEY", "changeme123")
    print(f"🌐 Web Panel: http://{host}:{port}?key={key}")
    return app


# Helper functions untuk bot
def get_key(name):
    """Ambil API key (dari DB atau env fallback)"""
    return config.get_key(name) or os.getenv(config._to_env_name(name), "")

def get_model(model_id):
    """Ambil config model"""
    return config.get_model(model_id)

def get_active_models(category=None):
    """Ambil semua model aktif"""
    return config.get_all_models(category, active_only=True)

def get_default_model():
    """Ambil default model"""
    return config.get_setting("default_model", "groq")
