import discord,os,io,re,time,random,logging,sqlite3,base64,traceback
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import List
from urllib.parse import quote
from discord import app_commands
from discord.ext import commands
from curl_cffi import requests as curl_requests
from groq import Groq
from openai import OpenAI
import google.generativeai as genai
import requests,aiohttp
from keep_alive import keep_alive

# ==============================================================================
# 📋 LOGGING
# ==============================================================================
logging.basicConfig(level=logging.INFO,format='%(asctime)s|%(levelname)s|%(message)s')
logger=logging.getLogger(__name__)

# ==============================================================================
# 🔑 CONFIG & API KEYS
# ==============================================================================
DISCORD_TOKEN=os.getenv("DISCORD_TOKEN")
KEY_GROQ=os.getenv("GROQ_API_KEY")
KEY_GEMINI=os.getenv("GEMINI_API_KEY")
KEY_OPENAI=os.getenv("OPENAI_API_KEY")
SCRAPER_KEY=os.getenv("SCRAPER_API_KEY")
KEY_LUAOBF=os.getenv("LUAOBF_API_KEY")
ERROR_WEBHOOK=os.getenv("ERROR_WEBHOOK_URL")
OWNER_IDS=[int(x)for x in os.getenv("OWNER_IDS","0").split(",")if x.isdigit()]

if not DISCORD_TOKEN:
    logger.critical("❌ DISCORD_TOKEN not found!")
    exit(1)

# ==============================================================================
# 🤖 BOT SETUP
# ==============================================================================
intents=discord.Intents.default()
intents.message_content=True
bot=commands.Bot(command_prefix="!",intents=intents)

