import discord
import os
import io
import re
import time
import json
import logging
import sqlite3
import random
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import quote
from discord import app_commands
from discord.ext import commands
from keep_alive import keep_alive

# ==============================================================================
# 📋 LOGGING CONFIGURATION
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ==============================================================================
# 🔑 ENVIRONMENT VARIABLES
# ==============================================================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
KEY_GROQ = os.getenv("GROQ_API_KEY")
KEY_GEMINI = os.getenv("GEMINI_API_KEY")
KEY_OPENAI = os.getenv("OPENAI_API_KEY")
KEY_OPENROUTER = os.getenv("OPENROUTER_API_KEY")
SCRAPER_KEY = os.getenv("SCRAPER_API_KEY")
OWNER_IDS = [int(x) for x in os.getenv("OWNER_IDS", "0").split(",") if x.isdigit()]

if not DISCORD_TOKEN:
    print("❌ FATAL ERROR: DISCORD_TOKEN is missing!")
    exit(1)

# ==============================================================================
# 🤖 BOT SETUP
# ==============================================================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ==============================================================================
# 📦 GLOBAL VARIABLES (LAZY LOADING)
# ==============================================================================
_groq = None
_openai = None
_curl = None
_requests = None
_pd = None
_openpyxl = None

def get_groq():
    global _groq
    if _groq is None and KEY_GROQ:
        from groq import Groq
        _groq = Groq(api_key=KEY_GROQ)
    return _groq

def get_openai():
    global _openai
    if _openai is None and KEY_OPENAI:
        from openai import OpenAI
        _openai = OpenAI(api_key=KEY_OPENAI)
    return _openai

def get_curl():
    global _curl
    if _curl is None:
        from curl_cffi import requests as curl_requests
        _curl = curl_requests
    return _curl

def get_requests():
    global _requests
    if _requests is None:
        import requests
        _requests = requests
    return _requests

def get_pandas():
    global _pd
    if _pd is None:
        import pandas as pd
        _pd = pd
    return _pd

def get_openpyxl():
    global _openpyxl
    if _openpyxl is None:
        import openpyxl
        _openpyxl = openpyxl
    return _openpyxl

