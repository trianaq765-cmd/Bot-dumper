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
from discord import app_commands
from discord.ext import commands

try:
    from keep_alive import keep_alive
except:
    keep_alive = lambda: None

logging.basicConfig(level=logging.INFO, format='%(asctime)s|%(levelname)s|%(message)s')
logger = logging.getLogger(__name__)

# ============ ENVIRONMENT VARIABLES ============
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
KEY_ANTHROPIC = os.getenv("ANTHROPIC_API_KEY")
KEY_GROQ = os.getenv("GROQ_API_KEY")
KEY_OPENROUTER = os.getenv("OPENROUTER_API_KEY")
KEY_CEREBRAS = os.getenv("CEREBRAS_API_KEY")
KEY_SAMBANOVA = os.getenv("SAMBANOVA_API_KEY")
KEY_COHERE = os.getenv("COHERE_API_KEY")
OWNER_IDS = [int(x) for x in os.getenv("OWNER_IDS", "0").split(",") if x.isdigit()]
PREFIX = os.getenv("BOT_PREFIX", "!")

if not DISCORD_TOKEN:
    print("❌ DISCORD_TOKEN tidak ditemukan!")
    exit(1)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

UA_LIST = ["Roblox/WinInet", "Synapse-X/2.0", "Sentinel/3.0", "Krnl/1.0", "Fluxus/1.0"]

# ============ LAZY IMPORTS ============
_groq = None
_curl = None
_requests = None
_openpyxl = None

def get_groq():
    global _groq
    if _groq is None and KEY_GROQ:
        from groq import Groq
        _groq = Groq(api_key=KEY_GROQ)
    return _groq

def get_curl():
    global _curl
    if _curl is None:
        from curl_cffi import requests as r
        _curl = r
    return _curl

def get_requests():
    global _requests
    if _requests is None:
        import requests
        _requests = requests
    return _requests

def get_openpyxl():
    global _openpyxl
    if _openpyxl is None:
        import openpyxl
        _openpyxl = openpyxl
    return _openpyxl