# ==============================================================================
# 💾 DATABASE
# ==============================================================================
class Database:
    def __init__(self,path="bot_data.db"):
        self.conn=sqlite3.connect(path,check_same_thread=False)
        self._setup()
    def _setup(self):
        c=self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS chat_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,guild_id INTEGER,
            command TEXT,prompt TEXT,response TEXT,ai_model TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS blacklist(
            user_id INTEGER PRIMARY KEY,reason TEXT,banned_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS usage_stats(
            id INTEGER PRIMARY KEY AUTOINCREMENT,command TEXT,user_id INTEGER,
            guild_id INTEGER,success INTEGER,exec_time REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        self.conn.commit()
    def log_chat(self,uid,gid,cmd,prompt,resp,model):
        self.conn.execute('INSERT INTO chat_history(user_id,guild_id,command,prompt,response,ai_model)VALUES(?,?,?,?,?,?)',
            (uid,gid,cmd,prompt,resp[:5000],model))
        self.conn.commit()
    def get_history(self,uid,limit=5):
        return self.conn.execute('SELECT prompt,response,created_at FROM chat_history WHERE user_id=? ORDER BY created_at DESC LIMIT ?',
            (uid,limit)).fetchall()
    def is_blacklisted(self,uid):
        return self.conn.execute('SELECT 1 FROM blacklist WHERE user_id=?',(uid,)).fetchone()is not None
    def add_blacklist(self,uid,reason,by):
        self.conn.execute('INSERT OR REPLACE INTO blacklist(user_id,reason,banned_by)VALUES(?,?,?)',(uid,reason,by))
        self.conn.commit()
    def remove_blacklist(self,uid):
        self.conn.execute('DELETE FROM blacklist WHERE user_id=?',(uid,))
        self.conn.commit()
    def log_usage(self,cmd,uid,gid,success,t):
        self.conn.execute('INSERT INTO usage_stats(command,user_id,guild_id,success,exec_time)VALUES(?,?,?,?,?)',
            (cmd,uid,gid,int(success),t))
        self.conn.commit()
    def get_stats(self):
        c=self.conn.cursor()
        total=c.execute('SELECT COUNT(*)FROM usage_stats').fetchone()[0]
        cmds=c.execute('SELECT command,COUNT(*),AVG(exec_time)FROM usage_stats GROUP BY command ORDER BY COUNT(*)DESC').fetchall()
        users=c.execute('SELECT user_id,COUNT(*)FROM usage_stats GROUP BY user_id ORDER BY COUNT(*)DESC LIMIT 5').fetchall()
        return{"total":total,"commands":cmds,"top_users":users}

db=Database()

# ==============================================================================
# ⏱️ RATE LIMITER
# ==============================================================================
class RateLimiter:
    def __init__(self):
        self.cd=defaultdict(lambda:defaultdict(float))
    def check(self,uid,cmd,t=5.0):
        now=time.time()
        last=self.cd[uid][cmd]
        if now-last<t:
            return False,t-(now-last)
        self.cd[uid][cmd]=now
        return True,0

rl=RateLimiter()

def rate_limit(s=5.0):
    async def pred(i:discord.Interaction)->bool:
        ok,rem=rl.check(i.user.id,i.command.name,s)
        if not ok:
            await i.response.send_message(f"⏳ Tunggu **{rem:.1f}s**",ephemeral=True)
            return False
        return True
    return app_commands.check(pred)

def is_owner():
    async def pred(i:discord.Interaction)->bool:
        if i.user.id not in OWNER_IDS:
            await i.response.send_message("❌ Owner only!",ephemeral=True)
            return False
        return True
    return app_commands.check(pred)

def not_blacklisted():
    async def pred(i:discord.Interaction)->bool:
        if db.is_blacklisted(i.user.id):
            await i.response.send_message("🚫 Kamu di-blacklist!",ephemeral=True)
            return False
        return True
    return app_commands.check(pred)

# ==============================================================================
# 🧠 CONTEXT MEMORY
# ==============================================================================
@dataclass
class Msg:
    role:str
    content:str
    ts:float

class Memory:
    def __init__(self,mx=10,exp=30):
        self.cv=defaultdict(list)
        self.mx=mx
        self.exp=exp*60
    def add(self,uid,role,content):
        self._cl(uid)
        self.cv[uid].append(Msg(role,content,time.time()))
        if len(self.cv[uid])>self.mx:
            self.cv[uid]=self.cv[uid][-self.mx:]
    def get(self,uid):
        self._cl(uid)
        return[{"role":m.role,"content":m.content}for m in self.cv[uid]]
    def clear(self,uid):
        self.cv[uid]=[]
    def _cl(self,uid):
        now=time.time()
        self.cv[uid]=[m for m in self.cv[uid]if now-m.ts<self.exp]

mem=Memory()

# ==============================================================================
# 🧠 AI MODELS 2025
# ==============================================================================
GROQ_M=["llama-3.3-70b-versatile","llama-3.1-8b-instant","mixtral-8x7b-32768"]
OPENAI_M=["gpt-4o","gpt-4o-mini","gpt-4-turbo"]
GEMINI_M=["gemini-2.0-flash","gemini-1.5-pro","gemini-1.5-flash"]

def ask_ai(prompt:str,system:str="Kamu adalah ahli coding.",uid:int=None,use_ctx:bool=False)->tuple[str,str]:
    """Multi-AI: Groq -> OpenAI -> Gemini -> Pollinations"""
    msgs=[{"role":"system","content":system}]
    if use_ctx and uid:
        msgs.extend(mem.get(uid))
    msgs.append({"role":"user","content":prompt})
    
    # 1️⃣ GROQ
    if KEY_GROQ:
        for m in GROQ_M[:2]:
            try:
                r=Groq(api_key=KEY_GROQ).chat.completions.create(
                    messages=msgs,model=m,temperature=0.7,max_tokens=4096)
                resp=r.choices[0].message.content
                if uid:mem.add(uid,"user",prompt);mem.add(uid,"assistant",resp)
                return f"⚡**[Groq-{m}]**\n{resp}",m
            except Exception as e:
                logger.warning(f"Groq {m}:{e}")
    
    # 2️⃣ OPENAI
    if KEY_OPENAI:
        for m in OPENAI_M[:2]:
            try:
                r=OpenAI(api_key=KEY_OPENAI).chat.completions.create(
                    model=m,messages=msgs,temperature=0.7,max_tokens=4096)
                resp=r.choices[0].message.content
                if uid:mem.add(uid,"user",prompt);mem.add(uid,"assistant",resp)
                return f"🤖**[OpenAI-{m}]**\n{resp}",m
            except Exception as e:
                logger.warning(f"OpenAI {m}:{e}")
    
    # 3️⃣ GEMINI
    if KEY_GEMINI:
        for m in GEMINI_M:
            try:
                genai.configure(api_key=KEY_GEMINI)
                sf=[{"category":c,"threshold":"BLOCK_NONE"}for c in[
                    "HARM_CATEGORY_HARASSMENT","HARM_CATEGORY_HATE_SPEECH",
                    "HARM_CATEGORY_SEXUALLY_EXPLICIT","HARM_CATEGORY_DANGEROUS_CONTENT"]]
                mdl=genai.GenerativeModel(m,safety_settings=sf,system_instruction=system)
                r=mdl.generate_content(prompt)
                if uid:mem.add(uid,"user",prompt);mem.add(uid,"assistant",r.text)
                return f"🧠**[Gemini-{m}]**\n{r.text}",m
            except Exception as e:
                logger.warning(f"Gemini {m}:{e}")
    
    # 4️⃣ POLLINATIONS
    try:
        for pm in["openai","mistral","claude"]:
            r=requests.get(f"https://text.pollinations.ai/{quote(system+' '+prompt)}?model={pm}",timeout=45)
            if r.status_code==200 and len(r.text)>10:
                if uid:mem.add(uid,"user",prompt);mem.add(uid,"assistant",r.text)
                return f"🌺**[Poll-{pm}]**\n{r.text}",pm
    except:
        pass
    
    return "❌ Semua AI down.","none"

def split_msg(t,lim=1900):
    if len(t)<=lim:return[t]
    ch=[];cur=""
    for l in t.split('\n'):
        if len(cur)+len(l)+1>lim:
            if cur:ch.append(cur)
            cur=l
        else:
            cur+=('\n'if cur else'')+l
    if cur:ch.append(cur)
    return ch if ch else[t[:lim]]

# ==============================================================================
# 🔓 DEOBFUSCATOR
# ==============================================================================
class Deobf:
    @staticmethod
    def decode(c):
        c=re.sub(r'\\(\d{1,3})',lambda m:chr(int(m.group(1)))if int(m.group(1))<256 else m.group(0),c)
        return re.sub(r'\\x([0-9a-fA-F]{2})',lambda m:chr(int(m.group(1),16)),c)
    @staticmethod
    def detect(c):
        p={"Luraph":[r'Luraph'],"IronBrew2":[r'IB2'],"Moonsec":[r'MoonSec'],
           "PSU":[r'PSU'],"Luarmor":[r'Luarmor'],"Synapse":[r'SynapseXen'],
           "Prometheus":[r'Prometheus'],"Aztupbrew":[r'aztupbrew']}
        f=[n for n,ps in p.items()for pt in ps if re.search(pt,c,re.I)]
        if not f:
            if c.count('(')>1000:f=["Heavy Obfuscation"]
            elif c.count('\\')>500:f=["Escape Obfuscation"]
        return",".join(f)if f else"Clean/Unknown"
    @staticmethod
    def strings(c):
        s=re.findall(r"'([^']*)'",c)+re.findall(r'"([^"]*)"',c)
        return[x for x in s if 10<len(x)<500][:50]

deobf=Deobf()

# ==============================================================================
# 🔒 LUA OBFUSCATOR API
# ==============================================================================
class LuaObf:
    URL="https://luaobfuscator.com/api/obfuscator"
    def __init__(self,key):
        self.h={"apikey":key,"Content-Type":"application/json"}
    def obf(self,script,preset="medium"):
        presets={
            "light":{"MinifySigns":True,"Minify":True},
            "medium":{"MinifySigns":True,"Minify":True,"EncryptStrings":True},
            "heavy":{"MinifySigns":True,"Minify":True,"MinifyAll":True,
                     "EncryptStrings":True,"ControlFlowFlattenV2AllBlocks":True},
            "max":{"MinifySigns":True,"Minify":True,"MinifyAll":True,
                   "EncryptStrings":True,"ControlFlowFlattenV2AllBlocks":True,"MaxSecurityV2":True}
        }
        try:
            r1=requests.post(f"{self.URL}/newscript",headers=self.h,
                            json={"script":script},timeout=30).json()
            if not r1.get("sessionId"):
                return None,r1.get("message","Upload failed")
            r2=requests.post(f"{self.URL}/obfuscate",headers=self.h,
                            json={"sessionId":r1["sessionId"],
                                  "options":presets.get(preset,presets["medium"])},timeout=60).json()
            if not r2.get("code"):
                return None,r2.get("message","Obfuscate failed")
            return r2["code"],None
        except Exception as e:
            return None,str(e)

lua_obf=LuaObf(KEY_LUAOBF)if KEY_LUAOBF else None

# ==============================================================================
# 🛡️ UTILITIES
# ==============================================================================
def get_headers():
    return{
        "User-Agent":random.choice(["Roblox/WinInet","RobloxStudio/WinInet"]),
        "Roblox-Place-Id":random.choice(["2753915549","155615604","4442272183"]),
        "Accept-Encoding":"gzip,deflate,br",
        "Connection":"keep-alive"
    }

def valid_url(u):
    blocked=["localhost","127.0.0.1","0.0.0.0","192.168.","10.0."]
    return not any(b in u.lower()for b in blocked)and u.startswith(("http://","https://"))

async def report_err(e,ctx=""):
    if not ERROR_WEBHOOK:return
    try:
        async with aiohttp.ClientSession()as s:
            embed={"title":"🚨 Error","color":0xFF0000,"fields":[
                {"name":"Type","value":f"`{type(e).__name__}`","inline":True},
                {"name":"Context","value":ctx or"Unknown","inline":True},
                {"name":"Message","value":f"```{str(e)[:500]}```","inline":False}
            ],"timestamp":datetime.utcnow().isoformat()}
            await s.post(ERROR_WEBHOOK,json={"embeds":[embed]})
    except:
        pass

async def vision_ai(url,prompt="Jelaskan gambar ini"):
    if not KEY_GEMINI:return"❌ Gemini API tidak tersedia"
    try:
        async with aiohttp.ClientSession()as s:
            async with s.get(url)as r:
                img=await r.read()
        genai.configure(api_key=KEY_GEMINI)
        m=genai.GenerativeModel('gemini-2.0-flash')
        r=m.generate_content([prompt,{"mime_type":"image/png","data":base64.b64encode(img).decode()}])
        return r.text
    except Exception as e:
        return f"❌ Vision Error: {e}"

# ==============================================================================
# 📡 BOT EVENTS
# ==============================================================================
@bot.event
async def on_ready():
    logger.info(f'🔥 {bot.user} | {len(bot.guilds)} servers')
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching,name="/help untuk bantuan"))
    try:
        s=await bot.tree.sync()
        logger.info(f"✅ {len(s)} commands synced")
    except Exception as e:
        logger.error(f"Sync error:{e}")

