import discord,os,io,re,time,json,logging,sqlite3,random,threading
from collections import defaultdict
from dataclasses import dataclass
from discord import app_commands
from discord.ext import commands

try:
    from keep_alive import keep_alive
except:
    keep_alive=lambda:None

logging.basicConfig(level=logging.INFO,format='%(asctime)s|%(levelname)s|%(message)s')
logger=logging.getLogger(__name__)

# ============ ENVIRONMENT VARIABLES ============
DISCORD_TOKEN=os.getenv("DISCORD_TOKEN")
KEY_GROQ=os.getenv("GROQ_API_KEY")
KEY_OPENROUTER=os.getenv("OPENROUTER_API_KEY")
KEY_CEREBRAS=os.getenv("CEREBRAS_API_KEY")
KEY_SAMBANOVA=os.getenv("SAMBANOVA_API_KEY")
KEY_COHERE=os.getenv("COHERE_API_KEY")
CF_ACCOUNT_ID=os.getenv("CLOUDFLARE_ACCOUNT_ID")
CF_API_TOKEN=os.getenv("CLOUDFLARE_API_TOKEN")
OWNER_IDS=[int(x)for x in os.getenv("OWNER_IDS","0").split(",")if x.isdigit()]
PREFIX=os.getenv("BOT_PREFIX","!")

if not DISCORD_TOKEN:
    print("❌ DISCORD_TOKEN not found!")
    exit(1)

intents=discord.Intents.default()
intents.message_content=True
bot=commands.Bot(command_prefix=PREFIX,intents=intents,help_command=None)

# ============ LAZY IMPORTS ============
_groq=_requests=_curl=None

def get_groq():
    global _groq
    if _groq is None and KEY_GROQ:
        from groq import Groq
        _groq=Groq(api_key=KEY_GROQ)
    return _groq

def get_requests():
    global _requests
    if _requests is None:
        import requests
        _requests=requests
    return _requests

def get_curl():
    global _curl
    if _curl is None:
        from curl_cffi import requests as r
        _curl=r
    return _curl