# ==============================================================================
# 💾 DATABASE SYSTEM (SQLite)
# ==============================================================================
class Database:
    def __init__(self, path="bot.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.setup_tables()
    
    def setup_tables(self):
        c = self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER,
            gid INTEGER,
            cmd TEXT,
            prompt TEXT,
            resp TEXT,
            ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS blacklist(
            uid INTEGER PRIMARY KEY,
            reason TEXT,
            by_uid INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS stats(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cmd TEXT,
            uid INTEGER,
            ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        self.conn.commit()

    def log(self, uid, gid, cmd, p, r):
        self.conn.execute('INSERT INTO history(uid,gid,cmd,prompt,resp)VALUES(?,?,?,?,?)', (uid, gid, cmd, p, r[:4000]))
        self.conn.commit()

    def hist(self, uid, n=5):
        return self.conn.execute('SELECT prompt,resp FROM history WHERE uid=? ORDER BY ts DESC LIMIT ?', (uid, n)).fetchall()

    def banned(self, uid):
        return self.conn.execute('SELECT 1 FROM blacklist WHERE uid=?', (uid,)).fetchone() is not None

    def ban(self, uid, r, by):
        self.conn.execute('INSERT OR REPLACE INTO blacklist VALUES(?,?,?)', (uid, r, by))
        self.conn.commit()

    def unban(self, uid):
        self.conn.execute('DELETE FROM blacklist WHERE uid=?', (uid,))
        self.conn.commit()

    def stat(self, cmd, uid):
        self.conn.execute('INSERT INTO stats(cmd,uid)VALUES(?,?)', (cmd, uid))
        self.conn.commit()

    def get_stats(self):
        return self.conn.execute('SELECT cmd,COUNT(*) FROM stats GROUP BY cmd ORDER BY COUNT(*) DESC').fetchall()

db = Database()

# ==============================================================================
# ⏱️ RATE LIMITER
# ==============================================================================
class RL:
    def __init__(self):
        self.cd = defaultdict(lambda: defaultdict(float))
    
    def ok(self, uid, cmd, t=5):
        now = time.time()
        if now - self.cd[uid][cmd] < t:
            return False, t - (now - self.cd[uid][cmd])
        self.cd[uid][cmd] = now
        return True, 0

rl = RL()

def rate(s=5):
    async def p(i: discord.Interaction) -> bool:
        ok, r = rl.ok(i.user.id, i.command.name, s)
        if not ok:
            await i.response.send_message(f"⏳ Tunggu **{r:.1f}s** lagi.", ephemeral=True)
            return False
        return True
    return app_commands.check(p)

def owner():
    async def p(i: discord.Interaction) -> bool:
        if i.user.id not in OWNER_IDS:
            await i.response.send_message("❌ Command ini khusus Owner!", ephemeral=True)
            return False
        return True
    return app_commands.check(p)

def noban():
    async def p(i: discord.Interaction) -> bool:
        if db.banned(i.user.id):
            await i.response.send_message("🚫 Akun Anda telah di-blacklist!", ephemeral=True)
            return False
        return True
    return app_commands.check(p)

# ==============================================================================
# 🧠 MEMORY SYSTEM
# ==============================================================================
@dataclass
class Msg:
    role: str
    content: str
    ts: float

class Memory:
    def __init__(self):
        self.data = defaultdict(list)
    
    def add(self, uid, role, txt):
        now = time.time()
        # Hapus chat lama (> 30 menit)
        self.data[uid] = [m for m in self.data[uid] if now - m.ts < 1800]
        self.data[uid].append(Msg(role, txt, now))
        # Keep max 10 messages
        if len(self.data[uid]) > 10:
            self.data[uid] = self.data[uid][-10:]
    
    def get(self, uid):
        return [{"role": m.role, "content": m.content} for m in self.data[uid]]
    
    def clear(self, uid):
        self.data[uid] = []

mem = Memory()

# ==============================================================================
# 📂 FILE READER
# ==============================================================================
class FileReader:
    @staticmethod
    async def read(attachment) -> tuple:
        fn = attachment.filename.lower()
        content = await attachment.read()
        try:
            if fn.endswith(('.xlsx', '.xls')):
                return FileReader._excel(content, fn)
            elif fn.endswith('.csv'):
                return FileReader._csv(content)
            elif fn.endswith('.json'):
                return FileReader._json(content)
            else:
                return FileReader._text(content, fn)
        except Exception as e:
            return f"Error reading file: {e}", "error", {}

    @staticmethod
    def _excel(content, fn):
        pd = get_pandas()
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None)
        result = []
        meta = {"sheets": [], "rows": 0}
        for name, df in sheets.items():
            meta["sheets"].append(name)
            meta["rows"] += len(df)
            result.append(f"=== SHEET: {name} ===\nSize: {len(df)}x{len(df.columns)}\nColumns: {','.join(map(str, df.columns.tolist()))}\n{df.to_string(max_rows=50)}")
        return '\n'.join(result), "excel", meta

    @staticmethod
    def _csv(content):
        pd = get_pandas()
        df = pd.read_csv(io.StringIO(content.decode('utf-8', errors='ignore')))
        return f"CSV {len(df)}x{len(df.columns)}\n{df.to_string(max_rows=50)}", "csv", {"rows": len(df)}

    @staticmethod
    def _json(content):
        data = json.loads(content.decode('utf-8', errors='ignore'))
        return json.dumps(data, indent=2, ensure_ascii=False)[:8000], "json", {"type": type(data).__name__}

    @staticmethod
    def _text(content, fn):
        txt = content.decode('utf-8', errors='ignore')
        return txt[:8000], fn.split('.')[-1] if '.' in fn else 'txt', {}

freader = FileReader()

# ==============================================================================
# 📊 EXCEL GENERATOR
# ==============================================================================
class ExcelGen:
    @staticmethod
    def generate(data) -> io.BytesIO:
        openpyxl = get_openpyxl()
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
        
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        
        sheets = data.get("sheets", [])
        if not sheets:
            sheets = [{"name": "Sheet1", "headers": data.get("headers", []), "data": data.get("data", [])}]
        
        for sh in sheets:
            ws = wb.create_sheet(title=str(sh.get("name", "Sheet1"))[:31])
            headers = sh.get("headers", [])
            rows = sh.get("data", [])
            formulas = sh.get("formulas", {})
            styling = sh.get("styling", {})
            
            # Styles
            header_color = styling.get("header_color", "4472C4")
            header_font_color = styling.get("header_font_color", "FFFFFF")
            
            hfill = PatternFill(start_color=header_color, end_color=header_color, fill_type="solid")
            hfont = Font(bold=True, color=header_font_color)
            border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
            
            # Write Headers
            for ci, h in enumerate(headers, 1):
                c = ws.cell(row=1, column=ci, value=str(h))
                c.font = hfont
                c.fill = hfill
                c.border = border
                c.alignment = Alignment(horizontal='center')
            
            # Write Data
            for ri, row in enumerate(rows, 2):
                if not isinstance(row, (list, tuple)):
                    row = [row]
                for ci, val in enumerate(row, 1):
                    c = ws.cell(row=ri, column=ci, value=val)
                    c.border = border
                    
                    # Number Format
                    cl = get_column_letter(ci)
                    nf = styling.get("number_format", {})
                    if isinstance(nf, dict) and cl in nf:
                        c.number_format = nf[cl]
                    elif isinstance(val, (int, float)) and abs(val) >= 1000:
                        c.number_format = '#,##0'
            
            # Write Formulas
            for ref, f in formulas.items():
                try:
                    ws[ref] = f
                    ws[ref].border = border
                    ws[ref].alignment = Alignment(horizontal='right')
                except:
                    pass
            
            # Summary Row
            summary = sh.get("summary", {})
            if summary and rows:
                lr = len(rows) + 1
                sr = lr + 1
                for cl, f in summary.get("formulas", {}).items():
                    try:
                        ws[f"{cl}{sr}"] = str(f).replace("{last}", str(lr))
                        ws[f"{cl}{sr}"].font = Font(bold=True)
                        ws[f"{cl}{sr}"].border = border
                    except:
                        pass
            
            # Auto Width
            for ci in range(1, max(len(headers), 1) + 1):
                cl = get_column_letter(ci)
                max_len = len(str(headers[ci-1])) if ci <= len(headers) else 10
                for r in rows:
                    if isinstance(r, (list, tuple)) and ci <= len(r):
                        max_len = max(max_len, len(str(r[ci-1])))
                ws.column_dimensions[cl].width = min(max(max_len + 5, 15), 60)
            
            ws.freeze_panes = 'A2'
        
        out = io.BytesIO()
        wb.save(out)
        out.seek(0)
        return out

egen = ExcelGen()

# ==============================================================================
# 🧠 AI LOGIC & PROMPT
# ==============================================================================
EXCEL_PROMPT = '''KAMU ADALAH EXCEL EXPERT AI.

ATURAN KETAT (WAJIB PATUHI):
1. Output HARUS berupa JSON valid. Tidak boleh ada teks lain di luar blok JSON.
2. Pastikan semua tanda kurung { } [ ] tertutup dengan benar.
3. Angka harus berupa tipe number (15000), JANGAN string ("15000") kecuali itu teks.
4. Gunakan Bahasa Indonesia yang sopan.

FORMAT OUTPUT JSON:

[JIKA DIMINTA MEMBUAT FILE EXCEL]:
{
    "action": "generate_excel",
    "message": "Deskripsi singkat tentang file yang dibuat.",
    "excel_data": {
        "filename": "output.xlsx",
        "sheets": [
            {
                "name": "Sheet1",
                "headers": ["Kolom1", "Kolom2", "Total"],
                "data": [
                    ["Item A", 100, 200],
                    ["Item B", 150, 250]
                ],
                "formulas": {
                    "C2": "=A2+B2",
                    "C3": "=A3+B3"
                },
                "styling": {
                    "header_color": "4472C4",
                    "number_format": {"B": "#,##0"}
                },
                "summary": {
                    "formulas": {"B": "=SUM(B2:B{last})"}
                }
            }
        ]
    }
}

[JIKA HANYA BERTANYA/ANALISIS]:
{
    "action": "text_only",
    "message": "Tuliskan jawaban atau hasil analisis di sini secara lengkap."
}
'''

OR_FREE = {
    "llama": "meta-llama/llama-3.3-70b-instruct:free",
    "gemini": "google/gemini-2.0-flash-exp:free",
    "mistral": "mistralai/mistral-7b-instruct:free",
    "qwen": "qwen/qwen-2-7b-instruct:free"
}

# --- AI FUNCTIONS ---

def call_groq(msgs):
    cl = get_groq()
    if not cl:
        return None
    try:
        r = cl.chat.completions.create(messages=msgs, model="llama-3.3-70b-versatile", temperature=0.2, max_tokens=8000)
        return r.choices[0].message.content
    except Exception as e:
        logger.warning(f"Groq Error: {e}")
        return None

def call_openrouter(msgs, model_key="llama"):
    if not KEY_OPENROUTER:
        return None
    try:
        req = get_requests()
        r = req.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {KEY_OPENROUTER}", "Content-Type": "application/json"},
            json={
                "model": OR_FREE.get(model_key, OR_FREE["llama"]),
                "messages": msgs,
                "temperature": 0.2,
                "max_tokens": 8000
            },
            timeout=60
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning(f"OpenRouter Error: {e}")
    return None

def call_gemini(prompt):
    if not KEY_GEMINI:
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=KEY_GEMINI)
        # Try multiple models for redundancy
        for model_name in ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-pro"]:
            try:
                m = genai.GenerativeModel(model_name)
                r = m.generate_content(f"{EXCEL_PROMPT}\n\nUser: {prompt}")
                if r and r.text:
                    return r.text
            except:
                continue
    except:
        pass
    return None

def call_pollinations(prompt):
    try:
        req = get_requests()
        # Pollinations usually works best with GET for simple prompts
        full_prompt = f"{EXCEL_PROMPT}\n\nUser: {prompt}"
        r = req.get(f"https://text.pollinations.ai/{quote(full_prompt[:2000])}", timeout=60)
        if r.ok and len(r.text) > 10:
            return r.text
    except Exception as e:
        logger.warning(f"Pollinations Error: {e}")
    return None

def ask_ai(prompt, uid=None, model="auto"):
    msgs = [{"role": "system", "content": EXCEL_PROMPT}, {"role": "user", "content": prompt}]
    
    if uid:
        history = mem.get(uid)
        if history:
            msgs = [{"role": "system", "content": EXCEL_PROMPT}] + history + [{"role": "user", "content": prompt}]
    
    result = None
    used_model = "none"
    
    # Direct Selection
    if model == "groq":
        result = call_groq(msgs)
        used_model = "Groq"
    elif model == "gemini":
        result = call_gemini(prompt)
        used_model = "Gemini"
    elif model == "pollinations":
        result = call_pollinations(prompt)
        used_model = "Pollinations"
    elif model.startswith("or_"):
        mk = model[3:]
        result = call_openrouter(msgs, mk)
        used_model = f"OpenRouter({mk})"
    else:  # AUTO MODE
        # Order: Groq -> OpenRouter -> Gemini -> Pollinations
        result = call_groq(msgs)
        if result:
            used_model = "Groq"
        else:
            result = call_openrouter(msgs, "llama")
            if result:
                used_model = "OpenRouter"
            else:
                result = call_gemini(prompt)
                if result:
                    used_model = "Gemini"
                else:
                    result = call_pollinations(prompt)
                    if result:
                        used_model = "Pollinations"
    
    # Fallback if selected model failed
    if not result and model != "auto":
        # Try fallbacks silently
        if not result: result = call_groq(msgs); used_model = "Groq (Fallback)"
        if not result: result = call_openrouter(msgs, "llama"); used_model = "OpenRouter (Fallback)"
        if not result: result = call_pollinations(prompt); used_model = "Pollinations (Fallback)"
    
    if not result:
        return '{"action":"text_only","message":"❌ Semua AI sedang sibuk atau down."}', "none"
    
    if uid and result:
        mem.add(uid, "user", prompt)
        mem.add(uid, "assistant", result)
    
    return result, used_model

def fix_json(text):
    text = text.strip()
    text = re.sub(r',(\s*[}\]])', r'\1', text) # Remove trailing commas
    text = re.sub(r'"\s*\.\s*"', '","', text) # Fix dot separators
    text = text.replace("'", '"')
    # Auto close brackets
    ob = text.count('{')
    cb = text.count('}')
    if ob > cb: text += '}' * (ob - cb)
    osb = text.count('[')
    csb = text.count(']')
    if osb > csb: text += ']' * (osb - csb)
    return text

def parse_ai(resp):
    resp = resp.strip()
    if resp.startswith('```'):
        m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', resp)
        if m: resp = m.group(1).strip()
    
    try:
        return json.loads(resp)
    except:
        pass
    
    try:
        # Try extracting JSON object
        m = re.search(r'(\{[\s\S]*\})', resp)
        if m:
            jt = m.group(1)
            try: return json.loads(jt)
            except:
                jt = fix_json(jt)
                try: return json.loads(jt)
                except: pass
    except:
        pass
    
    return {"action": "text_only", "message": resp}

def split_msg(text, limit=1900):
    if len(text) <= limit:
        return [text]
    chunks = []
    current = ""
    for line in text.split('\n'):
        if len(current) + len(line) + 1 > limit:
            if current: chunks.append(current)
            current = line
        else:
            current += ('\n' if current else '') + line
    if current:
        chunks.append(current)
    return chunks or [text[:limit]]

# ==============================================================================
# 🕵️ DUMP SYSTEM (Executor Simulation - NO CHANGES HERE!)
# ==============================================================================
def get_executor_headers():
    # ID Game Populer
    fake_place_id = random.choice(["2753915549", "6284583030", "155615604"])
    fake_job_id = os.urandom(16).hex()
    
    return {
        "User-Agent": "Roblox/WinInet", 
        "Roblox-Place-Id": fake_place_id,
        "Roblox-Game-Id": fake_job_id,
        "Roblox-Session-Id": os.urandom(20).hex(),
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Fingerprint": os.urandom(32).hex()
    }

def valid_url(u):
    return u.startswith(("http://", "https://")) and not any(x in u.lower() for x in ["localhost", "127.0.0.1"])

# ==============================================================================
# 📡 EVENTS & COMMANDS
# ==============================================================================
@bot.event
async def on_ready():
    logger.info(f'🔥 {bot.user} is Online!')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="/help"))
    try:
        await bot.tree.sync()
        logger.info("✅ Slash Commands Synced")
    except Exception as e:
        logger.error(f"Sync Error: {e}")