@bot.tree.error
async def on_err(i:discord.Interaction,e:app_commands.AppCommandError):
    await report_err(e,f"/{i.command.name if i.command else'?'}")
    msg="⏳ Cooldown!"if isinstance(e,app_commands.CommandOnCooldown)else f"❌ Error:`{str(e)[:100]}`"
    try:
        await i.response.send_message(msg,ephemeral=True)
    except:
        pass

# ==============================================================================
# 🎮 SLASH COMMANDS
# ==============================================================================

# ── PING ──
@bot.tree.command(name="ping",description="🏓 Cek latency bot")
async def ping(i:discord.Interaction):
    lat=round(bot.latency*1000)
    st="🟢 Excellent"if lat<100 else"🟡 Good"if lat<200 else"🔴 High"
    e=discord.Embed(title="🏓 Pong!",color=0x00FF00)
    e.add_field(name="Latency",value=f"`{lat}ms`",inline=True)
    e.add_field(name="Status",value=st,inline=True)
    e.add_field(name="Servers",value=f"`{len(bot.guilds)}`",inline=True)
    await i.response.send_message(embed=e)

# ── HELP ──
@bot.tree.command(name="help",description="📚 Lihat semua commands")
async def help_cmd(i:discord.Interaction):
    e=discord.Embed(title="📚 Bot Commands",description="AI Multi-Purpose Bot untuk Roblox Development",color=0xFFD700)
    cmds=[
        ("🔓 /dump `<url>` `[raw]`","Dump script dari URL"),
        ("🤖 /tanya `<q>` `[mode]`","Tanya AI tentang coding"),
        ("🔍 /explain `<url>` `[detail]`","Analisa script dari URL"),
        ("🔓 /deobf `<url>`","Deobfuscate script"),
        ("🔒 /obfuscate `<url>` `[preset]`","Obfuscate script dari URL"),
        ("🔒 /obf `<file>` `[preset]`","Obfuscate file upload"),
        ("🖼️ /vision `<url>`","Analisa gambar dengan AI"),
        ("🔍 /analyze `<file>`","Analisa gambar upload"),
        ("🧹 /clear","Hapus memory percakapan"),
        ("📜 /history","Lihat history chat"),
        ("🏓 /ping","Cek latency"),
    ]
    for n,d in cmds:
        e.add_field(name=n,value=d,inline=False)
    e.add_field(name="🧠 AI Models 2025",
                value="• Groq Llama 3.3 70B\n• OpenAI GPT-4o\n• Google Gemini 2.0\n• Pollinations (backup)",
                inline=False)
    e.set_footer(text="🔧 Owner commands: /stats /blacklist /reload")
    await i.response.send_message(embed=e)

