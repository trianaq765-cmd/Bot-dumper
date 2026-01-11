import discord,os,io,re,time,random,logging,sqlite3,base64
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import quote
from discord import app_commands
from discord.ext import commands
from keep_alive import keep_alive

# ==============================================================================
# 📋 LOGGING (Minimal untuk speed)
# ==============================================================================
logging.basicConfig(level=logging.WARNING,format='%(asctime)s|%(levelname)s|%(message)s')
logger=logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ==============================================================================
# 🔑 CONFIG
# ==============================================================================
DISCORD_TOKEN=os.getenv("DISCORD_TOKEN")
KEY_GROQ=os.getenv("GROQ_API_KEY")
KEY_GEMINI=os.getenv("GEMINI_API_KEY")
KEY_OPENAI=os.getenv("OPENAI_API_KEY")
SCRAPER_KEY=os.getenv("SCRAPER_API_KEY")
KEY_LUAOBF=os.getenv("LUAOBF_API_KEY")
OWNER_IDS=[int(x)for x in os.getenv("OWNER_IDS","0").split(",")if x.isdigit()]

if not DISCORD_TOKEN:print("❌ NO TOKEN!");exit(1)

# ==============================================================================
# 🤖 BOT (Lazy loading untuk speed)
# ==============================================================================
intents=discord.Intents.default()
intents.message_content=True
bot=commands.Bot(command_prefix="!",intents=intents)

# ==============================================================================
# 📦 LAZY IMPORTS (Load saat dibutuhkan)
# ==============================================================================
_groq=None
_openai=None
_genai=None
_curl=None
_requests=None
_aiohttp=None

def get_groq():
    global _groq
    if _groq is None and KEY_GROQ:
        from groq import Groq
        _groq=Groq(api_key=KEY_GROQ)
    return _groq

def get_openai():
    global _openai
    if _openai is None and KEY_OPENAI:
        from openai import OpenAI
        _openai=OpenAI(api_key=KEY_OPENAI)
    return _openai

def get_genai():
    global _genai
    if _genai is None and KEY_GEMINI:
        import google.generativeai as genai
        genai.configure(api_key=KEY_GEMINI)
        _genai=genai
    return _genai

def get_curl():
    global _curl
    if _curl is None:
        from curl_cffi import requests as curl_requests
        _curl=curl_requests
    return _curl

def get_requests():
    global _requests
    if _requests is None:
        import requests
        _requests=requests
    return _requests

async def get_aiohttp():
    global _aiohttp
    if _aiohttp is None:
        import aiohttp
        _aiohttp=aiohttp
    return _aiohttp