@bot.tree.error
async def on_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    try:
        await interaction.response.send_message(f"❌ Error: {str(error)[:100]}", ephemeral=True)
    except:
        pass

# --- /dump ---
@bot.tree.command(name="dump", description="Dump script (Mode: Executor Simulation)")
@app_commands.describe(url="URL Script")
@rate(10)
@noban()
async def dump(interaction: discord.Interaction, url: str):
    await interaction.response.defer()

    if not SCRAPER_KEY:
        return await interaction.followup.send("❌ API Key Error: Scraper Key missing!")

    try:
        req = get_requests()
        payload = {
            'api_key': SCRAPER_KEY,
            'url': url,
            'keep_headers': 'true'
        }
        fake_headers = get_executor_headers()

        response = req.get(
            'http://api.scraperapi.com', 
            params=payload, 
            headers=fake_headers,
            timeout=30
        )

        if response.status_code == 200:
            content = response.text
            if "<!DOCTYPE html>" in content or "<html" in content[:100]:
                file_ext = "html"
                status_text = "⚠️ **Peringatan:** Target mendeteksi bot dan mengirim Halaman Web."
            else:
                file_ext = "lua"
                status_text = "✅ **Sukses!** Target mengira ini Executor Asli."

            file_data = io.BytesIO(content.encode("utf-8"))
            
            db.stat("dump", interaction.user.id)
            await interaction.followup.send(
                content=f"{status_text}\nSize: `{len(content)} bytes`",
                file=discord.File(file_data, filename=f"Dump_Result.{file_ext}")
            )
        else:
            await interaction.followup.send(f"❌ Gagal: {response.status_code}")

    except Exception as e:
        await interaction.followup.send(f"💀 Error: {str(e)}")