# ── DUMP ──
@bot.tree.command(name="dump",description="🔓 Dump script dari URL")
@app_commands.describe(url="URL script",raw="Mode raw tanpa proxy")
@rate_limit(10)
@not_blacklisted()
async def dump(i:discord.Interaction,url:str,raw:bool=False):
    await i.response.defer()
    t0=time.time()
    if not valid_url(url):
        return await i.followup.send("❌ URL tidak valid!")
    try:
        if raw or not SCRAPER_KEY:
            r=curl_requests.get(url,impersonate="chrome120",headers=get_headers(),timeout=30)
            content,method=r.text,"Raw (curl_cffi)"
        else:
            r=requests.get('http://api.scraperapi.com',
                          params={'api_key':SCRAPER_KEY,'url':url,'keep_headers':'true'},
                          headers=get_headers(),timeout=90)
            content,method=r.text,"ScraperAPI"
        
        ext="lua";st="✅"
        if"<!DOCTYPE"in content[:500]or"<html"in content[:100]:
            ext="html";st="⚠️"
        elif content.strip().startswith(("{","[")):
            ext="json"
        
        e=discord.Embed(title=f"{st} Dump Result",color=0x00FF00 if ext=="lua"else 0xFFFF00)
        e.add_field(name="📎 URL",value=f"`{url[:50]}{'...'if len(url)>50 else''}`",inline=False)
        e.add_field(name="📦 Size",value=f"`{len(content):,}` bytes",inline=True)
        e.add_field(name="📄 Type",value=f"`.{ext}`",inline=True)
        e.add_field(name="🔧 Method",value=method,inline=True)
        e.set_footer(text=f"By {i.user}")
        
        db.log_usage("dump",i.user.id,i.guild_id,True,time.time()-t0)
        await i.followup.send(embed=e,file=discord.File(io.BytesIO(content.encode()),f"dump_{random.randint(1000,9999)}.{ext}"))
    except Exception as ex:
        db.log_usage("dump",i.user.id,i.guild_id,False,time.time()-t0)
        await i.followup.send(f"💀 Error: `{str(ex)[:200]}`")

