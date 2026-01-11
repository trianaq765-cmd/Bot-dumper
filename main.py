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

logging.basicConfig(level=logging.INFO,format='%(asctime)s|%(levelname)s|%(message)s')
logger=logging.getLogger(__name__)

SCRAPER_KEY=os.getenv("SCRAPER_API_KEY")
KEY_GROQ=os.getenv("GROQ_API_KEY")
KEY_GEMINI=os.getenv("GEMINI_API_KEY")
KEY_OPENAI=os.getenv("OPENAI_API_KEY")
DISCORD_TOKEN=os.getenv("DISCORD_TOKEN")
ERROR_WEBHOOK=os.getenv("ERROR_WEBHOOK_URL")
OWNER_IDS=[int(x)for x in os.getenv("OWNER_IDS","0").split(",")if x.isdigit()]
if not DISCORD_TOKEN:logger.critical("❌ NO TOKEN!");exit(1)

intents=discord.Intents.default()
intents.message_content=True
bot=commands.Bot(command_prefix="!",intents=intents)

class Database:
    def __init__(self,path="bot_data.db"):
        self.conn=sqlite3.connect(path,check_same_thread=False);self._setup()
    def _setup(self):
        c=self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS chat_history(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,guild_id INTEGER,command TEXT,prompt TEXT,response TEXT,ai_model TEXT,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS blacklist(user_id INTEGER PRIMARY KEY,reason TEXT,banned_by INTEGER,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS usage_stats(id INTEGER PRIMARY KEY AUTOINCREMENT,command TEXT,user_id INTEGER,guild_id INTEGER,success INTEGER,exec_time REAL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        self.conn.commit()
    def log_chat(self,uid,gid,cmd,prompt,resp,model):self.conn.execute('INSERT INTO chat_history(user_id,guild_id,command,prompt,response,ai_model)VALUES(?,?,?,?,?,?)',(uid,gid,cmd,prompt,resp[:5000],model));self.conn.commit()
    def get_history(self,uid,limit=5):return self.conn.execute('SELECT prompt,response,created_at FROM chat_history WHERE user_id=? ORDER BY created_at DESC LIMIT ?',(uid,limit)).fetchall()
    def is_blacklisted(self,uid):return self.conn.execute('SELECT 1 FROM blacklist WHERE user_id=?',(uid,)).fetchone()is not None
    def add_blacklist(self,uid,reason,by):self.conn.execute('INSERT OR REPLACE INTO blacklist(user_id,reason,banned_by)VALUES(?,?,?)',(uid,reason,by));self.conn.commit()
    def remove_blacklist(self,uid):self.conn.execute('DELETE FROM blacklist WHERE user_id=?',(uid,));self.conn.commit()
    def log_usage(self,cmd,uid,gid,success,t):self.conn.execute('INSERT INTO usage_stats(command,user_id,guild_id,success,exec_time)VALUES(?,?,?,?,?)',(cmd,uid,gid,int(success),t));self.conn.commit()
    def get_stats(self):
        c=self.conn.cursor()
        return{"total":c.execute('SELECT COUNT(*)FROM usage_stats').fetchone()[0],"commands":c.execute('SELECT command,COUNT(*),AVG(exec_time)FROM usage_stats GROUP BY command ORDER BY COUNT(*)DESC').fetchall(),"top_users":c.execute('SELECT user_id,COUNT(*)FROM usage_stats GROUP BY user_id ORDER BY COUNT(*)DESC LIMIT 5').fetchall()}
db=Database()

class RateLimiter:
    def __init__(self):self.cd=defaultdict(lambda:defaultdict(float))
    def check(self,uid,cmd,t=5.0):
        now=time.time();last=self.cd[uid][cmd]
        if now-last<t:return False,t-(now-last)
        self.cd[uid][cmd]=now;return True,0
rl=RateLimiter()

def rate_limit(s=5.0):
    async def pred(i:discord.Interaction)->bool:
        ok,rem=rl.check(i.user.id,i.command.name,s)
        if not ok:await i.response.send_message(f"⏳ Tunggu **{rem:.1f}s**",ephemeral=True);return False
        return True
    return app_commands.check(pred)

def is_owner():
    async def pred(i:discord.Interaction)->bool:
        if i.user.id not in OWNER_IDS:await i.response.send_message("❌ Owner only!",ephemeral=True);return False
        return True
    return app_commands.check(pred)

def not_blacklisted():
    async def pred(i:discord.Interaction)->bool:
        if db.is_blacklisted(i.user.id):await i.response.send_message("🚫 Blacklisted!",ephemeral=True);return False
        return True
    return app_commands.check(pred)

@dataclass
class Msg:
    role:str;content:str;ts:float
class Memory:
    def __init__(self,mx=10,exp=30):self.cv=defaultdict(list);self.mx=mx;self.exp=exp*60
    def add(self,uid,role,content):self._cl(uid);self.cv[uid].append(Msg(role,content,time.time()));self.cv[uid]=self.cv[uid][-self.mx:]if len(self.cv[uid])>self.mx else self.cv[uid]
    def get(self,uid):self._cl(uid);return[{"role":m.role,"content":m.content}for m in self.cv[uid]]
    def clear(self,uid):self.cv[uid]=[]
    def _cl(self,uid):now=time.time();self.cv[uid]=[m for m in self.cv[uid]if now-m.ts<self.exp]
mem=Memory()

GROQ_M=["llama-3.3-70b-versatile","llama-3.1-8b-instant","mixtral-8x7b-32768"]
OPENAI_M=["gpt-4o","gpt-4o-mini","gpt-4-turbo"]
GEMINI_M=["gemini-2.0-flash","gemini-1.5-pro","gemini-1.5-flash"]

def ask_ai(prompt:str,system:str="Kamu adalah ahli coding.",uid:int=None,use_ctx:bool=False)->tuple[str,str]:
    msgs=[{"role":"system","content":system}]
    if use_ctx and uid:msgs.extend(mem.get(uid))
    msgs.append({"role":"user","content":prompt})
    #1 GROQ
    if KEY_GROQ:
        for m in GROQ_M[:2]:
            try:
                r=Groq(api_key=KEY_GROQ).chat.completions.create(messages=msgs,model=m,temperature=0.7,max_tokens=4096)
                resp=r.choices[0].message.content
                if uid:mem.add(uid,"user",prompt);mem.add(uid,"assistant",resp)
                return f"⚡**[Groq-{m}]**\n{resp}",m
            except Exception as e:logger.warning(f"Groq {m}:{e}")
    #2 OPENAI
    if KEY_OPENAI:
        for m in OPENAI_M[:2]:
            try:
                r=OpenAI(api_key=KEY_OPENAI).chat.completions.create(model=m,messages=msgs,temperature=0.7,max_tokens=4096)
                resp=r.choices[0].message.content
                if uid:mem.add(uid,"user",prompt);mem.add(uid,"assistant",resp)
                return f"🤖**[OpenAI-{m}]**\n{resp}",m
            except Exception as e:logger.warning(f"OpenAI {m}:{e}")
    #3 GEMINI
    if KEY_GEMINI:
        for m in GEMINI_M:
            try:
                genai.configure(api_key=KEY_GEMINI)
                sf=[{"category":c,"threshold":"BLOCK_NONE"}for c in["HARM_CATEGORY_HARASSMENT","HARM_CATEGORY_HATE_SPEECH","HARM_CATEGORY_SEXUALLY_EXPLICIT","HARM_CATEGORY_DANGEROUS_CONTENT"]]
                r=genai.GenerativeModel(m,safety_settings=sf,system_instruction=system).generate_content(prompt)
                if uid:mem.add(uid,"user",prompt);mem.add(uid,"assistant",r.text)
                return f"🧠**[Gemini-{m}]**\n{r.text}",m
            except Exception as e:logger.warning(f"Gemini {m}:{e}")
    #4 POLLINATIONS
    try:
        for pm in["openai","mistral","claude"]:
            r=requests.get(f"https://text.pollinations.ai/{quote(system+' '+prompt)}?model={pm}",timeout=45)
            if r.status_code==200 and len(r.text)>10:
                if uid:mem.add(uid,"user",prompt);mem.add(uid,"assistant",r.text)
                return f"🌺**[Poll-{pm}]**\n{r.text}",pm
    except:pass
    return "❌ Semua AI down.","none"

def split_msg(t,lim=1900):
    if len(t)<=lim:return[t]
    ch=[];cur=""
    for l in t.split('\n'):
        if len(cur)+len(l)+1>lim:
            if cur:ch.append(cur)
            cur=l
        else:cur+=('\n'if cur else'')+l
    if cur:ch.append(cur)
    return ch if ch else[t[:lim]]

class Deobf:
    @staticmethod
    def decode(c):
        c=re.sub(r'\\(\d{1,3})',lambda m:chr(int(m.group(1)))if int(m.group(1))<256 else m.group(0),c)
        return re.sub(r'\\x([0-9a-fA-F]{2})',lambda m:chr(int(m.group(1),16)),c)
    @staticmethod
    def detect(c):
        p={"Luraph":[r'Luraph'],"IronBrew2":[r'IB2'],"Moonsec":[r'MoonSec'],"PSU":[r'PSU'],"Luarmor":[r'Luarmor'],"Synapse":[r'SynapseXen'],"Prometheus":[r'Prometheus']}
        f=[n for n,ps in p.items()for pt in ps if re.search(pt,c,re.I)]
        if not f and c.count('(')>1000:f=["Heavy Obfuscation"]
        return",".join(f)if f else"Clean/Unknown"
    @staticmethod
    def strings(c):return[x for x in re.findall(r"'([^']*)'",c)+re.findall(r'"([^"]*)"',c)if 10<len(x)<500][:50]
deobf=Deobf()

def get_headers():return{"User-Agent":random.choice(["Roblox/WinInet","RobloxStudio/WinInet"]),"Roblox-Place-Id":random.choice(["2753915549","155615604"]),"Accept-Encoding":"gzip,deflate,br"}
def valid_url(u):return not any(b in u.lower()for b in["localhost","127.0.0.1","0.0.0.0"])and u.startswith(("http://","https://"))

async def report_err(e,ctx=""):
    if not ERROR_WEBHOOK:return
    try:
        async with aiohttp.ClientSession()as s:await s.post(ERROR_WEBHOOK,json={"embeds":[{"title":"🚨 Error","color":0xFF0000,"fields":[{"name":"Type","value":f"`{type(e).__name__}`"},{"name":"Ctx","value":ctx},{"name":"Msg","value":f"```{str(e)[:500]}```"}]}]})
    except:pass

async def vision_ai(url,prompt="Jelaskan gambar"):
    if not KEY_GEMINI:return"❌ No Gemini"
    try:
        async with aiohttp.ClientSession()as s:
            async with s.get(url)as r:img=await r.read()
        genai.configure(api_key=KEY_GEMINI)
        return genai.GenerativeModel('gemini-2.0-flash').generate_content([prompt,{"mime_type":"image/png","data":base64.b64encode(img).decode()}]).text
    except Exception as e:return f"❌ {e}"

@bot.event
async def on_ready():
    logger.info(f'🔥 {bot.user}|{len(bot.guilds)} servers')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching,name="/help"))
    try:s=await bot.tree.sync();logger.info(f"✅ {len(s)} cmds")
    except Exception as e:logger.error(f"Sync:{e}")

@bot.tree.error
async def on_err(i:discord.Interaction,e:app_commands.AppCommandError):
    await report_err(e,f"/{i.command.name if i.command else'?'}")
    try:await i.response.send_message(f"❌ {str(e)[:100]}",ephemeral=True)
    except:pass

@bot.tree.command(name="ping",description="🏓 Latency")
async def ping(i:discord.Interaction):
    lat=round(bot.latency*1000)
    e=discord.Embed(title="🏓 Pong!",color=0x00FF00)
    e.add_field(name="Latency",value=f"`{lat}ms`");e.add_field(name="Status",value="🟢"if lat<100 else"🟡"if lat<200 else"🔴")
    await i.response.send_message(embed=e)

@bot.tree.command(name="help",description="📚 Help")
async def help_cmd(i:discord.Interaction):
    e=discord.Embed(title="📚 Commands",color=0xFFD700)
    for n,d in[("🔓 /dump","Dump script"),("🤖 /tanya","Tanya AI"),("🔍 /explain","Analisa"),("🔓 /deobf","Deobfuscate"),("🖼️ /vision","Gambar AI"),("🧹 /clear","Hapus memory"),("📜 /history","History"),("📊 /stats","Stats(owner)")]:
        e.add_field(name=n,value=d,inline=False)
    e.add_field(name="🧠 AI 2025",value="Groq•OpenAI GPT-4o•Gemini 2.0•Pollinations",inline=False)
    await i.response.send_message(embed=e)

@bot.tree.command(name="dump",description="🔓 Dump script")
@app_commands.describe(url="URL",raw="Raw mode")
@rate_limit(10)
@not_blacklisted()
async def dump(i:discord.Interaction,url:str,raw:bool=False):
    await i.response.defer();t0=time.time()
    if not valid_url(url):return await i.followup.send("❌ Invalid URL!")
    try:
        if raw or not SCRAPER_KEY:c=curl_requests.get(url,impersonate="chrome120",headers=get_headers(),timeout=30).text;m="Raw"
        else:c=requests.get('http://api.scraperapi.com',params={'api_key':SCRAPER_KEY,'url':url,'keep_headers':'true'},headers=get_headers(),timeout=90).text;m="ScraperAPI"
        ext="lua";st="✅"
        if"<!DOCTYPE"in c[:500]or"<html"in c[:100]:ext="html";st="⚠️"
        elif c.strip().startswith(("{","[")):ext="json"
        e=discord.Embed(title=f"{st} Dump",color=0x00FF00 if ext=="lua"else 0xFFFF00)
        e.add_field(name="📎",value=f"`{url[:40]}...`",inline=False);e.add_field(name="📦",value=f"`{len(c):,}B`",inline=True);e.add_field(name="📄",value=f"`.{ext}`",inline=True);e.add_field(name="🔧",value=m,inline=True)
        db.log_usage("dump",i.user.id,i.guild_id,True,time.time()-t0)
        await i.followup.send(embed=e,file=discord.File(io.BytesIO(c.encode()),f"dump.{ext}"))
    except Exception as ex:db.log_usage("dump",i.user.id,i.guild_id,False,time.time()-t0);await i.followup.send(f"💀 {str(ex)[:200]}")

@bot.tree.command(name="tanya",description="🤖 Tanya AI")
@app_commands.describe(pertanyaan="Question",mode="Mode",context="Use memory")
@app_commands.choices(mode=[app_commands.Choice(name="🎮 Roblox",value="roblox"),app_commands.Choice(name="🐍 Python",value="python"),app_commands.Choice(name="🌐 Web",value="web"),app_commands.Choice(name="💬 General",value="general")])
@rate_limit(8)
@not_blacklisted()
async def tanya(i:discord.Interaction,pertanyaan:str,mode:str="general",context:bool=True):
    await i.response.defer();t0=time.time()
    sp={"roblox":"Ahli Roblox/Lua.","python":"Ahli Python.","web":"Ahli Web Dev.","general":"Asisten helpful."}
    ic={"roblox":"🎮","python":"🐍","web":"🌐","general":"💬"}
    ans,mdl=ask_ai(pertanyaan,sp.get(mode,""),i.user.id,context)
    ch=split_msg(ans)
    e=discord.Embed(title=f"{ic.get(mode,'🤖')} Q",description=pertanyaan[:500],color=0x5865F2);e.set_footer(text=f"By {i.user}")
    db.log_chat(i.user.id,i.guild_id,"tanya",pertanyaan,ans,mdl);db.log_usage("tanya",i.user.id,i.guild_id,True,time.time()-t0)
    await i.followup.send(embed=e,content=ch[0])
    for c in ch[1:]:await i.channel.send(c)

@bot.tree.command(name="explain",description="🔍 Analisa script")
@app_commands.describe(url="URL",detail="Detail level")
@app_commands.choices(detail=[app_commands.Choice(name="📝 Ringkas",value="short"),app_commands.Choice(name="📋 Detail",value="detail"),app_commands.Choice(name="🛡️ Security",value="security")])
@rate_limit(15)
@not_blacklisted()
async def explain(i:discord.Interaction,url:str,detail:str="short"):
    await i.response.defer()
    if not valid_url(url):return await i.followup.send("❌ Invalid!")
    try:
        r=curl_requests.get(url,impersonate="chrome120",timeout=15)
        lm={"short":4000,"detail":8000,"security":6000}
        pm={"short":"Jelaskan SINGKAT.","detail":"Analisa DETAIL.","security":"Security audit: backdoor? Rating 1-10."}
        ans,_=ask_ai(f"{pm[detail]}\n```lua\n{r.text[:lm.get(detail,4000)]}\n```","Script Analyst.")
        ch=split_msg(ans);ic={"short":"📝","detail":"📋","security":"🛡️"}
        e=discord.Embed(title=f"{ic.get(detail,'🔍')} Analysis",color=0x9B59B6)
        e.add_field(name="🔗",value=f"`{url[:40]}...`",inline=False);e.add_field(name="📊",value=f"`{len(r.text):,}`",inline=True)
        await i.followup.send(embed=e,content=ch[0])
        for c in ch[1:]:await i.channel.send(c)
    except Exception as ex:await i.followup.send(f"❌ {str(ex)[:200]}")

@bot.tree.command(name="deobf",description="🔓 Deobfuscate")
@app_commands.describe(url="URL")
@rate_limit(15)
@not_blacklisted()
async def deobfuscate(i:discord.Interaction,url:str):
    await i.response.defer()
    if not valid_url(url):return await i.followup.send("❌ Invalid!")
    try:
        r=curl_requests.get(url,impersonate="chrome120",timeout=15);c=r.text
        ot=deobf.detect(c);dc=deobf.decode(c[:15000]);st=deobf.strings(dc)
        e=discord.Embed(title="🔓 Deobf",color=0xE67E22)
        e.add_field(name="📦",value=f"`{len(c):,}`",inline=True);e.add_field(name="🔍",value=ot,inline=True);e.add_field(name="📝",value=f"`{len(st)}`",inline=True)
        if st:e.add_field(name="🔑 Strings",value="\n".join([f"• `{s[:35]}...`"if len(s)>35 else f"• `{s}`"for s in st[:6]])[:900],inline=False)
        await i.followup.send(embed=e,file=discord.File(io.BytesIO(dc.encode()),"decoded.lua"))
        ans,_=ask_ai(f"Obfuscated({ot}).Strings:{st[:5]}.Preview:{dc[:1200]}.Analisa.","Reverse engineer.")
        await i.channel.send(f"🧠 **AI:**\n{ans[:1900]}")
    except Exception as ex:await i.followup.send(f"❌ {str(ex)[:200]}")

@bot.tree.command(name="vision",description="🖼️ Analisa gambar")
@app_commands.describe(url="Image URL",prompt="Question")
@rate_limit(10)
@not_blacklisted()
async def vision(i:discord.Interaction,url:str,prompt:str="Jelaskan gambar ini"):
    await i.response.defer()
    r=await vision_ai(url,prompt);ch=split_msg(r)
    e=discord.Embed(title="🖼️ Vision",color=0x9B59B6);e.set_thumbnail(url=url);e.add_field(name="❓",value=prompt[:150],inline=False)
    await i.followup.send(embed=e,content=ch[0])
    for c in ch[1:]:await i.channel.send(c)

@bot.tree.command(name="analyze",description="🔍 Upload gambar")
@app_commands.describe(gambar="Image file")
@rate_limit(10)
@not_blacklisted()
async def analyze(i:discord.Interaction,gambar:discord.Attachment):
    await i.response.defer()
    if not gambar.content_type or not gambar.content_type.startswith('image/'):return await i.followup.send("❌ Image only!")
    r=await vision_ai(gambar.url,"Analisis gambar ini.")
    await i.followup.send(f"🖼️ **Hasil:**\n{r[:1900]}")

@bot.tree.command(name="clear",description="🧹 Clear memory")
async def clear_mem(i:discord.Interaction):mem.clear(i.user.id);await i.response.send_message("🧹 Cleared!",ephemeral=True)

@bot.tree.command(name="history",description="📜 Chat history")
@app_commands.describe(limit="Count")
async def history(i:discord.Interaction,limit:int=5):
    h=db.get_history(i.user.id,min(limit,10))
    if not h:return await i.response.send_message("📭 Empty.",ephemeral=True)
    e=discord.Embed(title="📜 History",color=0x3498DB)
    for idx,(p,r,t)in enumerate(h,1):e.add_field(name=f"{idx}. {p[:40]}...",value=f"```{r[:80]}...```",inline=False)
    await i.response.send_message(embed=e,ephemeral=True)

@bot.tree.command(name="stats",description="📊 Stats")
@is_owner()
async def stats(i:discord.Interaction):
    s=db.get_stats()
    e=discord.Embed(title="📊 Stats",color=0x3498DB)
    e.add_field(name="Total",value=f"`{s['total']:,}`",inline=True);e.add_field(name="Servers",value=f"`{len(bot.guilds)}`",inline=True);e.add_field(name="Users",value=f"`{sum(g.member_count or 0 for g in bot.guilds):,}`",inline=True)
    if s['commands']:e.add_field(name="Top Cmds",value="\n".join([f"• `{c[0]}`: {c[1]}x"for c in s['commands'][:5]]),inline=False)
    await i.response.send_message(embed=e)

@bot.tree.command(name="blacklist",description="🚫 Blacklist")
@is_owner()
@app_commands.describe(user="Target",reason="Reason")
async def bl(i:discord.Interaction,user:discord.User,reason:str="No reason"):db.add_blacklist(user.id,reason,i.user.id);await i.response.send_message(f"🚫 {user} blacklisted")

@bot.tree.command(name="unblacklist",description="✅ Unblacklist")
@is_owner()
@app_commands.describe(user="Target")
async def ubl(i:discord.Interaction,user:discord.User):db.remove_blacklist(user.id);await i.response.send_message(f"✅ {user} unblacklisted")

@bot.tree.command(name="reload",description="🔄 Sync")
@is_owner()
async def reload_cmd(i:discord.Interaction):
    await i.response.defer()
    try:s=await bot.tree.sync();await i.followup.send(f"✅ {len(s)} synced!")
    except Exception as e:await i.followup.send(f"❌ {e}")

@bot.tree.command(name="setai",description="⚙️ Set AI priority")
@is_owner()
@app_commands.describe(priority="Order: groq,openai,gemini")
async def setai(i:discord.Interaction,priority:str):
    await i.response.send_message(f"⚙️ AI Priority: `{priority}`\n(Feature placeholder)",ephemeral=True)

# Ganti bagian terakhir
if __name__ == "__main__":
    import os
    
    # Start web server FIRST
    keep_alive()
    
    # Tunggu sebentar biar server ready
    import time
    time.sleep(2)
    
    logger.info("🚀 Starting...")
    logger.info(f"📦 Groq:{'✅' if KEY_GROQ else '❌'} OpenAI:{'✅' if KEY_OPENAI else '❌'} Gemini:{'✅' if KEY_GEMINI else '❌'}")
    
    try:
        bot.run(DISCORD_TOKEN, log_handler=None)
    except discord.LoginFailure:
        logger.critical("❌ Invalid token!")
    except Exception as e:
        logger.critical(f"❌ {e}")