# --- /ai ---
@bot.tree.command(name="ai", description="🤖 Tanya AI / Buat Excel")
@app_commands.describe(perintah="Perintah untuk AI", file="Upload file", model="Pilih AI")
@app_commands.choices(model=[
    app_commands.Choice(name="🚀 Auto (Recommended)", value="auto"),
    app_commands.Choice(name="⚡ Groq (Fast)", value="groq"),
    app_commands.Choice(name="🧠 Gemini", value="gemini"),
    app_commands.Choice(name="🦙 OpenRouter Llama", value="or_llama"),
    app_commands.Choice(name="🔵 OpenRouter Gemini", value="or_gemini"),
    app_commands.Choice(name="🌺 Pollinations", value="pollinations")])
@rate(10)
@noban()
async def ai_cmd(interaction: discord.Interaction, perintah: str, file: discord.Attachment = None, model: str = "auto"):
    await interaction.response.defer()
    
    try:
        parts = [perintah]
        if file:
            fc, ft, meta = await freader.read(file)
            parts.append(f"\n\nFile: {file.filename}\n{json.dumps(meta, ensure_ascii=False)}\n{fc}")
        
        prompt = '\n'.join(parts)
        resp, used_model = ask_ai(prompt, interaction.user.id, model)
        parsed = parse_ai(resp)
        
        db.stat("ai", interaction.user.id)
        
        if parsed.get("action") == "generate_excel":
            ed = parsed["excel_data"]
            ef = egen.generate(ed)
            filename = ed.get("filename", "output.xlsx")
            if not filename.endswith('.xlsx'): filename += '.xlsx'
            
            await interaction.followup.send(
                content=f"✅ Excel Created using **{used_model}**",
                file=discord.File(ef, filename)
            )
        else:
            msg = parsed.get("message", resp)
            chunks = split_msg(msg)
            await interaction.followup.send(content=f"🤖 **{used_model}**: {chunks[0]}")
            for c in chunks[1:]:
                await interaction.channel.send(c)
                
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}")