# ── TANYA ──
@bot.tree.command(name="tanya",description="🤖 Tanya AI tentang coding")
@app_commands.describe(pertanyaan="Pertanyaanmu",mode="Jenis pertanyaan",context="Gunakan memory")
@app_commands.choices(mode=[
    app_commands.Choice(name="🎮 Roblox/Lua",value="roblox"),
    app_commands.Choice(name="🐍 Python",value="python"),
    app_commands.Choice(name="🌐 Web Dev",value="web"),
    app_commands.Choice(name="💬 General",value="general")])
@rate_limit(8)
@not_blacklisted()
async def tanya(i:discord.Interaction,pertanyaan:str,mode:str="general",context:bool=True):
    await i.response.defer()
    t0=time.time()
    sp={
        "roblox":"Kamu adalah ahli Roblox Studio dan Lua scripting. Jawab dalam Bahasa Indonesia dengan contoh kode yang jelas.",
        "python":"Kamu adalah ahli Python programming. Jawab dalam Bahasa Indonesia dengan best practices.",
        "web":"Kamu adalah ahli Web Development (HTML, CSS, JS, React). Jawab dalam Bahasa Indonesia.",
        "general":"Kamu adalah asisten AI yang helpful. Jawab dalam Bahasa Indonesia dengan jelas."
    }
    ic={"roblox":"🎮","python":"🐍","web":"🌐","general":"💬"}
    
    ans,mdl=ask_ai(pertanyaan,sp.get(mode,""),i.user.id,context)
    ch=split_msg(ans)
    
    e=discord.Embed(title=f"{ic.get(mode,'🤖')} Pertanyaan",description=pertanyaan[:500],color=0x5865F2)
    e.set_footer(text=f"By {i.user} | Mode: {mode}")
    
    db.log_chat(i.user.id,i.guild_id,"tanya",pertanyaan,ans,mdl)
    db.log_usage("tanya",i.user.id,i.guild_id,True,time.time()-t0)
    
    await i.followup.send(embed=e,content=ch[0])
    for c in ch[1:]:
        await i.channel.send(c)

# ── EXPLAIN ──
@bot.tree.command(name="explain",description="🔍 Analisa script dari URL")
@app_commands.describe(url="URL script",detail="Level detail")
@app_commands.choices(detail=[
    app_commands.Choice(name="📝 Ringkas",value="short"),
    app_commands.Choice(name="📋 Detail",value="detail"),
    app_commands.Choice(name="🛡️ Security Audit",value="security")])