# ============ DATABASE ============
class Database:
    def __init__(self,path="bot.db"):
        self.conn=sqlite3.connect(path,check_same_thread=False)
        self.lock=threading.Lock()
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS user_prefs(uid INTEGER PRIMARY KEY,model TEXT DEFAULT "auto");
            CREATE TABLE IF NOT EXISTS stats(id INTEGER PRIMARY KEY,cmd TEXT,uid INTEGER,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS blacklist(uid INTEGER PRIMARY KEY);
        ''')
    
    def get_model(self,uid):
        with self.lock:
            r=self.conn.execute('SELECT model FROM user_prefs WHERE uid=?',(uid,)).fetchone()
            return r[0] if r else "auto"
    
    def set_model(self,uid,model):
        with self.lock:
            self.conn.execute('INSERT OR REPLACE INTO user_prefs VALUES(?,?)',(uid,model))
            self.conn.commit()
    
    def stat(self,cmd,uid):
        with self.lock:
            self.conn.execute('INSERT INTO stats(cmd,uid)VALUES(?,?)',(cmd,uid))
            self.conn.commit()
    
    def banned(self,uid):
        with self.lock:
            return self.conn.execute('SELECT 1 FROM blacklist WHERE uid=?',(uid,)).fetchone() is not None
    
    def add_blacklist(self,uid):
        with self.lock:
            self.conn.execute('INSERT OR IGNORE INTO blacklist VALUES(?)',(uid,))
            self.conn.commit()
    
    def remove_blacklist(self,uid):
        with self.lock:
            self.conn.execute('DELETE FROM blacklist WHERE uid=?',(uid,))
            self.conn.commit()

db=Database()

# ============ RATE LIMITER ============
class RateLimiter:
    def __init__(self):
        self.cd=defaultdict(lambda:defaultdict(float))
        self.lock=threading.Lock()
    
    def check(self,uid,cmd,t=5):
        with self.lock:
            now=time.time()
            if now-self.cd[uid][cmd]<t:
                return False,t-(now-self.cd[uid][cmd])
            self.cd[uid][cmd]=now
            return True,0

rl=RateLimiter()

# ============ MEMORY ============
@dataclass
class Msg:
    role:str
    content:str
    ts:float

class Memory:
    def __init__(self):
        self.data=defaultdict(list)
        self.lock=threading.Lock()
    
    def add(self,uid,role,content):
        with self.lock:
            now=time.time()
            self.data[uid]=[m for m in self.data[uid] if now-m.ts<1800]
            self.data[uid].append(Msg(role,content[:1500],now))
            if len(self.data[uid])>15:
                self.data[uid]=self.data[uid][-15:]
    
    def get(self,uid):
        with self.lock:
            now=time.time()
            self.data[uid]=[m for m in self.data[uid] if now-m.ts<1800]
            return [{"role":m.role,"content":m.content} for m in self.data[uid]]
    
    def clear(self,uid):
        with self.lock:
            self.data[uid]=[]

mem=Memory()

# ============ SYSTEM PROMPT ============
SYSTEM_PROMPT='''Kamu adalah AI Assistant yang helpful dan friendly. 
Kamu membantu user dengan berbagai pertanyaan dan tugas.
Jawab dalam Bahasa Indonesia kecuali diminta bahasa lain.
Berikan jawaban yang jelas, informatif, dan mudah dipahami.'''

# ============ MODEL CONFIGURATIONS ============
OR_MODELS={
    "llama":"meta-llama/llama-3.3-70b-instruct:free",
    "gemini":"google/gemini-2.0-flash-exp:free",
    "qwen":"qwen/qwen3-32b:free",
    "deepseek":"deepseek/deepseek-chat-v3-0324:free"
}

CF_MODELS={
    "llama":"@cf/meta/llama-3.1-8b-instruct",
    "mistral":"@cf/mistral/mistral-7b-instruct-v0.1"
}

MODEL_NAMES={
    "auto":"🚀 Auto",
    "groq":"⚡ Groq",
    "cerebras":"🧠 Cerebras",
    "cloudflare":"☁️ Cloudflare",
    "sambanova":"🦣 SambaNova",
    "cohere":"🔷 Cohere",
    "or_llama":"🦙 OR-Llama",
    "or_gemini":"🔵 OR-Gemini",
    "or_qwen":"🟣 OR-Qwen",
    "or_deepseek":"🌊 OR-DeepSeek"
}

UA_LIST=["Roblox/WinInet","Synapse-X/2.0","Sentinel/3.0","Krnl/1.0","Fluxus/1.0","ScriptWare/2.0"]

# ============ AI PROVIDERS ============

def call_groq(msgs):
    """Call Groq API"""
    cl=get_groq()
    if not cl:
        return None
    try:
        r=cl.chat.completions.create(
            messages=msgs,
            model="llama-3.3-70b-versatile",
            temperature=0.7,
            max_tokens=2000
        )
        return r.choices[0].message.content
    except Exception as e:
        logger.error(f"Groq: {e}")
        return None

def call_cerebras(msgs):
    """Call Cerebras API"""
    if not KEY_CEREBRAS:
        return None
    try:
        r=get_requests().post(
            "https://api.cerebras.ai/v1/chat/completions",
            headers={
                "Authorization":f"Bearer {KEY_CEREBRAS}",
                "Content-Type":"application/json"
            },
            json={
                "model":"llama-3.3-70b",
                "messages":msgs,
                "temperature":0.7,
                "max_tokens":2000
            },
            timeout=30
        )
        if r.status_code==200:
            return r.json()["choices"][0]["message"]["content"]
        logger.error(f"Cerebras: {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"Cerebras: {e}")
        return None

def call_cloudflare(msgs):
    """Call Cloudflare Workers AI"""
    if not CF_ACCOUNT_ID or not CF_API_TOKEN:
        return None
    try:
        model=CF_MODELS["llama"]
        url=f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{model}"
        r=get_requests().post(
            url,
            headers={
                "Authorization":f"Bearer {CF_API_TOKEN}",
                "Content-Type":"application/json"
            },
            json={"messages":msgs,"max_tokens":2000},
            timeout=60
        )
        if r.status_code==200:
            data=r.json()
            if data.get("success") and "result" in data:
                response=data["result"].get("response","")
                if response and response.strip():
                    return response.strip()
        logger.error(f"Cloudflare: {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"Cloudflare: {e}")
        return None

def call_openrouter(msgs,mk="llama"):
    """Call OpenRouter API"""
    if not KEY_OPENROUTER:
        return None
    try:
        mid=OR_MODELS.get(mk,OR_MODELS["llama"])
        r=get_requests().post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization":f"Bearer {KEY_OPENROUTER}",
                "Content-Type":"application/json",
                "HTTP-Referer":"https://github.com"
            },
            json={
                "model":mid,
                "messages":msgs,
                "temperature":0.7,
                "max_tokens":2000
            },
            timeout=60
        )
        if r.status_code==200:
            data=r.json()
            if "choices" in data and data["choices"]:
                return data["choices"][0]["message"]["content"]
        logger.error(f"OpenRouter {mk}: {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"OpenRouter: {e}")
        return None

def call_sambanova(msgs):
    """Call SambaNova API"""
    if not KEY_SAMBANOVA:
        return None
    try:
        r=get_requests().post(
            "https://api.sambanova.ai/v1/chat/completions",
            headers={
                "Authorization":f"Bearer {KEY_SAMBANOVA}",
                "Content-Type":"application/json"
            },
            json={
                "model":"Meta-Llama-3.3-70B-Instruct",
                "messages":msgs,
                "temperature":0.7,
                "max_tokens":2000
            },
            timeout=60
        )
        if r.status_code==200:
            return r.json()["choices"][0]["message"]["content"]
        logger.error(f"SambaNova: {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"SambaNova: {e}")
        return None

def call_cohere(msgs):
    """Call Cohere API"""
    if not KEY_COHERE:
        return None
    try:
        preamble=""
        hist=[]
        messages=[]
        for m in msgs:
            if m["role"]=="system":
                preamble=m["content"]
            else:
                messages.append(m)
        for m in messages[:-1]:
            role="USER" if m["role"]=="user" else "CHATBOT"
            hist.append({"role":role,"message":m["content"]})
        user_msg=messages[-1]["content"] if messages else ""
        payload={"model":"command-r-plus-08-2024","message":user_msg,"temperature":0.7}
        if preamble:
            payload["preamble"]=preamble
        if hist:
            payload["chat_history"]=hist
        r=get_requests().post(
            "https://api.cohere.com/v1/chat",
            headers={
                "Authorization":f"Bearer {KEY_COHERE}",
                "Content-Type":"application/json"
            },
            json=payload,
            timeout=60
        )
        if r.status_code==200:
            return r.json().get("text","")
        logger.error(f"Cohere: {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"Cohere: {e}")
        return None

# ============ AI ROUTER ============

def call_ai(model,msgs):
    """Route to specific AI provider"""
    if model=="groq":
        return call_groq(msgs),"Groq"
    elif model=="cerebras":
        return call_cerebras(msgs),"Cerebras"
    elif model=="cloudflare":
        return call_cloudflare(msgs),"Cloudflare"
    elif model=="sambanova":
        return call_sambanova(msgs),"SambaNova"
    elif model=="cohere":
        return call_cohere(msgs),"Cohere"
    elif model.startswith("or_"):
        mk=model[3:]
        return call_openrouter(msgs,mk),f"OR-{mk.title()}"
    return None,"none"

def ask_ai(prompt,uid=None,model=None):
    """Main AI function with fallback"""
    if not model or model=="auto":
        model=db.get_model(uid) if uid else "auto"
    
    if uid and model!="auto":
        db.set_model(uid,model)
    
    # Build messages
    msgs=[{"role":"system","content":SYSTEM_PROMPT}]
    if uid:
        h=mem.get(uid)
        if h:
            msgs.extend(h[-6:])
    msgs.append({"role":"user","content":prompt})
    
    result=None
    used="none"
    
    if model!="auto":
        result,used=call_ai(model,msgs)
        # Fallback if failed
        if not result:
            fallbacks=[
                (lambda:call_groq(msgs),"Groq"),
                (lambda:call_cerebras(msgs),"Cerebras"),
                (lambda:call_cloudflare(msgs),"Cloudflare"),
                (lambda:call_openrouter(msgs,"llama"),"OR-Llama")
            ]
            for fn,nm in fallbacks:
                try:
                    result=fn()
                    if result:
                        used=f"{nm}(fb)"
                        break
                except:
                    continue
    else:
        # Auto mode - try all
        providers=[
            (lambda:call_groq(msgs),"Groq"),
            (lambda:call_cerebras(msgs),"Cerebras"),
            (lambda:call_cloudflare(msgs),"Cloudflare"),
            (lambda:call_openrouter(msgs,"llama"),"OR-Llama"),
            (lambda:call_sambanova(msgs),"SambaNova"),
            (lambda:call_cohere(msgs),"Cohere")
        ]
        for fn,nm in providers:
            try:
                result=fn()
                if result:
                    used=nm
                    break
            except:
                continue
    
    if not result:
        return "❌ Semua AI provider tidak tersedia saat ini.","none"
    
    # Save to memory
    if uid:
        mem.add(uid,"user",prompt[:500])
        mem.add(uid,"assistant",result[:500])
    
    return result,used

# ============ HELPERS ============

def split_msg(text,limit=1900):
    """Split long messages"""
    if not text or not str(text).strip():
        return ["(kosong)"]
    text=str(text).strip()[:3800]
    if len(text)<=limit:
        return [text]
    chunks=[]
    while text:
        if len(text)<=limit:
            chunks.append(text)
            break
        idx=text.rfind('\n',0,limit)
        if idx<=0:
            idx=text.rfind(' ',0,limit)
        if idx<=0:
            idx=limit
        chunk=text[:idx].strip()
        if chunk:
            chunks.append(chunk)
        text=text[idx:].lstrip()
    return chunks if chunks else ["(kosong)"]

async def safe_send(target,content,used,is_reply=True):
    """Safe send with error handling"""
    try:
        if not content or not content.strip():
            content="(Response kosong)"
        
        chunks=split_msg(content)
        first=chunks[0] if chunks else "(kosong)"
        if not first.strip():
            first="(Response kosong)"
        
        embed=discord.Embed(color=0x5865F2)
        embed.set_footer(text=f"🤖 {used}")
        
        if is_reply:
            try:
                await target.reply(content=first,embed=embed if len(chunks)==1 else None)
            except discord.NotFound:
                await target.channel.send(content=first,embed=embed if len(chunks)==1 else None)
            for c in chunks[1:]:
                if c.strip():
                    await target.channel.send(c)
        else:
            await target.followup.send(content=first,embed=embed if len(chunks)==1 else None)
            for c in chunks[1:]:
                if c.strip():
                    await target.channel.send(c)
        return True
    except discord.NotFound:
        logger.warning("Message deleted, sending to channel")
        try:
            await target.channel.send(content=content[:1900])
        except:
            pass
        return False
    except discord.HTTPException as e:
        logger.error(f"Discord HTTP: {e}")
        return False
    except Exception as e:
        logger.error(f"Send error: {e}")
        return False

# ============ BOT EVENTS ============

@bot.event
async def on_ready():
    logger.info(f'🔥 {bot.user} online | {len(bot.guilds)} servers')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching,name=f"{PREFIX}help"))
    try:
        s=await bot.tree.sync()
        logger.info(f"✅ Synced {len(s)} commands")
    except Exception as e:
        logger.error(f"Sync error: {e}")

@bot.event
async def on_message(msg):
    if msg.author.bot:
        return
    
    # Handle mention
    if bot.user.mentioned_in(msg) and not msg.mention_everyone:
        content=msg.content.replace(f'<@{bot.user.id}>','').replace(f'<@!{bot.user.id}>','').strip()
        
        if content:
            if db.banned(msg.author.id):
                try:
                    await msg.reply("🚫 Kamu diblokir dari menggunakan bot ini.")
                except:
                    pass
                return
            
            ok,rem=rl.check(msg.author.id,"mention",5)
            if not ok:
                try:
                    await msg.reply(f"⏳ Tunggu {rem:.0f} detik")
                except:
                    pass
                return
            
            async with msg.channel.typing():
                try:
                    result,used=ask_ai(content,msg.author.id)
                    await safe_send(msg,result,used,True)
                    db.stat("ai",msg.author.id)
                except Exception as e:
                    logger.error(f"Mention AI error: {e}")
                    try:
                        await msg.reply("❌ Terjadi error saat memproses permintaan.")
                    except:
                        pass
        else:
            m=db.get_model(msg.author.id)
            mn=MODEL_NAMES.get(m,m)
            try:
                await msg.reply(f"👋 Hai! Saya AI Assistant.\n\n🤖 Model kamu: **{mn}**\n\nKetik pertanyaan setelah mention saya!")
            except:
                pass
        return
    
    await bot.process_commands(msg)

# ============ PREFIX COMMANDS ============

@bot.command(name="ai",aliases=["ask","chat","tanya"])
async def cmd_ai(ctx,*,prompt:str=None):
    """Chat with AI"""
    if db.banned(ctx.author.id):
        return
    
    ok,rem=rl.check(ctx.author.id,"ai",5)
    if not ok:
        return await ctx.reply(f"⏳ Tunggu {rem:.0f} detik")
    
    if not prompt:
        return await ctx.reply(f"❌ Gunakan: `{PREFIX}ai <pertanyaan>`\nContoh: `{PREFIX}ai apa itu Python?`")
    
    async with ctx.typing():
        try:
            result,used=ask_ai(prompt,ctx.author.id)
            await safe_send(ctx.message,result,used,True)
            db.stat("ai",ctx.author.id)
        except Exception as e:
            logger.error(f"AI cmd error: {e}")
            await ctx.reply("❌ Terjadi error saat memproses permintaan.")

@bot.command(name="model",aliases=["m","setmodel"])
async def cmd_model(ctx,model:str=None):
    """View or change AI model"""
    valid=list(MODEL_NAMES.keys())
    
    if not model:
        cur=db.get_model(ctx.author.id)
        e=discord.Embed(title="🤖 Model AI",color=0x3498DB)
        e.add_field(name="Model Kamu",value=f"**{MODEL_NAMES.get(cur,cur)}**",inline=False)
        e.add_field(name="Model Tersedia",value="\n".join([f"`{k}` - {v}" for k,v in MODEL_NAMES.items()]),inline=False)
        e.add_field(name="Cara Ganti",value=f"`{PREFIX}model <nama>`\nContoh: `{PREFIX}model groq`",inline=False)
        return await ctx.reply(embed=e)
    
    model=model.lower()
    if model not in valid:
        return await ctx.reply(f"❌ Model tidak valid!\n\nPilihan: `{', '.join(valid)}`")
    
    db.set_model(ctx.author.id,model)
    await ctx.reply(f"✅ Model diubah ke: **{MODEL_NAMES.get(model,model)}**")

@bot.command(name="clear",aliases=["reset","forget"])
async def cmd_clear(ctx):
    """Clear chat memory"""
    mem.clear(ctx.author.id)
    await ctx.reply("🧹 Memory percakapan dihapus!")

@bot.command(name="ping",aliases=["p","status"])
async def cmd_ping(ctx):
    """Check bot status"""
    m=db.get_model(ctx.author.id)
    mem_count=len(mem.get(ctx.author.id))
    
    e=discord.Embed(title="🏓 Pong!",color=0x00FF00)
    e.add_field(name="Latency",value=f"`{round(bot.latency*1000)}ms`")
    e.add_field(name="Model",value=f"`{MODEL_NAMES.get(m,m)}`")
    e.add_field(name="Memory",value=f"`{mem_count} pesan`")
    e.add_field(name="Servers",value=f"`{len(bot.guilds)}`")
    await ctx.reply(embed=e)

@bot.command(name="help",aliases=["h","bantuan"])
async def cmd_help(ctx):
    """Show help"""
    m=db.get_model(ctx.author.id)
    
    e=discord.Embed(title="📚 AI Bot - Help",description=f"Model kamu: **{MODEL_NAMES.get(m,m)}**",color=0x5865F2)
    e.add_field(
        name="🤖 AI Chat",
        value=f"`{PREFIX}ai <pertanyaan>` - Tanya AI\n`@{bot.user.name} <pertanyaan>` - Via mention",
        inline=False
    )
    e.add_field(
        name="⚙️ Pengaturan",
        value=f"`{PREFIX}model [nama]` - Lihat/ganti model AI\n`{PREFIX}clear` - Hapus memory chat\n`{PREFIX}ping` - Cek status bot",
        inline=False
    )
    e.add_field(
        name="🔧 Tools",
        value=f"`{PREFIX}dump <url>` - Download Roblox script\n`{PREFIX}testai` - Test semua AI (owner)",
        inline=False
    )
    e.set_footer(text=f"Prefix: {PREFIX} | Made with ❤️")
    await ctx.reply(embed=e)

@bot.command(name="dump",aliases=["script","download"])
async def cmd_dump(ctx,url:str=None,mode:str="auto"):
    """Download Roblox script from URL"""
    if not url:
        e=discord.Embed(title="🔓 Script Dumper",color=0xFF6B6B)
        e.add_field(name="Cara Pakai",value=f"`{PREFIX}dump <url>`",inline=False)
        e.add_field(name="Contoh",value=f"`{PREFIX}dump https://example.com/script`",inline=False)
        return await ctx.reply(embed=e)
    
    ok,rem=rl.check(ctx.author.id,"dump",8)
    if not ok:
        return await ctx.reply(f"⏳ Tunggu {rem:.0f} detik")
    
    async with ctx.typing():
        try:
            curl=get_curl()
            ua=random.choice(UA_LIST)
            
            headers={
                "User-Agent":ua,
                "Roblox-Place-Id":"2753915549",
                "Accept":"*/*",
                "Accept-Language":"en-US,en;q=0.9",
                "Accept-Encoding":"gzip, deflate, br"
            }
            
            resp=curl.get(url,impersonate="chrome110",headers=headers,timeout=20)
            content=resp.text
            
            # Limit size
            if len(content)>1024*1024:
                content=content[:1024*1024]
            
            # Detect type
            ext="lua"
            color=0x00FF00
            if "<!DOCTYPE" in content[:300] or "<html" in content[:300].lower():
                ext="html"
                color=0xFFFF00
            elif content.strip().startswith("{") or content.strip().startswith("["):
                ext="json"
                color=0x3498DB
            
            e=discord.Embed(title="🔓 Dump Result",color=color)
            e.add_field(name="📦 Size",value=f"`{len(content):,} bytes`",inline=True)
            e.add_field(name="📄 Type",value=f"`.{ext}`",inline=True)
            e.add_field(name="🌐 UA",value=f"`{ua[:15]}...`",inline=True)
            
            db.stat("dump",ctx.author.id)
            
            file=discord.File(io.BytesIO(content.encode('utf-8',errors='ignore')),filename=f"dump.{ext}")
            await ctx.reply(embed=e,file=file)
            
        except Exception as e:
            error_msg=str(e)[:100]
            await ctx.reply(f"💀 Error: `{error_msg}`")

@bot.command(name="testai",aliases=["test"])
async def cmd_testai(ctx):
    """Test all AI providers (Owner only)"""
    if ctx.author.id not in OWNER_IDS:
        return await ctx.reply("❌ Owner only!")
    
    async with ctx.typing():
        results=[]
        test_msgs=[{"role":"user","content":"Say 'OK' only"}]
        
        tests=[
            ("Groq",lambda:call_groq(test_msgs)),
            ("Cerebras",lambda:call_cerebras(test_msgs)),
            ("Cloudflare",lambda:call_cloudflare(test_msgs)),
            ("SambaNova",lambda:call_sambanova(test_msgs)),
            ("Cohere",lambda:call_cohere(test_msgs)),
            ("OR-Llama",lambda:call_openrouter(test_msgs,"llama")),
            ("OR-Gemini",lambda:call_openrouter(test_msgs,"gemini")),
        ]
        
        for name,fn in tests:
            try:
                r=fn()
                if r:
                    preview=r[:25].replace('\n',' ').strip()
                    results.append(f"✅ **{name}**: `{preview}...`")
                else:
                    results.append(f"❌ **{name}**: No response")
            except Exception as ex:
                results.append(f"❌ **{name}**: `{str(ex)[:30]}`")
        
        e=discord.Embed(title="🔧 AI Provider Test",description="\n".join(results),color=0x3498DB)
        await ctx.reply(embed=e)

@bot.command(name="blacklist",aliases=["ban","block"])
async def cmd_blacklist(ctx,action:str=None,user:discord.User=None):
    """Manage blacklist (Owner only)"""
    if ctx.author.id not in OWNER_IDS:
        return await ctx.reply("❌ Owner only!")
    
    if not action or not user:
        return await ctx.reply(f"❌ Gunakan: `{PREFIX}blacklist <add/remove> <@user>`")
    
    if action.lower() in ["add","ban"]:
        db.add_blacklist(user.id)
        await ctx.reply(f"✅ {user.mention} ditambahkan ke blacklist.")
    elif action.lower() in ["remove","unban"]:
        db.remove_blacklist(user.id)
        await ctx.reply(f"✅ {user.mention} dihapus dari blacklist.")
    else:
        await ctx.reply("❌ Action harus `add` atau `remove`")

# ============ SLASH COMMANDS ============

@bot.tree.command(name="ai",description="Chat dengan AI")
@app_commands.describe(prompt="Pertanyaan atau pesan kamu")
async def slash_ai(i:discord.Interaction,prompt:str):
    await i.response.defer()
    try:
        result,used=ask_ai(prompt,i.user.id)
        await safe_send(i,result,used,False)
        db.stat("ai",i.user.id)
    except Exception as e:
        logger.error(f"Slash AI error: {e}")
        await i.followup.send("❌ Terjadi error.")

@bot.tree.command(name="model",description="Lihat atau ganti model AI")
@app_commands.describe(model="Pilih model AI")
@app_commands.choices(model=[app_commands.Choice(name=v,value=k) for k,v in MODEL_NAMES.items()])
async def slash_model(i:discord.Interaction,model:str=None):
    if model:
        db.set_model(i.user.id,model)
        await i.response.send_message(f"✅ Model: **{MODEL_NAMES.get(model,model)}**",ephemeral=True)
    else:
        cur=db.get_model(i.user.id)
        await i.response.send_message(f"🤖 Model kamu: **{MODEL_NAMES.get(cur,cur)}**",ephemeral=True)

@bot.tree.command(name="clear",description="Hapus memory chat")
async def slash_clear(i:discord.Interaction):
    mem.clear(i.user.id)
    await i.response.send_message("🧹 Memory dihapus!",ephemeral=True)

@bot.tree.command(name="ping",description="Cek status bot")
async def slash_ping(i:discord.Interaction):
    await i.response.send_message(f"🏓 Pong! `{round(bot.latency*1000)}ms`")

@bot.tree.command(name="dump",description="Download Roblox script")
@app_commands.describe(url="URL script yang ingin di-download")
async def slash_dump(i:discord.Interaction,url:str):
    await i.response.defer()
    
    ok,rem=rl.check(i.user.id,"dump",8)
    if not ok:
        return await i.followup.send(f"⏳ Tunggu {rem:.0f} detik")
    
    try:
        curl=get_curl()
        ua=random.choice(UA_LIST)
        headers={"User-Agent":ua,"Roblox-Place-Id":"2753915549","Accept":"*/*"}
        
        resp=curl.get(url,impersonate="chrome110",headers=headers,timeout=20)
        content=resp.text[:1024*1024]
        
        ext="lua"
        if "<!DOCTYPE" in content[:300]:
            ext="html"
        elif content.strip().startswith("{"):
            ext="json"
        
        e=discord.Embed(title="🔓 Dump Result",color=0x00FF00)
        e.add_field(name="Size",value=f"`{len(content):,}b`",inline=True)
        e.add_field(name="Type",value=f"`.{ext}`",inline=True)
        
        db.stat("dump",i.user.id)
        file=discord.File(io.BytesIO(content.encode()),filename=f"dump.{ext}")
        await i.followup.send(embed=e,file=file)
        
    except Exception as e:
        await i.followup.send(f"❌ Error: `{str(e)[:100]}`")

@bot.tree.command(name="help",description="Tampilkan bantuan")
async def slash_help(i:discord.Interaction):
    m=db.get_model(i.user.id)
    e=discord.Embed(title="📚 AI Bot Help",description=f"Model: **{MODEL_NAMES.get(m,m)}**",color=0x5865F2)
    e.add_field(name="🤖 AI",value="`/ai` - Chat dengan AI\n`@mention` - Via mention",inline=False)
    e.add_field(name="⚙️ Settings",value="`/model` - Ganti model\n`/clear` - Hapus memory",inline=False)
    e.add_field(name="🔧 Tools",value="`/dump` - Download script\n`/ping` - Status bot",inline=False)
    await i.response.send_message(embed=e,ephemeral=True)

@bot.tree.command(name="reload",description="Sync commands (Owner)")
async def slash_reload(i:discord.Interaction):
    if i.user.id not in OWNER_IDS:
        return await i.response.send_message("❌ Owner only!",ephemeral=True)
    await i.response.defer()
    try:
        s=await bot.tree.sync()
        await i.followup.send(f"✅ Synced {len(s)} commands")
    except Exception as e:
        await i.followup.send(f"❌ Error: {e}")

# ============ MAIN ============

if __name__=="__main__":
    keep_alive()
    
    print("="*50)
    print("🚀 AI Bot Starting...")
    print("="*50)
    print(f"📦 Prefix: {PREFIX}")
    print(f"👑 Owners: {OWNER_IDS}")
    print()
    print("🔑 API Keys Status:")
    print(f"   Groq:       {'✅' if KEY_GROQ else '❌'}")
    print(f"   Cerebras:   {'✅' if KEY_CEREBRAS else '❌'}")
    print(f"   Cloudflare: {'✅' if CF_ACCOUNT_ID and CF_API_TOKEN else '❌'}")
    print(f"   OpenRouter: {'✅' if KEY_OPENROUTER else '❌'}")
    print(f"   SambaNova:  {'✅' if KEY_SAMBANOVA else '❌'}")
    print(f"   Cohere:     {'✅' if KEY_COHERE else '❌'}")
    print("="*50)
    
    try:
        bot.run(DISCORD_TOKEN,log_handler=None)
    except Exception as e:
        print(f"❌ Failed to start: {e}")