# --- /ping ---
@bot.tree.command(name="ping", description="🏓 Cek status bot")
async def ping(i: discord.Interaction):
    await i.response.send_message(f"🏓 Pong! `{round(bot.latency*1000)}ms`")

# --- /help ---
@bot.tree.command(name="help", description="📚 Panduan bot")
async def help(i: discord.Interaction):
    e = discord.Embed(title="📚 Bot Help", color=0x2ECC71)
    e.add_field(name="🔓 /dump", value="Executor Simulation Dump", inline=False)
    e.add_field(name="🤖 /ai", value="Excel & Tanya Jawab AI", inline=False)
    e.add_field(name="🔧 /testai", value="Test Koneksi AI", inline=False)
    await i.response.send_message(embed=e)

# --- /testai ---
@bot.tree.command(name="testai", description="🔧 Test AI")
@owner()
async def testai(i: discord.Interaction):
    await i.response.defer()
    res = []
    # Groq
    try:
        c = get_groq()
        if c: 
            c.chat.completions.create(messages=[{"role":"user","content":"OK"}], model="llama-3.3-70b-versatile", max_tokens=5)
            res.append("✅ Groq")
        else: res.append("❌ Groq (No Key)")
    except: res.append("❌ Groq Error")
    
    # Gemini
    try:
        if call_gemini("OK"): res.append("✅ Gemini")
        else: res.append("❌ Gemini")
    except: res.append("❌ Gemini Error")
    
    # OpenRouter
    try:
        if call_openrouter([{"role":"user","content":"OK"}], "llama"): res.append("✅ OpenRouter")
        else: res.append("❌ OpenRouter")
    except: res.append("❌ OpenRouter Error")
    
    # Pollinations
    try:
        if call_pollinations("OK"): res.append("✅ Pollinations")
        else: res.append("❌ Pollinations")
    except: res.append("❌ Pollinations Error")
    
    await i.followup.send("\n".join(res))