@rate_limit(15)
@not_blacklisted()
async def explain(i:discord.Interaction,url:str,detail:str="short"):
    await i.response.defer()
    if not valid_url(url):
        return await i.followup.send("❌ URL tidak valid!")
    try:
        r=curl_requests.get(url,impersonate="chrome120",timeout=15)
        lm={"short":4000,"detail":8000,"security":6000}
        pm={
            "short":"Jelaskan script ini secara SINGKAT dalam Bahasa Indonesia. Max 3 paragraf.",
            "detail":"Analisa script ini secara DETAIL. Jelaskan setiap fungsi utama dan alur kerjanya.",
            "security":"Kamu Security Analyst. Audit script ini: 1)Backdoor/Malware 2)Data stealing 3)Remote execution. Rating keamanan 1-10."
        }
        ans,_=ask_ai(f"{pm[detail]}\n```lua\n{r.text[:lm.get(detail,4000)]}\n```","Script Analyst profesional.")
        ch=split_msg(ans)
        
        ic={"short":"📝","detail":"📋","security":"🛡️"}
        e=discord.Embed(title=f"{ic.get(detail,'🔍')} Script Analysis",color=0x9B59B6)
        e.add_field(name="🔗 URL",value=f"`{url[:50]}...`"if len(url)>50 else f"`{url}`",inline=False)
        e.add_field(name="📊 Size",value=f"`{len(r.text):,}` chars",inline=True)
        e.add_field(name="🔬 Mode",value=detail.title(),inline=True)
        
        await i.followup.send(embed=e,content=ch[0])
        for c in ch[1:]:
            await i.channel.send(c)
    except Exception as ex:
        await i.followup.send(f"❌ Error: `{str(ex)[:200]}`")

# ── DEOBF ──
@bot.tree.command(name="deobf",description="🔓 Deobfuscate script")
@app_commands.describe(url="URL script obfuscated")
@rate_limit(15)
@not_blacklisted()
async def deobfuscate(i:discord.Interaction,url:str):
    await i.response.defer()
    if not valid_url(url):
        return await i.followup.send("❌ URL tidak valid!")
    try:
        r=curl_requests.get(url,impersonate="chrome120",timeout=15)
        c=r.text
        ot=deobf.detect(c)
        dc=deobf.decode(c[:15000])
        st=deobf.strings(dc)
        
        e=discord.Embed(title="🔓 Deobfuscator Result",color=0xE67E22)
        e.add_field(name="📦 Size",value=f"`{len(c):,}` chars",inline=True)
        e.add_field(name="🔍 Obfuscator",value=ot,inline=True)
        e.add_field(name="📝 Strings Found",value=f"`{len(st)}`",inline=True)
        
        if st:
            stxt="\n".join([f"• `{s[:40]}...`"if len(s)>40 else f"• `{s}`"for s in st[:8]])
            e.add_field(name="🔑 Extracted Strings",value=stxt[:900],inline=False)
        
        await i.followup.send(embed=e,file=discord.File(io.BytesIO(dc.encode()),"decoded.lua"))
        
        # AI Analysis
        ans,_=ask_ai(f"Script obfuscated ({ot}). Strings:{st[:5]}. Preview:{dc[:1500]}. Analisa fungsi & keamanan.",
                     "Reverse engineer Lua profesional.")
        await i.channel.send(f"🧠 **AI Analysis:**\n{ans[:1900]}")
    except Exception as ex:
        await i.followup.send(f"❌ Error: `{str(ex)[:200]}`")

# ── OBFUSCATE URL ──
@bot.tree.command(name="obfuscate",description="🔒 Obfuscate Lua script dari URL")
@app_commands.describe(url="URL script",preset="Level obfuscation")
@app_commands.choices(preset=[
    app_commands.Choice(name="🟢 Light - Minify only",value="light"),
    app_commands.Choice(name="🟡 Medium - Encrypt strings",value="medium"),
    app_commands.Choice(name="🟠 Heavy - Control flow",value="heavy"),
    app_commands.Choice(name="🔴 Max - Maximum security",value="max")])
@rate_limit(20)
@not_blacklisted()
async def obfuscate_cmd(i:discord.Interaction,url:str,preset:str="medium"):
    if not lua_obf:
        return await i.response.send_message("❌ Obfuscator API belum dikonfigurasi!",ephemeral=True)
    await i.response.defer()
    try:
        r=curl_requests.get(url,impersonate="chrome120",timeout=15)
        script=r.text
        if len(script)>500000:
            return await i.followup.send("❌ Script terlalu besar! Max 500KB")
        
        result,err=lua_obf.obf(script,preset)
        if err:
            return await i.followup.send(f"❌ Error: `{err}`")
        
        ic={"light":"🟢","medium":"🟡","heavy":"🟠","max":"🔴"}
        e=discord.Embed(title=f"{ic.get(preset,'🔒')} Obfuscated!",color=0x00FF00)
        e.add_field(name="📥 Original",value=f"`{len(script):,}` chars",inline=True)
        e.add_field(name="📤 Result",value=f"`{len(result):,}` chars",inline=True)
        e.add_field(name="🔒 Preset",value=preset.title(),inline=True)
        e.set_footer(text="Powered by luaobfuscator.com")
        
        await i.followup.send(embed=e,file=discord.File(io.BytesIO(result.encode()),f"obf_{preset}.lua"))
    except Exception as ex:
        await i.followup.send(f"💀 Error: `{str(ex)[:200]}`")