# ==============================================================================
# 💾 DATABASE (SQLite)
# ==============================================================================
class Database:
    def __init__(self,path="bot.db"):
        self.conn=sqlite3.connect(path,check_same_thread=False)
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY,uid INTEGER,gid INTEGER,cmd TEXT,prompt TEXT,resp TEXT,model TEXT,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS blacklist(uid INTEGER PRIMARY KEY,reason TEXT,by INTEGER);
            CREATE TABLE IF NOT EXISTS stats(id INTEGER PRIMARY KEY,cmd TEXT,uid INTEGER,gid INTEGER,ok INTEGER,t REAL,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        ''')
    def log(self,uid,gid,cmd,p,r,m):self.conn.execute('INSERT INTO history(uid,gid,cmd,prompt,resp,model)VALUES(?,?,?,?,?,?)',(uid,gid,cmd,p,r[:4000],m));self.conn.commit()
    def hist(self,uid,n=5):return self.conn.execute('SELECT prompt,resp,ts FROM history WHERE uid=? ORDER BY ts DESC LIMIT ?',(uid,n)).fetchall()
    def banned(self,uid):return self.conn.execute('SELECT 1 FROM blacklist WHERE uid=?',(uid,)).fetchone()is not None
    def ban(self,uid,r,by):self.conn.execute('INSERT OR REPLACE INTO blacklist VALUES(?,?,?)',(uid,r,by));self.conn.commit()
    def unban(self,uid):self.conn.execute('DELETE FROM blacklist WHERE uid=?',(uid,));self.conn.commit()
    def stat(self,cmd,uid,gid,ok,t):self.conn.execute('INSERT INTO stats(cmd,uid,gid,ok,t)VALUES(?,?,?,?,?)',(cmd,uid,gid,int(ok),t));self.conn.commit()
    def stats(self):
        c=self.conn
        return{"total":c.execute('SELECT COUNT(*)FROM stats').fetchone()[0],
               "cmds":c.execute('SELECT cmd,COUNT(*),AVG(t)FROM stats GROUP BY cmd ORDER BY COUNT(*)DESC').fetchall()}
db=Database()

# ==============================================================================
# ⏱️ RATE LIMITER
# ==============================================================================
class RL:
    def __init__(self):self.cd=defaultdict(lambda:defaultdict(float))
    def ok(self,uid,cmd,t=5):
        now=time.time();last=self.cd[uid][cmd]
        if now-last<t:return False,t-(now-last)
        self.cd[uid][cmd]=now;return True,0
rl=RL()

def rate(s=5):
    async def p(i:discord.Interaction)->bool:
        ok,r=rl.ok(i.user.id,i.command.name,s)
        if not ok:await i.response.send_message(f"⏳ Tunggu **{r:.1f}s**",ephemeral=True);return False
        return True
    return app_commands.check(p)

def owner():
    async def p(i:discord.Interaction)->bool:
        if i.user.id not in OWNER_IDS:await i.response.send_message("❌ Owner only!",ephemeral=True);return False
        return True
    return app_commands.check(p)

def noban():
    async def p(i:discord.Interaction)->bool:
        if db.banned(i.user.id):await i.response.send_message("🚫 Blacklisted!",ephemeral=True);return False
        return True
    return app_commands.check(p)

# ==============================================================================
# 🧠 MEMORY
# ==============================================================================
@dataclass
class M:
    role:str;content:str;ts:float
class Mem:
    def __init__(self):self.c=defaultdict(list)
    def add(self,uid,role,txt):
        now=time.time()
        self.c[uid]=[m for m in self.c[uid]if now-m.ts<1800]
        self.c[uid].append(M(role,txt,now))
        if len(self.c[uid])>10:self.c[uid]=self.c[uid][-10:]
    def get(self,uid):return[{"role":m.role,"content":m.content}for m in self.c[uid]]
    def clr(self,uid):self.c[uid]=[]
mem=Mem()

# ==============================================================================
# 🧠 AI
# ==============================================================================
GROQ_M=["llama-3.3-70b-versatile","llama-3.1-8b-instant"]
OPENAI_M=["gpt-4o","gpt-4o-mini"]
GEMINI_M=["gemini-2.0-flash","gemini-1.5-flash"]

def ask(prompt,sys="Kamu ahli coding.",uid=None,ctx=False):
    msgs=[{"role":"system","content":sys}]
    if ctx and uid:msgs.extend(mem.get(uid))
    msgs.append({"role":"user","content":prompt})
    
    # GROQ
    cl=get_groq()
    if cl:
        for m in GROQ_M:
            try:
                r=cl.chat.completions.create(messages=msgs,model=m,temperature=0.7,max_tokens=4096)
                resp=r.choices[0].message.content
                if uid:mem.add(uid,"user",prompt);mem.add(uid,"assistant",resp)
                return f"⚡**[Groq]**\n{resp}",m
            except:pass
    
    # OPENAI
    cl=get_openai()
    if cl:
        for m in OPENAI_M:
            try:
                r=cl.chat.completions.create(model=m,messages=msgs,temperature=0.7,max_tokens=4096)
                resp=r.choices[0].message.content
                if uid:mem.add(uid,"user",prompt);mem.add(uid,"assistant",resp)
                return f"🤖**[OpenAI]**\n{resp}",m
            except:pass
    
    # GEMINI
    g=get_genai()
    if g:
        for m in GEMINI_M:
            try:
                sf=[{"category":c,"threshold":"BLOCK_NONE"}for c in["HARM_CATEGORY_HARASSMENT","HARM_CATEGORY_HATE_SPEECH","HARM_CATEGORY_SEXUALLY_EXPLICIT","HARM_CATEGORY_DANGEROUS_CONTENT"]]
                mdl=g.GenerativeModel(m,safety_settings=sf,system_instruction=sys)
                r=mdl.generate_content(prompt)
                if uid:mem.add(uid,"user",prompt);mem.add(uid,"assistant",r.text)
                return f"🧠**[Gemini]**\n{r.text}",m
            except:pass
    
    # POLLINATIONS
    try:
        req=get_requests()
        for pm in["openai","mistral"]:
            r=req.get(f"https://text.pollinations.ai/{quote(sys+' '+prompt)}?model={pm}",timeout=45)
            if r.ok and len(r.text)>10:
                if uid:mem.add(uid,"user",prompt);mem.add(uid,"assistant",r.text)
                return f"🌺**[Poll]**\n{r.text}",pm
    except:pass
    return "❌ AI unavailable.","none"

def split(t,lim=1900):
    if len(t)<=lim:return[t]
    ch=[];cur=""
    for l in t.split('\n'):
        if len(cur)+len(l)+1>lim:
            if cur:ch.append(cur)
            cur=l
        else:cur+=('\n'if cur else'')+l
    if cur:ch.append(cur)
    return ch or[t[:lim]]

# ==============================================================================
# 🔓 DEOBF
# ==============================================================================
class Deobf:
    @staticmethod
    def dec(c):
        c=re.sub(r'\\(\d{1,3})',lambda m:chr(int(m.group(1)))if int(m.group(1))<256 else m.group(0),c)
        return re.sub(r'\\x([0-9a-fA-F]{2})',lambda m:chr(int(m.group(1),16)),c)
    @staticmethod
    def det(c):
        p={"Luraph":[r'Luraph'],"IronBrew2":[r'IB2'],"Moonsec":[r'MoonSec'],"PSU":[r'PSU'],"Luarmor":[r'Luarmor'],"Synapse":[r'SynapseXen'],"Prometheus":[r'Prometheus']}
        f=[n for n,ps in p.items()for pt in ps if re.search(pt,c,re.I)]
        if not f and c.count('(')>1000:f=["Heavy Obfuscation"]
        return",".join(f)or"Clean/Unknown"
    @staticmethod
    def strs(c):return[x for x in re.findall(r"'([^']*)'",c)+re.findall(r'"([^"]*)"',c)if 10<len(x)<500][:50]
deobf=Deobf()

# ==============================================================================
# 🔒 LUA OBFUSCATOR (FIXED)
# ==============================================================================
class LuaObf:
    URL="https://luaobfuscator.com/api/obfuscator"
    def __init__(self,key):self.h={"apikey":key,"Content-Type":"application/json"}
    def obf(self,script,preset="medium"):
        presets={"light":{"MinifySigns":True,"Minify":True},
                 "medium":{"MinifySigns":True,"Minify":True,"EncryptStrings":True},
                 "heavy":{"MinifySigns":True,"Minify":True,"MinifyAll":True,"EncryptStrings":True,"ControlFlowFlattenV2AllBlocks":True},
                 "max":{"MinifySigns":True,"Minify":True,"MinifyAll":True,"EncryptStrings":True,"ControlFlowFlattenV2AllBlocks":True,"MaxSecurityV2":True}}
        req=get_requests()
        try:
            # Upload
            r1=req.post(f"{self.URL}/newscript",headers=self.h,json={"script":script},timeout=30)
            logger.info(f"[Obf] Upload: {r1.status_code}")
            if r1.status_code==401:return None,"Invalid API key"
            if r1.status_code==429:return None,"Rate limit exceeded"
            if not r1.text.strip():return None,"Empty response from API"
            try:d1=r1.json()
            except:return None,f"Invalid response: {r1.text[:100]}"
            if d1.get("error"):return None,d1.get("message",str(d1.get("error")))
            if not d1.get("sessionId"):return None,d1.get("message","No session ID")
            sid=d1["sessionId"]
            
            # Obfuscate
            r2=req.post(f"{self.URL}/obfuscate",headers=self.h,json={"sessionId":sid,"options":presets.get(preset,presets["medium"])},timeout=60)
            logger.info(f"[Obf] Process: {r2.status_code}")
            if not r2.text.strip():return None,"Empty obfuscate response"
            try:d2=r2.json()
            except:return None,f"Invalid response: {r2.text[:100]}"
            if d2.get("error"):return None,d2.get("message",str(d2.get("error")))
            if not d2.get("code"):return None,d2.get("message","No code returned")
            return d2["code"],None
        except req.exceptions.Timeout:return None,"Request timeout"
        except Exception as e:return None,str(e)

lua_obf=LuaObf(KEY_LUAOBF)if KEY_LUAOBF else None

# ==============================================================================
# 🛡️ UTILS
# ==============================================================================
def headers():
    return{"User-Agent":random.choice(["Roblox/WinInet","RobloxStudio/WinInet"]),
           "Roblox-Place-Id":random.choice(["2753915549","155615604"]),"Accept-Encoding":"gzip,deflate,br"}

def valid(u):return u.startswith(("http://","https://"))and not any(x in u.lower()for x in["localhost","127.0.0.1","0.0.0.0"])

async def vision(url,prompt="Jelaskan gambar"):
    g=get_genai()
    if not g:return"❌ Gemini unavailable"
    try:
        aio=await get_aiohttp()
        async with aio.ClientSession()as s:
            async with s.get(url)as r:img=await r.read()
        m=g.GenerativeModel('gemini-2.0-flash')
        r=m.generate_content([prompt,{"mime_type":"image/png","data":base64.b64encode(img).decode()}])
        return r.text
    except Exception as e:return f"❌ {e}"

# ==============================================================================
# 📡 EVENTS
# ==============================================================================
@bot.event
async def on_ready():
    logger.info(f'🔥 {bot.user} | {len(bot.guilds)} guilds')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching,name="/help"))
    try:await bot.tree.sync();logger.info("✅ Synced")
    except Exception as e:logger.error(f"Sync: {e}")

@bot.tree.error
async def on_err(i:discord.Interaction,e:app_commands.AppCommandError):
    try:await i.response.send_message(f"❌ {str(e)[:100]}",ephemeral=True)
    except:pass

# ==============================================================================
# 🎮 COMMANDS
# ==============================================================================
@bot.tree.command(name="ping",description="🏓 Latency")
async def ping(i:discord.Interaction):
    e=discord.Embed(title="🏓 Pong!",color=0x00FF00)
    e.add_field(name="Latency",value=f"`{round(bot.latency*1000)}ms`")
    e.add_field(name="Servers",value=f"`{len(bot.guilds)}`")
    await i.response.send_message(embed=e)

@bot.tree.command(name="help",description="📚 Commands")
async def help_cmd(i:discord.Interaction):
    e=discord.Embed(title="📚 Commands",color=0xFFD700)
    for n,d in[("🔓 /dump","Dump script"),("🤖 /tanya","Tanya AI"),("🔍 /explain","Analisa script"),
               ("🔓 /deobf","Deobfuscate"),("🔒 /obfuscate","Obfuscate URL"),("🔒 /obf","Obfuscate file"),
               ("🖼️ /vision","Analisa gambar"),("🧹 /clear","Hapus memory"),("📜 /history","History")]:
        e.add_field(name=n,value=d,inline=True)
    e.set_footer(text="AI: Groq•OpenAI•Gemini•Pollinations")
    await i.response.send_message(embed=e)

@bot.tree.command(name="dump",description="🔓 Dump script")
@app_commands.describe(url="URL",raw="Raw mode")
@rate(10)
@noban()
async def dump(i:discord.Interaction,url:str,raw:bool=False):
    await i.response.defer()
    if not valid(url):return await i.followup.send("❌ Invalid URL!")
    t0=time.time()
    try:
        curl=get_curl();req=get_requests()
        if raw or not SCRAPER_KEY:
            c=curl.get(url,impersonate="chrome120",headers=headers(),timeout=30).text
            m="Raw"
        else:
            c=req.get('http://api.scraperapi.com',params={'api_key':SCRAPER_KEY,'url':url,'keep_headers':'true'},headers=headers(),timeout=90).text
            m="Scraper"
        ext="lua"
        if"<!DOCTYPE"in c[:500]:ext="html"
        elif c.strip().startswith(("{","[")):ext="json"
        e=discord.Embed(title=f"{'✅'if ext=='lua'else'⚠️'} Dump",color=0x00FF00 if ext=="lua"else 0xFFFF00)
        e.add_field(name="Size",value=f"`{len(c):,}B`")
        e.add_field(name="Type",value=f"`.{ext}`")
        e.add_field(name="Via",value=m)
        db.stat("dump",i.user.id,i.guild_id,True,time.time()-t0)
        await i.followup.send(embed=e,file=discord.File(io.BytesIO(c.encode()),f"dump.{ext}"))
    except Exception as ex:
        db.stat("dump",i.user.id,i.guild_id,False,time.time()-t0)
        await i.followup.send(f"💀 {str(ex)[:200]}")

@bot.tree.command(name="tanya",description="🤖 Tanya AI")
@app_commands.describe(q="Pertanyaan",mode="Mode",ctx="Memory")
@app_commands.choices(mode=[app_commands.Choice(name="🎮 Roblox",value="roblox"),app_commands.Choice(name="🐍 Python",value="python"),app_commands.Choice(name="🌐 Web",value="web"),app_commands.Choice(name="💬 General",value="general")])
@rate(8)
@noban()
async def tanya(i:discord.Interaction,q:str,mode:str="general",ctx:bool=True):
    await i.response.defer()
    sp={"roblox":"Ahli Roblox/Lua. Jawab Indonesia.","python":"Ahli Python.","web":"Ahli Web Dev.","general":"Asisten helpful."}
    ic={"roblox":"🎮","python":"🐍","web":"🌐","general":"💬"}
    t0=time.time()
    ans,mdl=ask(q,sp.get(mode,""),i.user.id,ctx)
    ch=split(ans)
    e=discord.Embed(title=f"{ic.get(mode,'🤖')} Q",description=q[:500],color=0x5865F2)
    db.log(i.user.id,i.guild_id,"tanya",q,ans,mdl)
    db.stat("tanya",i.user.id,i.guild_id,True,time.time()-t0)
    await i.followup.send(embed=e,content=ch[0])
    for c in ch[1:]:await i.channel.send(c)

@bot.tree.command(name="explain",description="🔍 Analisa script")
@app_commands.describe(url="URL",detail="Detail")
@app_commands.choices(detail=[app_commands.Choice(name="📝 Ringkas",value="short"),app_commands.Choice(name="📋 Detail",value="detail"),app_commands.Choice(name="🛡️ Security",value="security")])
@rate(15)
@noban()
async def explain(i:discord.Interaction,url:str,detail:str="short"):
    await i.response.defer()
    if not valid(url):return await i.followup.send("❌ Invalid URL!")
    try:
        curl=get_curl()
        r=curl.get(url,impersonate="chrome120",timeout=15)
        lm={"short":4000,"detail":8000,"security":6000}
        pm={"short":"Jelaskan SINGKAT.","detail":"Analisa DETAIL.","security":"Security audit, rating 1-10."}
        ans,_=ask(f"{pm[detail]}\n```lua\n{r.text[:lm.get(detail,4000)]}\n```","Script Analyst.")
        ch=split(ans)
        e=discord.Embed(title=f"{'📝📋🛡️'[['short','detail','security'].index(detail)]} Analysis",color=0x9B59B6)
        e.add_field(name="URL",value=f"`{url[:40]}...`")
        e.add_field(name="Size",value=f"`{len(r.text):,}`")
        await i.followup.send(embed=e,content=ch[0])
        for c in ch[1:]:await i.channel.send(c)
    except Exception as ex:await i.followup.send(f"❌ {str(ex)[:200]}")

@bot.tree.command(name="deobf",description="🔓 Deobfuscate")
@app_commands.describe(url="URL")
@rate(15)
@noban()
async def deobf_cmd(i:discord.Interaction,url:str):
    await i.response.defer()
    if not valid(url):return await i.followup.send("❌ Invalid!")
    try:
        curl=get_curl()
        c=curl.get(url,impersonate="chrome120",timeout=15).text
        ot=deobf.det(c);dc=deobf.dec(c[:15000]);st=deobf.strs(dc)
        e=discord.Embed(title="🔓 Deobf",color=0xE67E22)
        e.add_field(name="Size",value=f"`{len(c):,}`")
        e.add_field(name="Type",value=ot)
        e.add_field(name="Strings",value=f"`{len(st)}`")
        if st:e.add_field(name="Found",value="\n".join([f"• `{s[:35]}...`"if len(s)>35 else f"• `{s}`"for s in st[:6]])[:900],inline=False)
        await i.followup.send(embed=e,file=discord.File(io.BytesIO(dc.encode()),"decoded.lua"))
        ans,_=ask(f"Obfuscated({ot}).Strings:{st[:5]}.Code:{dc[:1500]}.Analisa.","Reverse engineer.")
        await i.channel.send(f"🧠 **AI:**\n{ans[:1900]}")
    except Exception as ex:await i.followup.send(f"❌ {str(ex)[:200]}")

@bot.tree.command(name="obfuscate",description="🔒 Obfuscate URL")
@app_commands.describe(url="URL",preset="Level")
@app_commands.choices(preset=[app_commands.Choice(name="🟢 Light",value="light"),app_commands.Choice(name="🟡 Medium",value="medium"),app_commands.Choice(name="🟠 Heavy",value="heavy"),app_commands.Choice(name="🔴 Max",value="max")])
@rate(20)
@noban()
async def obfuscate_cmd(i:discord.Interaction,url:str,preset:str="medium"):
    if not KEY_LUAOBF:return await i.response.send_message("❌ `LUAOBF_API_KEY` not set!",ephemeral=True)
    await i.response.defer()
    if not valid(url):return await i.followup.send("❌ Invalid URL!")
    try:
        curl=get_curl()
        script=curl.get(url,impersonate="chrome120",timeout=15).text
        if len(script)<10:return await i.followup.send("❌ Script too short!")
        if len(script)>500000:return await i.followup.send("❌ Max 500KB!")
        if"<!DOCTYPE"in script[:100]:return await i.followup.send("❌ Got HTML, not Lua!")
        result,err=lua_obf.obf(script,preset)
        if err:
            tips=""
            if"API key"in err:tips="\n💡 Cek API key di luaobfuscator.com"
            elif"Rate limit"in err:tips="\n💡 Tunggu beberapa menit"
            elif"Empty"in err or"timeout"in err:tips="\n💡 API mungkin down, coba lagi"
            return await i.followup.send(f"❌ Error: `{err}`{tips}")
        ic={"light":"🟢","medium":"🟡","heavy":"🟠","max":"🔴"}
        e=discord.Embed(title=f"{ic.get(preset,'🔒')} Obfuscated!",color=0x00FF00)
        e.add_field(name="📥 Ori",value=f"`{len(script):,}`")
        e.add_field(name="📤 Result",value=f"`{len(result):,}`")
        e.add_field(name="🔒 Preset",value=preset)
        e.set_footer(text="luaobfuscator.com")
        await i.followup.send(embed=e,file=discord.File(io.BytesIO(result.encode()),f"obf_{preset}.lua"))
    except Exception as ex:await i.followup.send(f"💀 {str(ex)[:200]}")

@bot.tree.command(name="obf",description="🔒 Obfuscate file")
@app_commands.describe(file="File .lua",preset="Level")
@app_commands.choices(preset=[app_commands.Choice(name="🟢 Light",value="light"),app_commands.Choice(name="🟡 Medium",value="medium"),app_commands.Choice(name="🟠 Heavy",value="heavy"),app_commands.Choice(name="🔴 Max",value="max")])
@rate(20)
@noban()
async def obf_file(i:discord.Interaction,file:discord.Attachment,preset:str="medium"):
    if not KEY_LUAOBF:return await i.response.send_message("❌ API not configured!",ephemeral=True)
    if not file.filename.endswith(('.lua','.txt')):return await i.response.send_message("❌ .lua/.txt only!",ephemeral=True)
    if file.size>500000:return await i.response.send_message("❌ Max 500KB!",ephemeral=True)
    await i.response.defer()
    try:
        script=(await file.read()).decode('utf-8')
        result,err=lua_obf.obf(script,preset)
        if err:return await i.followup.send(f"❌ {err}")
        ic={"light":"🟢","medium":"🟡","heavy":"🟠","max":"🔴"}
        e=discord.Embed(title=f"{ic.get(preset,'🔒')} Done!",color=0x00FF00)
        e.add_field(name="📁",value=f"`{file.filename}`")
        e.add_field(name="📥",value=f"`{len(script):,}`")
        e.add_field(name="📤",value=f"`{len(result):,}`")
        await i.followup.send(embed=e,file=discord.File(io.BytesIO(result.encode()),f"obf_{file.filename}"))
    except Exception as ex:await i.followup.send(f"💀 {str(ex)[:200]}")

@bot.tree.command(name="vision",description="🖼️ Analisa gambar")
@app_commands.describe(url="Image URL",prompt="Question")
@rate(10)
@noban()
async def vision_cmd(i:discord.Interaction,url:str,prompt:str="Jelaskan gambar ini dalam Bahasa Indonesia"):
    await i.response.defer()
    r=await vision(url,prompt)
    ch=split(r)
    e=discord.Embed(title="🖼️ Vision",color=0x9B59B6)
    e.set_thumbnail(url=url)
    await i.followup.send(embed=e,content=ch[0])
    for c in ch[1:]:await i.channel.send(c)

@bot.tree.command(name="analyze",description="🔍 Analisa gambar upload")
@app_commands.describe(img="Image file")
@rate(10)
@noban()
async def analyze(i:discord.Interaction,img:discord.Attachment):
    await i.response.defer()
    if not img.content_type or not img.content_type.startswith('image/'):return await i.followup.send("❌ Image only!")
    r=await vision(img.url,"Analisis gambar ini.")
    await i.followup.send(f"🖼️ **Hasil:**\n{r[:1900]}")

@bot.tree.command(name="clear",description="🧹 Hapus memory")
async def clear(i:discord.Interaction):mem.clr(i.user.id);await i.response.send_message("🧹 Cleared!",ephemeral=True)

@bot.tree.command(name="history",description="📜 History")
@app_commands.describe(n="Count")
async def hist(i:discord.Interaction,n:int=5):
    h=db.hist(i.user.id,min(n,10))
    if not h:return await i.response.send_message("📭 Empty.",ephemeral=True)
    e=discord.Embed(title="📜 History",color=0x3498DB)
    for idx,(p,r,t)in enumerate(h,1):e.add_field(name=f"{idx}. {p[:40]}...",value=f"```{r[:80]}...```",inline=False)
    await i.response.send_message(embed=e,ephemeral=True)

# ==============================================================================
# 👑 OWNER
# ==============================================================================
@bot.tree.command(name="stats",description="📊 Stats")
@owner()
async def stats(i:discord.Interaction):
    s=db.stats()
    e=discord.Embed(title="📊 Stats",color=0x3498DB)
    e.add_field(name="Total",value=f"`{s['total']:,}`")
    e.add_field(name="Servers",value=f"`{len(bot.guilds)}`")
    if s['cmds']:e.add_field(name="Top",value="\n".join([f"• `{c[0]}`: {c[1]}x"for c in s['cmds'][:5]]),inline=False)
    await i.response.send_message(embed=e)

@bot.tree.command(name="blacklist",description="🚫 Ban")
@owner()
@app_commands.describe(user="User",reason="Reason")
async def bl(i:discord.Interaction,user:discord.User,reason:str="No reason"):
    db.ban(user.id,reason,i.user.id);await i.response.send_message(f"🚫 {user} banned: {reason}")

@bot.tree.command(name="unblacklist",description="✅ Unban")
@owner()
@app_commands.describe(user="User")
async def ubl(i:discord.Interaction,user:discord.User):
    db.unban(user.id);await i.response.send_message(f"✅ {user} unbanned")

@bot.tree.command(name="reload",description="🔄 Sync")
@owner()
async def reload(i:discord.Interaction):
    await i.response.defer()
    try:s=await bot.tree.sync();await i.followup.send(f"✅ {len(s)} synced!")
    except Exception as e:await i.followup.send(f"❌ {e}")

@bot.tree.command(name="servers",description="🌐 List")
@owner()
async def servers(i:discord.Interaction):
    e=discord.Embed(title="🌐 Servers",color=0x3498DB)
    for idx,g in enumerate(bot.guilds[:20],1):e.add_field(name=f"{idx}. {g.name[:20]}",value=f"👥{g.member_count}",inline=True)
    await i.response.send_message(embed=e,ephemeral=True)

# ==============================================================================
# 🚀 START
# ==============================================================================
if __name__=="__main__":
    keep_alive()
    time.sleep(1)
    print(f"🚀 Starting | APIs: Groq{'✅'if KEY_GROQ else'❌'} OpenAI{'✅'if KEY_OPENAI else'❌'} Gemini{'✅'if KEY_GEMINI else'❌'} LuaObf{'✅'if KEY_LUAOBF else'❌'}")
    try:bot.run(DISCORD_TOKEN,log_handler=None)
    except Exception as e:print(f"❌ {e}")