# ============ DATABASE ============
class Database:
    def __init__(self, path="bot.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS user_prefs(
                uid INTEGER PRIMARY KEY,
                model TEXT DEFAULT "auto"
            );
            CREATE TABLE IF NOT EXISTS stats(
                id INTEGER PRIMARY KEY,
                cmd TEXT,
                uid INTEGER,
                ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS blacklist(
                uid INTEGER PRIMARY KEY
            );
        ''')
    
    def get_model(self, uid):
        r = self.conn.execute('SELECT model FROM user_prefs WHERE uid=?', (uid,)).fetchone()
        return r[0] if r else "auto"
    
    def set_model(self, uid, model):
        self.conn.execute('INSERT OR REPLACE INTO user_prefs VALUES(?,?)', (uid, model))
        self.conn.commit()
    
    def stat(self, cmd, uid):
        self.conn.execute('INSERT INTO stats(cmd,uid) VALUES(?,?)', (cmd, uid))
        self.conn.commit()
    
    def banned(self, uid):
        return self.conn.execute('SELECT 1 FROM blacklist WHERE uid=?', (uid,)).fetchone() is not None

db = Database()

# ============ RATE LIMITER ============
class RateLimiter:
    def __init__(self):
        self.cooldowns = defaultdict(lambda: defaultdict(float))
    
    def check(self, user_id, command, cooldown=5):
        now = time.time()
        last_used = self.cooldowns[user_id][command]
        if now - last_used < cooldown:
            return False, cooldown - (now - last_used)
        self.cooldowns[user_id][command] = now
        return True, 0

rl = RateLimiter()

# ============ MEMORY ============
@dataclass
class Message:
    role: str
    content: str
    timestamp: float

class Memory:
    def __init__(self):
        self.data = defaultdict(list)
    
    def add(self, user_id, role, content):
        now = time.time()
        # Remove expired messages (30 min)
        self.data[user_id] = [m for m in self.data[user_id] if now - m.timestamp < 1800]
        self.data[user_id].append(Message(role, content[:1500], now))
        # Keep last 15 messages
        if len(self.data[user_id]) > 15:
            self.data[user_id] = self.data[user_id][-15:]
    
    def get(self, user_id):
        now = time.time()
        self.data[user_id] = [m for m in self.data[user_id] if now - m.timestamp < 1800]
        return [{"role": m.role, "content": m.content} for m in self.data[user_id]]
    
    def clear(self, user_id):
        self.data[user_id] = []

mem = Memory()

# ============ DECORATORS ============
def rate_limit(seconds=5):
    async def predicate(interaction: discord.Interaction) -> bool:
        ok, remaining = rl.check(interaction.user.id, interaction.command.name, seconds)
        if not ok:
            await interaction.response.send_message(f"⏳ Tunggu {remaining:.0f}s", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

def owner_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id not in OWNER_IDS:
            await interaction.response.send_message("❌ Owner only!", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

# ============ EXCEL GENERATOR ============
class ExcelGenerator:
    @staticmethod
    def create(data) -> io.BytesIO:
        try:
            openpyxl = get_openpyxl()
            from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
            from openpyxl.utils import get_column_letter
            
            wb = openpyxl.Workbook()
            wb.remove(wb.active)
            
            sheets = data.get("sheets", [])
            if not sheets:
                sheets = [{
                    "name": "Sheet1",
                    "headers": data.get("headers", []),
                    "data": data.get("data", [])
                }]
            
            for sheet_data in sheets:
                name = str(sheet_data.get("name", "Sheet1"))[:31]
                ws = wb.create_sheet(title=name)
                headers = sheet_data.get("headers", [])
                rows = sheet_data.get("data", [])
                
                # Styles
                header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
                header_font = Font(bold=True, color="FFFFFF", size=11)
                border = Border(
                    left=Side(style='thin'),
                    right=Side(style='thin'),
                    top=Side(style='thin'),
                    bottom=Side(style='thin')
                )
                
                # Headers
                for col_idx, header in enumerate(headers, 1):
                    cell = ws.cell(row=1, column=col_idx, value=str(header))
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.border = border
                    cell.alignment = Alignment(horizontal='center', vertical='center')
                
                # Data rows
                for row_idx, row in enumerate(rows, 2):
                    if not isinstance(row, (list, tuple)):
                        row = [row]
                    for col_idx, val in enumerate(row, 1):
                        try:
                            if isinstance(val, str) and val.replace('.', '').replace('-', '').isdigit():
                                val = float(val) if '.' in val else int(val)
                        except:
                            pass
                        cell = ws.cell(row=row_idx, column=col_idx, value=val)
                        cell.border = border
                        if isinstance(val, (int, float)):
                            cell.number_format = '#,##0' if isinstance(val, int) else '#,##0.00'
                
                # Auto column width
                for col_idx in range(1, len(headers) + 1):
                    col_letter = get_column_letter(col_idx)
                    max_length = len(str(headers[col_idx-1])) if col_idx <= len(headers) else 10
                    for row in rows:
                        if isinstance(row, (list, tuple)) and col_idx <= len(row):
                            max_length = max(max_length, len(str(row[col_idx-1])))
                    ws.column_dimensions[col_letter].width = min(max(max_length + 3, 12), 50)
                
                ws.freeze_panes = 'A2'
            
            output = io.BytesIO()
            wb.save(output)
            output.seek(0)
            return output
        except Exception as e:
            logger.error(f"Excel generation error: {e}")
            raise

excel_gen = ExcelGenerator()

# ============ SYSTEM PROMPT ============
SYSTEM_PROMPT = '''Kamu adalah Excel Expert AI. WAJIB jawab dalam format JSON yang valid.

ATURAN KETAT:
1. Output HANYA JSON, tanpa teks lain
2. Semua angka harus berupa NUMBER (bukan string)
3. Gunakan double quotes untuk string

FORMAT untuk membuat Excel:
{"action":"generate_excel","message":"Deskripsi file","excel_data":{"sheets":[{"name":"NamaSheet","headers":["Kolom1","Kolom2"],"data":[["Isi1",100],["Isi2",200]]}],"filename":"nama_file.xlsx"}}

FORMAT untuk jawab pertanyaan:
{"action":"text_only","message":"Jawaban kamu disini"}

CONTOH untuk Excel:
{"action":"generate_excel","message":"Laporan Penjualan","excel_data":{"sheets":[{"name":"Penjualan","headers":["Produk","Qty","Harga","Total"],"data":[["Laptop",5,15000000,75000000],["Mouse",20,150000,3000000]]}],"filename":"laporan_penjualan.xlsx"}}

Jawab dalam Bahasa Indonesia.'''

# ============ MODEL CONFIGURATIONS ============
OR_MODELS = {
    "llama": "meta-llama/llama-3.3-70b-instruct:free",
    "gemini": "google/gemini-2.0-flash-exp:free",
    "qwen": "qwen/qwen3-32b:free",
    "deepseek": "deepseek/deepseek-chat-v3-0324:free"
}

MODEL_NAMES = {
    "auto": "🚀 Auto",
    "claude": "🟣 Claude",
    "groq": "⚡ Groq",
    "cerebras": "🧠 Cerebras",
    "sambanova": "🦣 SambaNova",
    "cohere": "🔷 Cohere",
    "or_llama": "🦙 OR-Llama",
    "or_gemini": "🔵 OR-Gemini",
    "or_qwen": "🟣 OR-Qwen"
}

# ============ AI PROVIDERS ============

def call_claude(msgs):
    """Call Anthropic Claude API"""
    if not KEY_ANTHROPIC:
        logger.warning("Claude: API key not set")
        return None
    
    try:
        # Separate system prompt
        system_prompt = ""
        claude_messages = []
        
        for m in msgs:
            if m["role"] == "system":
                system_prompt = m["content"]
            else:
                claude_messages.append({
                    "role": m["role"],
                    "content": m["content"]
                })
        
        if not claude_messages:
            claude_messages = [{"role": "user", "content": "Hello"}]
        
        # Ensure starts with user
        if claude_messages[0]["role"] != "user":
            claude_messages.insert(0, {"role": "user", "content": "Hello"})
        
        # Fix alternating roles
        fixed_messages = []
        last_role = None
        for m in claude_messages:
            if m["role"] == last_role:
                if fixed_messages:
                    fixed_messages[-1]["content"] += "\n" + m["content"]
            else:
                fixed_messages.append(m)
                last_role = m["role"]
        
        payload = {
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": 4096,
            "messages": fixed_messages
        }
        
        if system_prompt:
            payload["system"] = system_prompt
        
        response = get_requests().post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": KEY_ANTHROPIC,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json=payload,
            timeout=60
        )
        
        if response.status_code == 200:
            data = response.json()
            if "content" in data and len(data["content"]) > 0:
                text_content = data["content"][0].get("text", "")
                if text_content and text_content.strip():
                    logger.info("Claude: Success")
                    return text_content.strip()
        
        logger.error(f"Claude: {response.status_code} - {response.text[:200]}")
        return None
        
    except Exception as e:
        logger.error(f"Claude exception: {e}")
        return None


def call_groq(msgs):
    """Call Groq API"""
    client = get_groq()
    if not client:
        return None
    try:
        response = client.chat.completions.create(
            messages=msgs,
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            max_tokens=4000
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Groq: {e}")
        return None


def call_cerebras(msgs):
    """Call Cerebras API"""
    if not KEY_CEREBRAS:
        return None
    try:
        response = get_requests().post(
            "https://api.cerebras.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {KEY_CEREBRAS}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.3-70b",
                "messages": msgs,
                "temperature": 0.1,
                "max_tokens": 4000
            },
            timeout=30
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        logger.error(f"Cerebras: {response.status_code}")
        return None
    except Exception as e:
        logger.error(f"Cerebras: {e}")
        return None


def call_openrouter(msgs, model_key="llama"):
    """Call OpenRouter API"""
    if not KEY_OPENROUTER:
        return None
    try:
        model_id = OR_MODELS.get(model_key, OR_MODELS["llama"])
        response = get_requests().post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {KEY_OPENROUTER}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com"
            },
            json={
                "model": model_id,
                "messages": msgs,
                "temperature": 0.1,
                "max_tokens": 4000
            },
            timeout=60
        )
        if response.status_code == 200:
            data = response.json()
            if "choices" in data and data["choices"]:
                return data["choices"][0]["message"]["content"]
        logger.error(f"OpenRouter {model_key}: {response.status_code}")
        return None
    except Exception as e:
        logger.error(f"OpenRouter: {e}")
        return None


def call_sambanova(msgs):
    """Call SambaNova API"""
    if not KEY_SAMBANOVA:
        return None
    try:
        response = get_requests().post(
            "https://api.sambanova.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {KEY_SAMBANOVA}",
                "Content-Type": "application/json"
            },
            json={
                "model": "Meta-Llama-3.3-70B-Instruct",
                "messages": msgs,
                "temperature": 0.1,
                "max_tokens": 4000
            },
            timeout=60
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        return None
    except Exception as e:
        logger.error(f"SambaNova: {e}")
        return None


def call_cohere(msgs):
    """Call Cohere API"""
    if not KEY_COHERE:
        return None
    try:
        preamble = ""
        chat_history = []
        messages = []
        
        for m in msgs:
            if m["role"] == "system":
                preamble = m["content"]
            else:
                messages.append(m)
        
        # All except last go to history
        for m in messages[:-1]:
            role = "USER" if m["role"] == "user" else "CHATBOT"
            chat_history.append({"role": role, "message": m["content"]})
        
        user_msg = messages[-1]["content"] if messages else ""
        
        payload = {
            "model": "command-r-plus-08-2024",
            "message": user_msg,
            "temperature": 0.1
        }
        if preamble:
            payload["preamble"] = preamble
        if chat_history:
            payload["chat_history"] = chat_history
        
        response = get_requests().post(
            "https://api.cohere.com/v1/chat",
            headers={
                "Authorization": f"Bearer {KEY_COHERE}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=60
        )
        if response.status_code == 200:
            return response.json().get("text", "")
        return None
    except Exception as e:
        logger.error(f"Cohere: {e}")
        return None

# ============ AI HELPERS ============

def fix_json(text):
    """Fix common JSON issues"""
    text = text.strip()
    
    # Extract from code blocks
    if text.startswith("```"):
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if match:
            text = match.group(1).strip()
    
    # Fix trailing comma
    text = re.sub(r',\s*([}\]])', r'\1', text)
    
    # Balance brackets
    open_braces = text.count('{')
    close_braces = text.count('}')
    if open_braces > close_braces:
        text += '}' * (open_braces - close_braces)
    
    open_brackets = text.count('[')
    close_brackets = text.count(']')
    if open_brackets > close_brackets:
        text += ']' * (open_brackets - close_brackets)
    
    return text


def parse_response(resp):
    """Parse AI response to JSON"""
    if not resp or not str(resp).strip():
        return {"action": "text_only", "message": "Tidak ada response dari AI"}
    
    resp = str(resp).strip()
    resp = fix_json(resp)
    
    # Try direct parse
    try:
        parsed = json.loads(resp)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    
    # Try to extract JSON object
    try:
        match = re.search(r'(\{[\s\S]*\})', resp)
        if match:
            json_text = fix_json(match.group(1))
            parsed = json.loads(json_text)
            if isinstance(parsed, dict):
                return parsed
    except:
        pass
    
    # Fallback to text
    clean_resp = resp[:1800].strip()
    if not clean_resp:
        clean_resp = "(Response tidak dapat diproses)"
    
    return {"action": "text_only", "message": clean_resp}


def call_ai(model, msgs, prompt):
    """Route to specific AI provider"""
    if model == "claude":
        return call_claude(msgs), "Claude"
    elif model == "groq":
        return call_groq(msgs), "Groq"
    elif model == "cerebras":
        return call_cerebras(msgs), "Cerebras"
    elif model == "sambanova":
        return call_sambanova(msgs), "SambaNova"
    elif model == "cohere":
        return call_cohere(msgs), "Cohere"
    elif model.startswith("or_"):
        model_key = model[3:]
        return call_openrouter(msgs, model_key), f"OR-{model_key}"
    return None, "none"


def ask_ai(prompt, uid=None, model=None):
    """Main AI query function with fallback"""
    if not model or model == "auto":
        model = db.get_model(uid) if uid else "auto"
    
    if uid and model != "auto":
        db.set_model(uid, model)
    
    # Build messages
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    if uid:
        history = mem.get(uid)
        if history:
            msgs.extend(history[-6:])
    msgs.append({"role": "user", "content": prompt})
    
    result = None
    used = "none"
    
    if model != "auto":
        result, used = call_ai(model, msgs, prompt)
        if not result:
            # Fallback chain
            fallback_providers = [
                (lambda: call_claude(msgs), "Claude"),
                (lambda: call_groq(msgs), "Groq"),
                (lambda: call_cerebras(msgs), "Cerebras"),
                (lambda: call_openrouter(msgs, "llama"), "OR-llama")
            ]
            for provider_fn, provider_name in fallback_providers:
                result = provider_fn()
                if result:
                    used = f"{provider_name}(fb)"
                    break
    else:
        # Auto mode - try all providers
        auto_providers = [
            (lambda: call_claude(msgs), "Claude"),
            (lambda: call_groq(msgs), "Groq"),
            (lambda: call_cerebras(msgs), "Cerebras"),
            (lambda: call_openrouter(msgs, "llama"), "OR"),
            (lambda: call_sambanova(msgs), "SN"),
            (lambda: call_cohere(msgs), "Cohere")
        ]
        for provider_fn, provider_name in auto_providers:
            try:
                result = provider_fn()
                if result:
                    used = provider_name
                    break
            except:
                continue
    
    if not result:
        return {"action": "text_only", "message": "❌ Semua AI tidak tersedia"}, "none"
    
    # Save to memory
    if uid:
        mem.add(uid, "user", prompt[:500])
        mem.add(uid, "assistant", result[:500])
    
    parsed = parse_response(result)
    return parsed, used


def split_message(text, limit=1900):
    """Split long messages for Discord"""
    if not text or not str(text).strip():
        return ["(kosong)"]
    
    text = str(text).strip()[:3800]
    
    if len(text) <= limit:
        return [text]
    
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        
        # Try to split at newline
        split_idx = text.rfind('\n', 0, limit)
        if split_idx <= 0:
            split_idx = text.rfind(' ', 0, limit)
        if split_idx <= 0:
            split_idx = limit
        
        chunk = text[:split_idx].strip()
        if chunk:
            chunks.append(chunk)
        text = text[split_idx:].lstrip()
    
    return chunks if chunks else ["(kosong)"]


async def handle_ai_response(ctx_or_interaction, parsed, used, is_reply=True):
    """Handle AI response - send text or generate Excel"""
    try:
        action = parsed.get("action", "text_only")
        message = parsed.get("message", "")
        
        # Clean message
        if message:
            message = str(message).strip()
            message = ''.join(c for c in message if c.isprintable() or c in '\n\r\t')
        
        if action == "generate_excel":
            excel_data = parsed.get("excel_data", {})
            filename = excel_data.get("filename", "output.xlsx")
            
            # Sanitize filename
            filename = re.sub(r'[<>:"/\\|?*]', '_', str(filename))
            if not filename.endswith('.xlsx'):
                filename += '.xlsx'
            filename = filename[:100]
            
            try:
                file_buffer = excel_gen.create(excel_data)
                
                description = message[:500] if message else "File Excel berhasil dibuat"
                
                embed = discord.Embed(
                    title="📊 Excel Dibuat!",
                    description=description,
                    color=0x217346
                )
                embed.add_field(name="📁 File", value=f"`{filename}`", inline=True)
                embed.add_field(name="🤖 Model", value=f"`{used}`", inline=True)
                
                sheets = excel_data.get("sheets", [])
                if sheets:
                    total_rows = sum(len(s.get("data", [])) for s in sheets)
                    embed.add_field(
                        name="📋 Data",
                        value=f"`{len(sheets)} sheet, {total_rows} baris`",
                        inline=True
                    )
                embed.set_footer(text="Excel Expert AI")
                
                discord_file = discord.File(file_buffer, filename)
                
                if is_reply:
                    await ctx_or_interaction.reply(embed=embed, file=discord_file)
                else:
                    await ctx_or_interaction.followup.send(embed=embed, file=discord_file)
                
                return True
                
            except Exception as e:
                logger.error(f"Excel error: {e}")
                error_msg = f"❌ Gagal membuat Excel: `{str(e)[:100]}`"
                if is_reply:
                    await ctx_or_interaction.reply(error_msg)
                else:
                    await ctx_or_interaction.followup.send(error_msg)
                return False
        
        else:
            # Text response
            if not message:
                message = str(parsed)[:1500] if parsed else "(Tidak ada response)"
            
            message = message.strip()
            if not message:
                message = "(Response kosong dari AI)"
            
            chunks = split_message(message)
            first_chunk = chunks[0] if chunks else "(kosong)"
            
            if not first_chunk.strip():
                first_chunk = "(Response kosong)"
            
            embed = discord.Embed(color=0x5865F2)
            embed.set_footer(text=f"🤖 {used}")
            
            if is_reply:
                await ctx_or_interaction.reply(
                    content=first_chunk,
                    embed=embed if len(chunks) == 1 else None
                )
                for chunk in chunks[1:]:
                    if chunk.strip():
                        await ctx_or_interaction.channel.send(chunk)
            else:
                await ctx_or_interaction.followup.send(
                    content=first_chunk,
                    embed=embed if len(chunks) == 1 else None
                )
                for chunk in chunks[1:]:
                    if chunk.strip():
                        await ctx_or_interaction.channel.send(chunk)
            
            return True
    
    except discord.HTTPException as e:
        logger.error(f"Discord HTTP error: {e}")
        error_content = f"❌ Error: `{str(e)[:100]}`"
        try:
            if is_reply:
                await ctx_or_interaction.reply(error_content)
            else:
                await ctx_or_interaction.followup.send(error_content)
        except:
            pass
        return False
    
    except Exception as e:
        logger.error(f"Response handler error: {e}")
        return False

# ============ BOT EVENTS ============

@bot.event
async def on_ready():
    logger.info(f'🔥 {bot.user} online | {len(bot.guilds)} servers')
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{PREFIX}help"
        )
    )
    try:
        synced = await bot.tree.sync()
        logger.info(f"✅ Synced {len(synced)} commands")
    except Exception as e:
        logger.error(f"Sync error: {e}")


@bot.event
async def on_message(msg):
    if msg.author.bot:
        return
    
    # Handle mentions
    if bot.user.mentioned_in(msg) and not msg.mention_everyone:
        content = msg.content
        content = content.replace(f'<@{bot.user.id}>', '').strip()
        content = content.replace(f'<@!{bot.user.id}>', '').strip()
        
        if content:
            if db.banned(msg.author.id):
                return await msg.reply("🚫 Kamu diblokir")
            
            ok, remaining = rl.check(msg.author.id, "mention", 5)
            if not ok:
                return await msg.reply(f"⏳ Tunggu {remaining:.0f}s")
            
            async with msg.channel.typing():
                try:
                    user_model = db.get_model(msg.author.id)
                    parsed, used = ask_ai(content, msg.author.id, user_model)
                    await handle_ai_response(msg, parsed, used, is_reply=True)
                    db.stat("ai", msg.author.id)
                except Exception as e:
                    logger.error(f"Mention error: {e}")
                    await msg.reply(f"❌ Error: `{str(e)[:100]}`")
        else:
            model = db.get_model(msg.author.id)
            model_name = MODEL_NAMES.get(model, model)
            await msg.reply(
                f"👋 Hai! Model kamu: **{model_name}**\n\n"
                f"Ketik pertanyaan setelah mention!"
            )
        return
    
    await bot.process_commands(msg)

# ============ PREFIX COMMANDS ============

@bot.command(name="ai", aliases=["ask", "chat"])
async def cmd_ai(ctx, *, prompt: str = None):
    """Ask AI a question"""
    if db.banned(ctx.author.id):
        return
    
    ok, remaining = rl.check(ctx.author.id, "ai", 8)
    if not ok:
        return await ctx.reply(f"⏳ Tunggu {remaining:.0f}s")
    
    if not prompt:
        return await ctx.reply(f"❌ Gunakan: `{PREFIX}ai <pertanyaan>`")
    
    async with ctx.typing():
        try:
            user_model = db.get_model(ctx.author.id)
            parsed, used = ask_ai(prompt, ctx.author.id, user_model)
            await handle_ai_response(ctx.message, parsed, used, is_reply=True)
            db.stat("ai", ctx.author.id)
        except Exception as e:
            logger.error(f"AI cmd error: {e}")
            await ctx.reply(f"❌ Error: `{str(e)[:100]}`")


@bot.command(name="excel", aliases=["buat", "create"])
async def cmd_excel(ctx, *, prompt: str = None):
    """Create Excel file"""
    if db.banned(ctx.author.id):
        return
    
    ok, remaining = rl.check(ctx.author.id, "excel", 10)
    if not ok:
        return await ctx.reply(f"⏳ Tunggu {remaining:.0f}s")
    
    if not prompt:
        return await ctx.reply(
            f"❌ Gunakan: `{PREFIX}excel <deskripsi>`\n"
            f"Contoh: `{PREFIX}excel buat laporan keuangan bulanan`"
        )
    
    enhanced_prompt = (
        f"BUAT FILE EXCEL untuk: {prompt}\n\n"
        "WAJIB output format generate_excel dengan data lengkap dan profesional."
    )
    
    async with ctx.typing():
        try:
            user_model = db.get_model(ctx.author.id)
            parsed, used = ask_ai(enhanced_prompt, ctx.author.id, user_model)
            
            if parsed.get("action") != "generate_excel":
                msg = parsed.get('message', '')[:300]
                await ctx.reply(
                    f"⚠️ AI tidak menghasilkan Excel. Coba deskripsi lebih spesifik.\n\n"
                    f"Response: {msg}"
                )
                return
            
            await handle_ai_response(ctx.message, parsed, used, is_reply=True)
            db.stat("excel", ctx.author.id)
        except Exception as e:
            logger.error(f"Excel cmd error: {e}")
            await ctx.reply(f"❌ Error: `{str(e)[:100]}`")


@bot.command(name="model", aliases=["m"])
async def cmd_model(ctx, model: str = None):
    """View or change AI model"""
    valid_models = list(MODEL_NAMES.keys())
    
    if not model:
        current = db.get_model(ctx.author.id)
        current_name = MODEL_NAMES.get(current, current)
        
        embed = discord.Embed(title="🤖 Model AI", color=0x3498DB)
        embed.add_field(
            name="Model Kamu",
            value=f"**{current_name}**",
            inline=False
        )
        embed.add_field(
            name="Tersedia",
            value="\n".join([f"`{k}` - {v}" for k, v in MODEL_NAMES.items()]),
            inline=False
        )
        embed.add_field(
            name="Cara Ganti",
            value=f"`{PREFIX}model <nama>`\nContoh: `{PREFIX}model claude`",
            inline=False
        )
        return await ctx.reply(embed=embed)
    
    model = model.lower()
    if model not in valid_models:
        return await ctx.reply(
            f"❌ Model tidak valid!\n\nPilihan: `{', '.join(valid_models)}`"
        )
    
    db.set_model(ctx.author.id, model)
    model_name = MODEL_NAMES.get(model, model)
    await ctx.reply(f"✅ Model diubah ke: **{model_name}**")


@bot.command(name="clear", aliases=["reset"])
async def cmd_clear(ctx):
    """Clear chat memory"""
    mem.clear(ctx.author.id)
    await ctx.reply("🧹 Memory percakapan dihapus!")


@bot.command(name="ping")
async def cmd_ping(ctx):
    """Check bot status"""
    model = db.get_model(ctx.author.id)
    model_name = MODEL_NAMES.get(model, model)
    mem_count = len(mem.get(ctx.author.id))
    
    embed = discord.Embed(title="🏓 Pong!", color=0x00FF00)
    embed.add_field(name="Latency", value=f"`{round(bot.latency * 1000)}ms`")
    embed.add_field(name="Model", value=f"`{model_name}`")
    embed.add_field(name="Memory", value=f"`{mem_count} pesan`")
    await ctx.reply(embed=embed)


@bot.command(name="help", aliases=["h"])
async def cmd_help(ctx):
    """Show help"""
    model = db.get_model(ctx.author.id)
    model_name = MODEL_NAMES.get(model, model)
    
    embed = discord.Embed(
        title="📚 Excel AI Bot",
        description=f"Model kamu: **{model_name}**",
        color=0x217346
    )
    embed.add_field(
        name="🤖 AI Chat",
        value=(
            f"`{PREFIX}ai <pertanyaan>` - Tanya AI\n"
            f"`@{bot.user.name} <pertanyaan>` - Via mention"
        ),
        inline=False
    )
    embed.add_field(
        name="📊 Excel",
        value=(
            f"`{PREFIX}excel <deskripsi>` - Buat file Excel\n"
            f"Contoh: `{PREFIX}excel buat invoice perusahaan`"
        ),
        inline=False
    )
    embed.add_field(
        name="⚙️ Settings",
        value=(
            f"`{PREFIX}model` - Lihat/ganti model AI\n"
            f"`{PREFIX}clear` - Hapus memory chat"
        ),
        inline=False
    )
    embed.add_field(
        name="🔧 Utility",
        value=f"`{PREFIX}dump <url>` - Download script",
        inline=False
    )
    await ctx.reply(embed=embed)


@bot.command(name="dump")
async def cmd_dump(ctx, url: str = None):
    """Download script from URL"""
    if not url:
        return await ctx.reply(f"❌ Gunakan: `{PREFIX}dump <url>`")
    
    ok, remaining = rl.check(ctx.author.id, "dump", 8)
    if not ok:
        return await ctx.reply(f"⏳ Tunggu {remaining:.0f}s")
    
    async with ctx.typing():
        try:
            curl = get_curl()
            ua = random.choice(UA_LIST)
            headers = {
                "User-Agent": ua,
                "Roblox-Place-Id": "2753915549",
                "Accept": "*/*"
            }
            
            resp = curl.get(url, impersonate="chrome110", headers=headers, timeout=20)
            content = resp.text[:1024*1024]  # Limit 1MB
            
            # Detect file type
            ext = "lua"
            if "<!DOCTYPE" in content[:300]:
                ext = "html"
            elif content.strip().startswith("{"):
                ext = "json"
            
            embed = discord.Embed(
                title="🔓 Dump Result",
                color=0x00FF00 if ext == "lua" else 0xFFFF00
            )
            embed.add_field(name="Size", value=f"`{len(content):,} bytes`")
            embed.add_field(name="Type", value=f"`.{ext}`")
            embed.add_field(name="UA", value=f"`{ua[:20]}...`")
            
            db.stat("dump", ctx.author.id)
            
            file_buffer = io.BytesIO(content.encode())
            await ctx.reply(embed=embed, file=discord.File(file_buffer, f"dump.{ext}"))
            
        except Exception as e:
            await ctx.reply(f"💀 Error: `{str(e)[:100]}`")


@bot.command(name="testai")
@commands.is_owner()
async def cmd_testai(ctx):
    """Test all AI providers"""
    async with ctx.typing():
        results = []
        test_msgs = [{"role": "user", "content": "Say OK"}]
        
        tests = [
            ("Claude", lambda: call_claude(test_msgs)),
            ("Groq", lambda: call_groq(test_msgs)),
            ("Cerebras", lambda: call_cerebras(test_msgs)),
            ("SambaNova", lambda: call_sambanova(test_msgs)),
            ("Cohere", lambda: call_cohere(test_msgs)),
            ("OR-Llama", lambda: call_openrouter(test_msgs, "llama")),
        ]
        
        for name, test_fn in tests:
            try:
                result = test_fn()
                if result:
                    preview = result[:30].strip()
                    results.append(f"✅ **{name}**: {preview}")
                else:
                    results.append(f"❌ **{name}**: No response")
            except Exception as e:
                results.append(f"❌ **{name}**: {str(e)[:30]}")
        
        embed = discord.Embed(
            title="🔧 AI Provider Test",
            description="\n".join(results),
            color=0x3498DB
        )
        await ctx.reply(embed=embed)


@bot.command(name="testclaude")
@commands.is_owner()
async def cmd_testclaude(ctx):
    """Debug Claude API specifically"""
    await ctx.reply("🔍 Checking Claude API...")
    
    # Check env var
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return await ctx.reply(
            "❌ `ANTHROPIC_API_KEY` tidak ditemukan!\n\n"
            "Pastikan sudah di-set di environment variables."
        )
    
    # Show masked key
    if len(key) > 14:
        masked = f"{key[:12]}...{key[-4:]}"
    else:
        masked = "***"
    
    await ctx.reply(f"🔑 Key found: `{masked}` (length: {len(key)})")
    
    # Test API call
    async with ctx.typing():
        try:
            import requests
            
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": "Say hello in Indonesian"}]
                },
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                if "content" in data and data["content"]:
                    text = data["content"][0].get("text", "No text")
                    await ctx.reply(f"✅ **Claude Works!**\n```{text[:300]}```")
                else:
                    await ctx.reply(f"⚠️ Unexpected response:\n```{response.text[:500]}```")
            else:
                await ctx.reply(
                    f"❌ **Error {response.status_code}**\n```{response.text[:500]}```"
                )
        
        except Exception as e:
            await ctx.reply(f"❌ **Exception:** `{e}`")

# ============ SLASH COMMANDS ============

@bot.tree.command(name="ai", description="Tanya AI")
@app_commands.describe(prompt="Pertanyaan atau perintah")
@rate_limit(8)
async def slash_ai(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()
    try:
        user_model = db.get_model(interaction.user.id)
        parsed, used = ask_ai(prompt, interaction.user.id, user_model)
        await handle_ai_response(interaction, parsed, used, is_reply=False)
        db.stat("ai", interaction.user.id)
    except Exception as e:
        await interaction.followup.send(f"❌ Error: `{str(e)[:100]}`")


@bot.tree.command(name="excel", description="Buat file Excel")
@app_commands.describe(deskripsi="Deskripsi Excel yang ingin dibuat")
@rate_limit(10)
async def slash_excel(interaction: discord.Interaction, deskripsi: str):
    await interaction.response.defer()
    enhanced = (
        f"BUAT FILE EXCEL untuk: {deskripsi}\n\n"
        "WAJIB output format generate_excel."
    )
    try:
        user_model = db.get_model(interaction.user.id)
        parsed, used = ask_ai(enhanced, interaction.user.id, user_model)
        await handle_ai_response(interaction, parsed, used, is_reply=False)
        db.stat("excel", interaction.user.id)
    except Exception as e:
        await interaction.followup.send(f"❌ Error: `{str(e)[:100]}`")


@bot.tree.command(name="model", description="Lihat atau ganti model AI")
@app_commands.describe(model="Pilih model AI")
@app_commands.choices(model=[
    app_commands.Choice(name=name, value=key)
    for key, name in MODEL_NAMES.items()
])
async def slash_model(interaction: discord.Interaction, model: str = None):
    if model:
        db.set_model(interaction.user.id, model)
        model_name = MODEL_NAMES.get(model, model)
        await interaction.response.send_message(
            f"✅ Model: **{model_name}**",
            ephemeral=True
        )
    else:
        current = db.get_model(interaction.user.id)
        current_name = MODEL_NAMES.get(current, current)
        await interaction.response.send_message(
            f"🤖 Model kamu: **{current_name}**",
            ephemeral=True
        )


@bot.tree.command(name="clear", description="Hapus memory chat")
async def slash_clear(interaction: discord.Interaction):
    mem.clear(interaction.user.id)
    await interaction.response.send_message("🧹 Memory dihapus!", ephemeral=True)


@bot.tree.command(name="ping", description="Cek status bot")
async def slash_ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Pong! `{latency}ms`")


@bot.tree.command(name="reload", description="Sync slash commands")
@owner_only()
async def slash_reload(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        synced = await bot.tree.sync()
        await interaction.followup.send(f"✅ {len(synced)} commands synced")
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}")

# ============ MAIN ============

def check_api_key(name, key):
    """Check API key status"""
    if key:
        return f"✅ ({len(key)} chars)"
    return "❌ NOT SET"


if __name__ == "__main__":
    keep_alive()
    
    print("=" * 50)
    print("🚀 Excel AI Bot Starting...")
    print("=" * 50)
    print(f"📦 Prefix: {PREFIX}")
    print(f"👑 Owners: {OWNER_IDS}")
    print()
    print("🔑 API Keys Status:")
    print(f"   Claude:     {check_api_key('ANTHROPIC', KEY_ANTHROPIC)}")
    print(f"   Groq:       {check_api_key('GROQ', KEY_GROQ)}")
    print(f"   Cerebras:   {check_api_key('CEREBRAS', KEY_CEREBRAS)}")
    print(f"   OpenRouter: {check_api_key('OR', KEY_OPENROUTER)}")
    print(f"   SambaNova:  {check_api_key('SN', KEY_SAMBANOVA)}")
    print(f"   Cohere:     {check_api_key('COHERE', KEY_COHERE)}")
    print("=" * 50)
    
    try:
        bot.run(DISCORD_TOKEN, log_handler=None)
    except Exception as e:
        print(f"❌ Failed to start: {e}")