# ── OBFUSCATE FILE ──
@bot.tree.command(name="obf",description="🔒 Obfuscate Lua dari file upload")
@app_commands.describe(file="Upload file .lua",preset="Level obfuscation")
@app_commands.choices(preset=[
    app_commands.Choice(name="🟢 Light",value="light"),
    app_commands.Choice(name="🟡 Medium",value="medium"),
    app_commands.Choice(name="🟠 Heavy",value="heavy"),
    app_commands.Choice(name="🔴 Max",value="max")])
@rate_limit(20)
@not_blacklisted()
async def obf_file(i:discord.Interaction,file:discord.Attachment,preset:str="medium"):
    if not lua_obf:
        return await i.response.send_message("❌ API belum dikonfigurasi!",ephemeral=True)
    if not file.filename.endswith(('.lua','.txt')):
        return await i.response.send_message("❌ File harus .lua atau .txt!",ephemeral=True)
    if file.size>500000:
        return await i.response.send_message("❌ Max 500KB!",ephemeral=True)
    await i.response.defer()
    try:
        script=(await file.read()).decode('utf-8')
        result,err=lua_obf.obf(script,preset)
        if err:
            return await i.followup.send(f"❌ Error: `{err}`")
        
        ic={"light":"🟢","medium":"🟡","heavy":"🟠","max":"🔴"}
        e=discord.Embed(title=f"{ic.get(preset,'🔒')} Obfuscated!",color=0x00FF00)
        e.add_field(name="📁 File",value=f"`{file.filename}`",inline=True)
        e.add_field(name="📥 Original",value=f"`{len(script):,}`",inline=True)
        e.add_field(name="📤 Result",value=f"`{len(result):,}`",inline=True)
        e.set_footer(text="Powered by luaobfuscator.com")
        
        await i.followup.send(embed=e,file=discord.File(io.BytesIO(result.encode()),f"obf_{file.filename}"))
    except Exception as ex:
        await i.followup.send(f"💀 Error: `{str(ex)[:200]}`")

# ── VISION ──
@bot.tree.command(name="vision",description="🖼️ Analisa gambar dengan AI")
@app_commands.describe(url="URL gambar",prompt="Pertanyaan tentang gambar")
@rate_limit(10)
@not_blacklisted()
async def vision(i:discord.Interaction,url:str,prompt:str="Jelaskan gambar ini secara detail dalam Bahasa Indonesia"):
    await i.response.defer()
    result=await vision_ai(url,prompt)
    ch=split_msg(result)
    e=discord.Embed(title="🖼️ Vision AI Analysis",color=0x9B59B6)
    e.set_thumbnail(url=url)
    e.add_field(name="❓ Prompt",value=prompt[:200],inline=False)
    await i.followup.send(embed=e,content=ch[0])
    for c in ch[1:]:
        await i.channel.send(c)

# ── ANALYZE FILE ──
@bot.tree.command(name="analyze",description="🔍 Analisa gambar yang di-upload")
@app_commands.describe(gambar="Upload gambar")
@rate_limit(10)
@not_blacklisted()
async def analyze(i:discord.Interaction,gambar:discord.Attachment):
    await i.response.defer()
    if not gambar.content_type or not gambar.content_type.startswith('image/'):
        return await i.followup.send("❌ File harus gambar!")
    result=await vision_ai(gambar.url,"Analisis gambar ini. Jika ada script/code, jelaskan fungsinya.")
    await i.followup.send(f"🖼️ **Hasil Analisis:**\n{result[:1900]}")

# ── CLEAR MEMORY ──
@bot.tree.command(name="clear",description="🧹 Hapus memory percakapan AI")
async def clear_mem(i:discord.Interaction):
    mem.clear(i.user.id)
    await i.response.send_message("🧹 Memory percakapan berhasil dihapus!",ephemeral=True)

# ── HISTORY ──
@bot.tree.command(name="history",description="📜 Lihat history chat")
@app_commands.describe(limit="Jumlah history (max 10)")
async def history(i:discord.Interaction,limit:int=5):
    h=db.get_history(i.user.id,min(limit,10))
    if not h:
        return await i.response.send_message("📭 Tidak ada history.",ephemeral=True)
    e=discord.Embed(title="📜 Chat History",color=0x3498DB)
    for idx,(p,r,t)in enumerate(h,1):
        e.add_field(name=f"{idx}. {p[:50]}...",value=f"```{r[:100]}...```",inline=False)
    await i.response.send_message(embed=e,ephemeral=True)