# --- /clear ---
@bot.tree.command(name="clear", description="🧹 Clear Memory")
async def clear(i: discord.Interaction):
    mem.clear(i.user.id)
    await i.response.send_message("🧹 Memory dihapus", ephemeral=True)

# --- /history ---
@bot.tree.command(name="history", description="📜 History")
async def history(i: discord.Interaction):
    h = db.hist(i.user.id)
    if not h: return await i.response.send_message("📭 Empty", ephemeral=True)
    await i.response.send_message(f"📜 Last 5:\n" + "\n".join([f"- {p[:30]}..." for p, r in h]), ephemeral=True)

# --- /stats ---
@bot.tree.command(name="stats", description="📊 Stats")
@owner()
async def stats(i: discord.Interaction):
    st = db.get_stats()
    await i.response.send_message(f"📊 Stats:\n" + "\n".join([f"`{c}`: {n}" for c, n in st]))

# --- /reload ---
@bot.tree.command(name="reload", description="🔄 Reload")
@owner()
async def reload(i: discord.Interaction):
    await bot.tree.sync()
    await i.response.send_message("✅ Synced")

# ==============================================================================
# 🚀 START
# ==============================================================================
if __name__ == "__main__":
    keep_alive()
    time.sleep(1)
    print("🚀 Excel AI Bot Starting...")
    try:
        bot.run(DISCORD_TOKEN, log_handler=None)
    except Exception as e:
        print(f"❌ Error: {e}")    await i.response.send_message(f"📊 Stats:\n"+"\n".join([f"`{c}`: {n}"for c,n in st]))

@bot.tree.command(name="reload",description="🔄 Reload")
@owner()
async def reload(i:discord.Interaction):
    await bot.tree.sync()
    await i.response.send_message("✅ Synced")

if __name__=="__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN,log_handler=None)