# ==============================================================================
# 👑 OWNER COMMANDS
# ==============================================================================

@bot.tree.command(name="stats",description="📊 Statistik bot (Owner)")
@is_owner()
async def stats(i:discord.Interaction):
    s=db.get_stats()
    e=discord.Embed(title="📊 Bot Statistics",color=0x3498DB)
    e.add_field(name="📈 Total Commands",value=f"`{s['total']:,}`",inline=True)
    e.add_field(name="🌐 Servers",value=f"`{len(bot.guilds)}`",inline=True)
    e.add_field(name="👥 Users",value=f"`{sum(g.member_count or 0 for g in bot.guilds):,}`",inline=True)
    if s['commands']:
        txt="\n".join([f"• `{c[0]}`: {c[1]}x ({c[2]:.2f}s)"for c in s['commands'][:5]])
        e.add_field(name="🔝 Top Commands",value=txt,inline=False)
    if s['top_users']:
        utxt="\n".join([f"• <@{u[0]}>: {u[1]}x"for u in s['top_users'][:3]])
        e.add_field(name="👑 Top Users",value=utxt,inline=False)
    await i.response.send_message(embed=e)

@bot.tree.command(name="blacklist",description="🚫 Blacklist user (Owner)")
@is_owner()
@app_commands.describe(user="User target",reason="Alasan")
async def bl(i:discord.Interaction,user:discord.User,reason:str="No reason"):
    db.add_blacklist(user.id,reason,i.user.id)
    await i.response.send_message(f"🚫 **{user}** telah di-blacklist.\nAlasan: {reason}")

@bot.tree.command(name="unblacklist",description="✅ Unblacklist user (Owner)")
@is_owner()
@app_commands.describe(user="User target")
async def ubl(i:discord.Interaction,user:discord.User):
    db.remove_blacklist(user.id)
    await i.response.send_message(f"✅ **{user}** telah di-unblacklist.")

@bot.tree.command(name="reload",description="🔄 Sync commands (Owner)")
@is_owner()
async def reload_cmd(i:discord.Interaction):
    await i.response.defer()
    try:
        s=await bot.tree.sync()
        await i.followup.send(f"✅ Synced {len(s)} commands!")
    except Exception as e:
        await i.followup.send(f"❌ Error: {e}")

@bot.tree.command(name="broadcast",description="📢 Broadcast pesan (Owner)")
@is_owner()
@app_commands.describe(pesan="Pesan yang akan dibroadcast")
async def broadcast(i:discord.Interaction,pesan:str):
    await i.response.defer()
    sent,failed=0,0
    for g in bot.guilds:
        ch=g.system_channel or next((c for c in g.text_channels if c.permissions_for(g.me).send_messages),None)
        if ch:
            try:
                await ch.send(f"📢 **Announcement:**\n{pesan}")
                sent+=1
            except:
                failed+=1
        else:
            failed+=1
    await i.followup.send(f"📢 Broadcast selesai!\n✅ Sent: {sent}\n❌ Failed: {failed}")

@bot.tree.command(name="servers",description="🌐 List servers (Owner)")
@is_owner()
async def servers(i:discord.Interaction):
    e=discord.Embed(title="🌐 Server List",color=0x3498DB)
    for idx,g in enumerate(bot.guilds[:25],1):
        e.add_field(name=f"{idx}. {g.name}",value=f"👥 {g.member_count} | ID: `{g.id}`",inline=False)
    e.set_footer(text=f"Total: {len(bot.guilds)} servers")
    await i.response.send_message(embed=e,ephemeral=True)

# ==============================================================================
# 🚀 START BOT
# ==============================================================================
if __name__=="__main__":
    # Start web server first
    keep_alive()
    
    # Delay untuk Render detect port
    time.sleep(3)
    
    logger.info("🚀 Starting bot...")
    logger.info(f"📦 APIs: Groq{'✅'if KEY_GROQ else'❌'} OpenAI{'✅'if KEY_OPENAI else'❌'} Gemini{'✅'if KEY_GEMINI else'❌'} Scraper{'✅'if SCRAPER_KEY else'❌'} LuaObf{'✅'if KEY_LUAOBF else'❌'}")
    
    try:
        bot.run(DISCORD_TOKEN,log_handler=None)
    except discord.LoginFailure:
        logger.critical("❌ Invalid Discord token!")
    except Exception as e:
        logger.critical(f"❌ Fatal error: {e}")
