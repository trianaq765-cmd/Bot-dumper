import discord,os,io,re,time,json,logging,sqlite3,random
from collections import defaultdict
from dataclasses import dataclass
from discord import app_commands
from discord.ext import commands
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
OWNER_IDS=[int(x)for x in os.getenv("OWNER_IDS","0").split(",")if x.isdigit()]
PREFIX=os.getenv("BOT_PREFIX","!")
if not DISCORD_TOKEN:
    print("❌ NO TOKEN!")
    exit(1)
intents=discord.Intents.default()
intents.message_content=True
bot=commands.Bot(command_prefix=PREFIX,intents=intents,help_command=None)
UA_LIST=["Roblox/WinInet","Synapse-X/2.0","Sentinel/3.0","Krnl/1.0","KRNL/2.0","Fluxus/1.0","ScriptWare/2.0","Electron/1.0","Hydrogen/1.0","Codex/1.0","Arceus-X/2.0","Delta/1.0","Trigon/3.0","Evon/1.0","JJSploit/7.0"]
_groq=None
_curl=None
_requests=None
_pd=None
_openpyxl=None
def get_groq():
    global _groq
    if _groq is None and KEY_GROQ:
        from groq import Groq
        _groq=Groq(api_key=KEY_GROQ)
    return _groq
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
def get_pandas():
    global _pd
    if _pd is None:
        import pandas as pd
        _pd=pd
    return _pd
def get_openpyxl():
    global _openpyxl
    if _openpyxl is None:
        import openpyxl
        _openpyxl=openpyxl
    return _openpyxl
class Database:
    def __init__(self,path="bot.db"):
        self.conn=sqlite3.connect(path,check_same_thread=False)
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY,uid INTEGER,gid INTEGER,cmd TEXT,prompt TEXT,resp TEXT,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS blacklist(uid INTEGER PRIMARY KEY,reason TEXT,by_uid INTEGER);
            CREATE TABLE IF NOT EXISTS stats(id INTEGER PRIMARY KEY,cmd TEXT,uid INTEGER,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS user_prefs(uid INTEGER PRIMARY KEY,model TEXT DEFAULT 'auto',updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        ''')
    def log(self,uid,gid,cmd,p,r):
        self.conn.execute('INSERT INTO history(uid,gid,cmd,prompt,resp)VALUES(?,?,?,?,?)',(uid,gid,cmd,p,r[:4000]if r else""))
        self.conn.commit()
    def hist(self,uid,n=5):
        return self.conn.execute('SELECT prompt,resp FROM history WHERE uid=? ORDER BY ts DESC LIMIT ?',(uid,n)).fetchall()
    def banned(self,uid):
        return self.conn.execute('SELECT 1 FROM blacklist WHERE uid=?',(uid,)).fetchone()is not None
    def ban(self,uid,r,by):
        self.conn.execute('INSERT OR REPLACE INTO blacklist VALUES(?,?,?)',(uid,r,by))
        self.conn.commit()
    def unban(self,uid):
        self.conn.execute('DELETE FROM blacklist WHERE uid=?',(uid,))
        self.conn.commit()
    def stat(self,cmd,uid):
        self.conn.execute('INSERT INTO stats(cmd,uid)VALUES(?,?)',(cmd,uid))
        self.conn.commit()
    def get_stats(self):
        return self.conn.execute('SELECT cmd,COUNT(*)FROM stats GROUP BY cmd ORDER BY COUNT(*)DESC').fetchall()
    def get_user_model(self,uid):
        r=self.conn.execute('SELECT model FROM user_prefs WHERE uid=?',(uid,)).fetchone()
        return r[0] if r else "auto"
    def set_user_model(self,uid,model):
        self.conn.execute('INSERT OR REPLACE INTO user_prefs(uid,model,updated)VALUES(?,?,CURRENT_TIMESTAMP)',(uid,model))
        self.conn.commit()
db=Database()
class RL:
    def __init__(self):
        self.cd=defaultdict(lambda:defaultdict(float))
    def ok(self,uid,cmd,t=5):
        now=time.time()
        if now-self.cd[uid][cmd]<t:
            return False,t-(now-self.cd[uid][cmd])
        self.cd[uid][cmd]=now
        return True,0
rl=RL()
def rate(s=5):
    async def p(i:discord.Interaction)->bool:
        ok,r=rl.ok(i.user.id,i.command.name,s)
        if not ok:
            await i.response.send_message(f"⏳ Tunggu **{r:.1f}s**",ephemeral=True)
            return False
        return True
    return app_commands.check(p)
def owner():
    async def p(i:discord.Interaction)->bool:
        if i.user.id not in OWNER_IDS:
            await i.response.send_message("❌ Owner only!",ephemeral=True)
            return False
        return True
    return app_commands.check(p)
def noban():
    async def p(i:discord.Interaction)->bool:
        if db.banned(i.user.id):
            await i.response.send_message("🚫 Blacklisted!",ephemeral=True)
            return False
        return True
    return app_commands.check(p)
@dataclass
class Msg:
    role:str
    content:str
    ts:float
class Memory:
    def __init__(self):
        self.data=defaultdict(list)
    def add(self,uid,role,content):
        now=time.time()
        self.data[uid]=[m for m in self.data[uid] if now-m.ts<3600]
        self.data[uid].append(Msg(role,content[:2000],now))
        if len(self.data[uid])>20:
            self.data[uid]=self.data[uid][-20:]
    def get(self,uid):
        now=time.time()
        valid=[m for m in self.data[uid] if now-m.ts<3600]
        self.data[uid]=valid
        return[{"role":m.role,"content":m.content}for m in valid]
    def clear(self,uid):
        self.data[uid]=[]
    def get_last_n(self,uid,n=10):
        msgs=self.get(uid)
        return msgs[-n:] if len(msgs)>n else msgs
mem=Memory()
class FileReader:
    @staticmethod
    async def read(attachment)->tuple:
        fn=attachment.filename.lower()
        content=await attachment.read()
        try:
            if fn.endswith(('.xlsx','.xls')):
                return FileReader._excel(content)
            elif fn.endswith('.csv'):
                return FileReader._csv(content)
            elif fn.endswith('.json'):
                return FileReader._json(content)
            else:
                return FileReader._text(content,fn)
        except Exception as e:
            return f"Error: {e}","error",{}
    @staticmethod
    def _excel(content):
        pd=get_pandas()
        sheets=pd.read_excel(io.BytesIO(content),sheet_name=None)
        result=[]
        meta={"sheets":[],"rows":0}
        for name,df in sheets.items():
            meta["sheets"].append(name)
            meta["rows"]+=len(df)
            result.append(f"=== SHEET: {name} ===\n{df.to_string(max_rows=30)}")
        return '\n'.join(result)[:6000],"excel",meta
    @staticmethod
    def _csv(content):
        pd=get_pandas()
        df=pd.read_csv(io.StringIO(content.decode('utf-8',errors='ignore')))
        return df.to_string(max_rows=30)[:6000],"csv",{"rows":len(df)}
    @staticmethod
    def _json(content):
        data=json.loads(content.decode('utf-8',errors='ignore'))
        return json.dumps(data,indent=2,ensure_ascii=False)[:6000],"json",{}
    @staticmethod
    def _text(content,fn):
        return content.decode('utf-8',errors='ignore')[:6000],fn.split('.')[-1]if'.'in fn else'txt',{}
freader=FileReader()
class ExcelGen:
    @staticmethod
    def generate(data)->io.BytesIO:
        openpyxl=get_openpyxl()
        from openpyxl.styles import Font,PatternFill,Alignment,Border,Side
        from openpyxl.utils import get_column_letter
        wb=openpyxl.Workbook()
        wb.remove(wb.active)
        sheets=data.get("sheets",[])
        if not sheets:
            sheets=[{"name":"Sheet1","headers":data.get("headers",[]),"data":data.get("data",[])}]
        for sh in sheets:
            ws=wb.create_sheet(title=str(sh.get("name","Sheet1"))[:31])
            headers=sh.get("headers",[])
            rows=sh.get("data",[])
            hfill=PatternFill(start_color="4472C4",end_color="4472C4",fill_type="solid")
            hfont=Font(bold=True,color="FFFFFF")
            border=Border(left=Side(style='thin'),right=Side(style='thin'),top=Side(style='thin'),bottom=Side(style='thin'))
            for ci,h in enumerate(headers,1):
                c=ws.cell(row=1,column=ci,value=str(h))
                c.font=hfont
                c.fill=hfill
                c.border=border
                c.alignment=Alignment(horizontal='center')
            for ri,row in enumerate(rows,2):
                if not isinstance(row,(list,tuple)):row=[row]
                for ci,val in enumerate(row,1):
                    c=ws.cell(row=ri,column=ci,value=val)
                    c.border=border
            for ci in range(1,len(headers)+1):
                ws.column_dimensions[get_column_letter(ci)].width=15
            ws.freeze_panes='A2'
        out=io.BytesIO()
        wb.save(out)
        out.seek(0)
        return out
egen=ExcelGen()
EXCEL_PROMPT='''Kamu Excel Expert AI. Jawab dalam Bahasa Indonesia.
Jika diminta buat Excel, output JSON format:
{"action":"generate_excel","message":"deskripsi","excel_data":{"sheets":[{"name":"Sheet1","headers":["A","B"],"data":[["x",1]]}],"filename":"file.xlsx"}}
Jika hanya jawab pertanyaan:
{"action":"text_only","message":"jawaban"}
HANYA output JSON, tanpa teks lain.'''
OR_FREE={
    "llama":"meta-llama/llama-3.3-70b-instruct:free",
    "gemini":"google/gemini-2.0-flash-exp:free",
    "mistral":"mistralai/mistral-small-3.1-24b-instruct:free",
    "qwen":"qwen/qwen3-32b:free",
    "deepseek":"deepseek/deepseek-chat-v3-0324:free"
}
CF_MODELS={
    "llama":"@cf/meta/llama-3.1-8b-instruct",
    "mistral":"@cf/mistral/mistral-7b-instruct-v0.1",
    "qwen":"@cf/qwen/qwen1.5-14b-chat-awq"
}
MODEL_NAMES={
    "auto":"🚀 Auto",
    "groq":"⚡ Groq",
    "cerebras":"🧠 Cerebras",
    "sambanova":"🦣 SambaNova",
    "cohere":"🔷 Cohere",
    "cloudflare":"☁️ Cloudflare",
    "or_llama":"🦙 OR Llama",
    "or_gemini":"🔵 OR Gemini",
    "or_qwen":"🟣 OR Qwen",
    "or_deepseek":"🧪 OR DeepSeek",
    "pollinations":"🌺 Pollinations"
}
def call_groq(msgs):
    cl=get_groq()
    if not cl:return None
    try:
        r=cl.chat.completions.create(messages=msgs,model="llama-3.3-70b-versatile",temperature=0.2,max_tokens=4000)
        return r.choices[0].message.content
    except Exception as e:
        logger.error(f"Groq: {e}")
        return None
def call_openrouter(msgs,model_key="llama"):
    if not KEY_OPENROUTER:return None
    try:
        req=get_requests()
        model_id=OR_FREE.get(model_key,OR_FREE["llama"])
        r=req.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization":f"Bearer {KEY_OPENROUTER}","Content-Type":"application/json","HTTP-Referer":"https://github.com","X-Title":"Bot"},
            json={"model":model_id,"messages":msgs,"temperature":0.2,"max_tokens":4000},
            timeout=90
        )
        if r.status_code==200:
            data=r.json()
            if "choices" in data and data["choices"]:
                return data["choices"][0]["message"]["content"]
        logger.error(f"OR {model_key}: {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"OR: {e}")
        return None
def call_cerebras(msgs):
    if not KEY_CEREBRAS:return None
    try:
        req=get_requests()
        r=req.post(
            "https://api.cerebras.ai/v1/chat/completions",
            headers={"Authorization":f"Bearer {KEY_CEREBRAS}","Content-Type":"application/json"},
            json={"model":"llama-3.3-70b","messages":msgs,"temperature":0.2,"max_tokens":4000},
            timeout=30
        )
        if r.status_code==200:
            return r.json()["choices"][0]["message"]["content"]
        return None
    except Exception as e:
        logger.error(f"Cerebras: {e}")
        return None
def call_sambanova(msgs):
    if not KEY_SAMBANOVA:return None
    try:
        req=get_requests()
        r=req.post(
            "https://api.sambanova.ai/v1/chat/completions",
            headers={"Authorization":f"Bearer {KEY_SAMBANOVA}","Content-Type":"application/json"},
            json={"model":"Meta-Llama-3.3-70B-Instruct","messages":msgs,"temperature":0.2,"max_tokens":4000},
            timeout=60
        )
        if r.status_code==200:
            return r.json()["choices"][0]["message"]["content"]
        return None
    except Exception as e:
        logger.error(f"SN: {e}")
        return None
def call_cohere(msgs):
    if not KEY_COHERE:return None
    try:
        req=get_requests()
        preamble=""
        user_msg=""
        history=[]
        for m in msgs:
            if m["role"]=="system":preamble=m["content"]
            elif m["role"]=="user":
                if user_msg:history.append({"role":"USER","message":user_msg})
                user_msg=m["content"]
            elif m["role"]=="assistant":
                history.append({"role":"CHATBOT","message":m["content"]})
        payload={"model":"command-r-plus-08-2024","message":user_msg,"temperature":0.2}
        if preamble:payload["preamble"]=preamble
        if history:payload["chat_history"]=history
        r=req.post(
            "https://api.cohere.com/v1/chat",
            headers={"Authorization":f"Bearer {KEY_COHERE}","Content-Type":"application/json"},
            json=payload,timeout=60
        )
        if r.status_code==200:
            return r.json().get("text","")
        return None
    except Exception as e:
        logger.error(f"Cohere: {e}")
        return None
def call_cloudflare(msgs,model_key="llama"):
    """Cloudflare Workers AI"""
    if not CF_ACCOUNT_ID or not CF_API_TOKEN:
        logger.info("Cloudflare: No credentials")
        return None
    try:
        req=get_requests()
        model=CF_MODELS.get(model_key,CF_MODELS["llama"])
        url=f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{model}"
        cf_msgs=[]
        for m in msgs:
            if m["role"]=="system":
                cf_msgs.append({"role":"system","content":m["content"]})
            elif m["role"]=="user":
                cf_msgs.append({"role":"user","content":m["content"]})
            elif m["role"]=="assistant":
                cf_msgs.append({"role":"assistant","content":m["content"]})
        r=req.post(
            url,
            headers={"Authorization":f"Bearer {CF_API_TOKEN}","Content-Type":"application/json"},
            json={"messages":cf_msgs,"max_tokens":2000},
            timeout=60
        )
        if r.status_code==200:
            data=r.json()
            if data.get("success") and "result" in data:
                response=data["result"].get("response","")
                if response:
                    logger.info(f"Cloudflare ({model_key}): Success")
                    return response
        logger.error(f"Cloudflare: {r.status_code} - {r.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"Cloudflare: {e}")
        return None
def call_pollinations(prompt):
    try:
        req=get_requests()
        r=req.post(
            "https://text.pollinations.ai/",
            headers={"Content-Type":"application/json"},
            json={"messages":[{"role":"user","content":prompt}],"model":"openai","seed":random.randint(1,99999)},
            timeout=60
        )
        if r.ok and r.text and len(r.text)>5:
            return r.text
        return None
    except Exception as e:
        logger.error(f"Poll: {e}")
        return None
def call_model_direct(model,msgs,prompt):
    if model=="groq":return call_groq(msgs),"Groq"
    elif model=="cerebras":return call_cerebras(msgs),"Cerebras"
    elif model=="sambanova":return call_sambanova(msgs),"SambaNova"
    elif model=="cohere":return call_cohere(msgs),"Cohere"
    elif model=="cloudflare":return call_cloudflare(msgs),"Cloudflare"
    elif model=="pollinations":return call_pollinations(prompt),"Pollinations"
    elif model.startswith("or_"):
        mk=model[3:]
        return call_openrouter(msgs,mk),f"OR({mk})"
    return None,"none"
def ask_ai(prompt,uid=None,model=None):
    if model is None or model=="auto":
        if uid:model=db.get_user_model(uid)
        else:model="auto"
    if uid and model!="auto":
        db.set_user_model(uid,model)
    msgs=[{"role":"system","content":EXCEL_PROMPT}]
    if uid:
        history=mem.get_last_n(uid,6)
        if history:msgs.extend(history)
    msgs.append({"role":"user","content":prompt})
    result=None
    used_model="none"
    if model!="auto":
        result,used_model=call_model_direct(model,msgs,prompt)
        if not result:
            for fn,name in[(lambda:call_groq(msgs),"Groq"),(lambda:call_cerebras(msgs),"Cerebras"),(lambda:call_cloudflare(msgs),"Cloudflare"),(lambda:call_openrouter(msgs,"llama"),"OR")]:
                result=fn()
                if result:
                    used_model=f"{name}(fb)"
                    break
    else:
        for fn,name in[(lambda:call_groq(msgs),"Groq"),(lambda:call_cerebras(msgs),"Cerebras"),(lambda:call_cloudflare(msgs),"Cloudflare"),(lambda:call_openrouter(msgs,"llama"),"OR"),(lambda:call_sambanova(msgs),"SN"),(lambda:call_cohere(msgs),"Cohere"),(lambda:call_pollinations(prompt),"Poll")]:
            try:
                result=fn()
                if result:
                    used_model=name
                    break
            except:continue
    if not result:
        result='{"action":"text_only","message":"❌ AI tidak tersedia."}'
        used_model="none"
    if uid and result:
        mem.add(uid,"user",prompt[:1000])
        try:
            p=json.loads(result)
            mem.add(uid,"assistant",p.get("message",result)[:1000])
        except:
            mem.add(uid,"assistant",result[:1000])
    return result,used_model
def fix_json(t):
    t=t.strip()
    t=re.sub(r',(\s*[}\]])',r'\1',t)
    t=t.replace("'",'"')
    ob,cb=t.count('{'),t.count('}')
    if ob>cb:t+='}'*(ob-cb)
    return t
def parse_ai(resp):
    resp=resp.strip()
    if resp.startswith('```'):
        m=re.search(r'```(?:json)?\s*([\s\S]*?)\s*```',resp)
        if m:resp=m.group(1).strip()
    try:return json.loads(resp)
    except:pass
    try:
        m=re.search(r'(\{[\s\S]*\})',resp)
        if m:
            jt=fix_json(m.group(1))
            try:return json.loads(jt)
            except:pass
    except:pass
    return{"action":"text_only","message":resp}
def split_msg(t,lim=1800):
    """Split message untuk Discord dengan limit lebih aman"""
    if not t:return["(empty)"]
    t=str(t)
    if len(t)<=lim:return[t]
    chunks=[]
    while t:
        if len(t)<=lim:
            chunks.append(t)
            break
        split_at=t.rfind('\n',0,lim)
        if split_at<=0:split_at=t.rfind(' ',0,lim)
        if split_at<=0:split_at=lim
        chunks.append(t[:split_at])
        t=t[split_at:].lstrip()
    return chunks if chunks else["(empty)"]
def clean_for_discord(text):
    """Clean text untuk menghindari Discord error"""
    if not text:return "(no response)"
    text=str(text)[:3900]
    text=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]','',text)
    return text if text.strip() else "(empty response)"
def get_roblox_headers():
    return{"User-Agent":random.choice(UA_LIST),"Roblox-Place-Id":"2753915549","Accept":"*/*"}
def valid_url(u):
    return u.startswith(("http://","https://"))and"localhost"not in u.lower()
def extract_links(html):
    links=set()
    for p in[r'https?://[^\s"\'<>]+\.lua',r'https?://[^\s"\'<>]*(?:raw|script|paste)[^\s"\'<>]*']:
        links.update(re.findall(p,html,re.I))
    return list(links)[:5]
async def process_ai(prompt,uid,gid,attachments=None,model=None):
    parts=[prompt]
    if attachments:
        for a in attachments:
            fc,ft,_=await freader.read(a)
            parts.append(f"\n[FILE:{a.filename}]\n{fc[:3000]}")
    resp,used=ask_ai('\n'.join(parts),uid,model)
    parsed=parse_ai(resp)
    msg=parsed.get("message","")
    db.log(uid,gid,"ai",prompt[:300],msg[:300]if msg else"")
    db.stat("ai",uid)
    return parsed,resp,used
async def process_dump(url,mode="auto"):
    if not valid_url(url):return None,"",""
    curl=get_curl()
    browsers=["chrome110","chrome120"]if mode=="aggressive"else["chrome110"]
    for br in browsers:
        try:
            ua=random.choice(UA_LIST)
            r=curl.get(url,impersonate=br,headers={**get_roblox_headers(),"User-Agent":ua},timeout=20)
            return r.text,ua,br
        except:continue
    return None,"",""
@bot.event
async def on_ready():
    logger.info(f'🔥 {bot.user}|{len(bot.guilds)}g')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching,name=f"{PREFIX}help"))
    try:await bot.tree.sync()
    except:pass
@bot.event
async def on_message(msg):
    if msg.author.bot:return
    if bot.user.mentioned_in(msg)and not msg.mention_everyone:
        content=msg.content.replace(f'<@{bot.user.id}>','').replace(f'<@!{bot.user.id}>','').strip()
        if content:
            if db.banned(msg.author.id):return await msg.reply("🚫")
            ok,r=rl.ok(msg.author.id,"m",5)
            if not ok:return await msg.reply(f"⏳ {r:.0f}s")
            async with msg.channel.typing():
                try:
                    att=list(msg.attachments)if msg.attachments else None
                    parsed,resp,used=await process_ai(content,msg.author.id,msg.guild.id if msg.guild else None,att,db.get_user_model(msg.author.id))
                    action=parsed.get("action","text_only")
                    m=clean_for_discord(parsed.get("message","")or resp)
                    if action=="generate_excel":
                        ed=parsed.get("excel_data",{})
                        fn=ed.get("filename","out.xlsx")
                        ef=egen.generate(ed)
                        await msg.reply(f"📊 **{used}**",file=discord.File(ef,fn))
                    else:
                        for c in split_msg(m):
                            await msg.reply(f"🤖 **{used}**\n{c}")
                            break
                except Exception as e:
                    await msg.reply(f"❌ `{str(e)[:100]}`")
        else:
            await msg.reply(f"👋 Model: `{db.get_user_model(msg.author.id)}`")
        return
    await bot.process_commands(msg)
@bot.command(name="model",aliases=["m"])
async def cmd_model(ctx,m:str=None):
    valid=list(MODEL_NAMES.keys())
    if not m:
        cm=db.get_user_model(ctx.author.id)
        return await ctx.reply(f"🤖 Model: **{MODEL_NAMES.get(cm,cm)}**\n\nAvailable: `{', '.join(valid)}`")
    m=m.lower()
    if m not in valid:return await ctx.reply(f"❌ Invalid. Use: `{', '.join(valid)}`")
    db.set_user_model(ctx.author.id,m)
    await ctx.reply(f"✅ Model: **{MODEL_NAMES.get(m,m)}**")
@bot.command(name="ai",aliases=["ask"])
async def cmd_ai(ctx,*,prompt:str=None):
    if db.banned(ctx.author.id):return
    ok,r=rl.ok(ctx.author.id,"ai",8)
    if not ok:return await ctx.reply(f"⏳ {r:.0f}s")
    if not prompt and not ctx.message.attachments:return await ctx.reply(f"❌ `{PREFIX}ai <prompt>`")
    async with ctx.typing():
        try:
            att=list(ctx.message.attachments)if ctx.message.attachments else None
            parsed,resp,used=await process_ai(prompt or"Analyze",ctx.author.id,ctx.guild.id if ctx.guild else None,att,db.get_user_model(ctx.author.id))
            action=parsed.get("action","text_only")
            m=clean_for_discord(parsed.get("message","")or resp)
            if action=="generate_excel":
                ed=parsed.get("excel_data",{})
                fn=ed.get("filename","out.xlsx")
                ef=egen.generate(ed)
                await ctx.reply(f"📊 **{used}**",file=discord.File(ef,fn))
            else:
                chunks=split_msg(m)
                await ctx.reply(f"🤖 **{used}**\n{chunks[0]}")
                for c in chunks[1:]:await ctx.send(c)
        except Exception as e:
            await ctx.reply(f"❌ `{str(e)[:100]}`")
@bot.command(name="dump")
async def cmd_dump(ctx,url:str=None,mode:str="auto"):
    if not url:return await ctx.reply(f"❌ `{PREFIX}dump <url>`")
    ok,r=rl.ok(ctx.author.id,"d",8)
    if not ok:return await ctx.reply(f"⏳ {r:.0f}s")
    async with ctx.typing():
        try:
            content,ua,br=await process_dump(url,mode)
            if not content:return await ctx.reply("💀 Failed")
            ext="lua"
            if"<!DOCTYPE"in content[:300]:ext="html"
            elif content.strip().startswith("{"):ext="json"
            links=extract_links(content)if ext=="html"else[]
            e=discord.Embed(title="🔓 Dump",color=0x00FF00 if ext=="lua"else 0xFFFF00)
            e.add_field(name="Size",value=f"`{len(content):,}b`")
            e.add_field(name="Type",value=f"`.{ext}`")
            if links:e.add_field(name="Links",value="\n".join([f"`{l[:40]}`"for l in links]),inline=False)
            db.stat("dump",ctx.author.id)
            await ctx.reply(embed=e,file=discord.File(io.BytesIO(content.encode()),f"dump.{ext}"))
        except Exception as e:
            await ctx.reply(f"💀 `{str(e)[:100]}`")
@bot.command(name="ping")
async def cmd_ping(ctx):
    cm=db.get_user_model(ctx.author.id)
    cf="✅"if CF_ACCOUNT_ID and CF_API_TOKEN else"❌"
    await ctx.reply(f"🏓 `{round(bot.latency*1000)}ms` | Model: `{cm}` | CF: {cf} | Mem: `{len(mem.get(ctx.author.id))}`")
@bot.command(name="help",aliases=["h"])
async def cmd_help(ctx):
    cm=db.get_user_model(ctx.author.id)
    e=discord.Embed(title="📚 Bot Help",description=f"Model: **{MODEL_NAMES.get(cm,cm)}**",color=0x3498DB)
    e.add_field(name="AI",value=f"`{PREFIX}ai <prompt>`\n`{PREFIX}model <name>`\n`{PREFIX}clear`",inline=True)
    e.add_field(name="Dump",value=f"`{PREFIX}dump <url>`",inline=True)
    e.add_field(name="Models",value="`auto` `groq` `cerebras` `cloudflare` `sambanova` `cohere`\n`or_llama` `or_gemini` `or_qwen` `or_deepseek`",inline=False)
    await ctx.reply(embed=e)
@bot.command(name="clear")
async def cmd_clear(ctx):
    mem.clear(ctx.author.id)
    await ctx.reply("🧹 Cleared!")
@bot.command(name="history")
async def cmd_hist(ctx):
    h=mem.get_last_n(ctx.author.id,5)
    if not h:return await ctx.reply("📭 Empty")
    txt="\n".join([f"{'👤'if m['role']=='user'else'🤖'} {m['content'][:50]}..."for m in h])
    await ctx.reply(f"📜 **Memory:**\n{txt}")
@bot.command(name="testai")
@commands.is_owner()
async def cmd_test(ctx):
    async with ctx.typing():
        results=[]
        test=[{"role":"user","content":"Say: OK"}]
        for n,f in[("Groq",lambda:call_groq(test)),("Cerebras",lambda:call_cerebras(test)),("Cloudflare",lambda:call_cloudflare(test)),("SambaNova",lambda:call_sambanova(test)),("OR-Llama",lambda:call_openrouter(test,"llama")),("OR-Gemini",lambda:call_openrouter(test,"gemini")),("Cohere",lambda:call_cohere(test)),("Poll",lambda:call_pollinations("Say OK"))]:
            try:
                r=f()
                s="✅"if r else"❌"
                t=clean_for_discord(r[:25])if r else"Fail"
                results.append(f"{s} **{n}**: {t}")
            except Exception as ex:
                results.append(f"❌ **{n}**: {str(ex)[:15]}")
        await ctx.reply("\n".join(results))
@bot.command(name="stats")
@commands.is_owner()
async def cmd_stats(ctx):
    st=db.get_stats()
    usage="\n".join([f"`{c}`: {n}x"for c,n in st[:5]])if st else"No data"
    await ctx.reply(f"📊 **Stats**\nServers: `{len(bot.guilds)}`\n{usage}")
@bot.tree.command(name="model",description="Set AI model")
@app_commands.choices(model=[app_commands.Choice(name=v,value=k)for k,v in MODEL_NAMES.items()])
async def sl_model(i:discord.Interaction,model:str=None):
    if model:
        db.set_user_model(i.user.id,model)
        await i.response.send_message(f"✅ Model: **{MODEL_NAMES.get(model,model)}**",ephemeral=True)
    else:
        await i.response.send_message(f"🤖 Model: **{MODEL_NAMES.get(db.get_user_model(i.user.id))}**",ephemeral=True)
@bot.tree.command(name="ai",description="Ask AI")
@rate(8)
@noban()
async def sl_ai(i:discord.Interaction,prompt:str,file:discord.Attachment=None):
    await i.response.defer()
    try:
        att=[file]if file else None
        parsed,resp,used=await process_ai(prompt,i.user.id,i.guild_id,att,db.get_user_model(i.user.id))
        m=clean_for_discord(parsed.get("message","")or resp)
        if parsed.get("action")=="generate_excel":
            ed=parsed.get("excel_data",{})
            ef=egen.generate(ed)
            await i.followup.send(f"📊 **{used}**",file=discord.File(ef,ed.get("filename","out.xlsx")))
        else:
            chunks=split_msg(m)
            await i.followup.send(f"🤖 **{used}**\n{chunks[0]}")
            for c in chunks[1:]:await i.channel.send(c)
    except Exception as e:
        await i.followup.send(f"❌ `{str(e)[:100]}`")
@bot.tree.command(name="dump",description="Dump script")
@rate(8)
@noban()
async def sl_dump(i:discord.Interaction,url:str):
    await i.response.defer()
    try:
        content,_,_=await process_dump(url)
        if not content:return await i.followup.send("💀")
        ext="lua"
        if"<!DOCTYPE"in content[:300]:ext="html"
        db.stat("dump",i.user.id)
        await i.followup.send(f"🔓 `{len(content):,}b`",file=discord.File(io.BytesIO(content.encode()),f"dump.{ext}"))
    except Exception as e:
        await i.followup.send(f"💀 `{str(e)[:50]}`")
@bot.tree.command(name="clear",description="Clear memory")
async def sl_clear(i:discord.Interaction):
    mem.clear(i.user.id)
    await i.response.send_message("🧹",ephemeral=True)
@bot.tree.command(name="ping",description="Ping")
async def sl_ping(i:discord.Interaction):
    await i.response.send_message(f"🏓 `{round(bot.latency*1000)}ms`")
@bot.tree.command(name="testai",description="Test AI")
@owner()
async def sl_test(i:discord.Interaction):
    await i.response.defer()
    test=[{"role":"user","content":"OK"}]
    r=[]
    for n,f in[("Groq",lambda:call_groq(test)),("Cerebras",lambda:call_cerebras(test)),("CF",lambda:call_cloudflare(test)),("OR",lambda:call_openrouter(test,"llama"))]:
        try:
            x=f()
            r.append(f"{'✅'if x else'❌'} {n}")
        except:r.append(f"❌ {n}")
    await i.followup.send(" | ".join(r))
@bot.tree.command(name="reload",description="Sync")
@owner()
async def sl_reload(i:discord.Interaction):
    await i.response.defer()
    try:
        s=await bot.tree.sync()
        await i.followup.send(f"✅ {len(s)}")
    except Exception as e:
        await i.followup.send(f"❌ {e}")
if __name__=="__main__":
    keep_alive()
    print("🚀 Starting...")
    cf="✅"if CF_ACCOUNT_ID and CF_API_TOKEN else"❌"
    print(f"📦 Groq{'✅'if KEY_GROQ else'❌'} Cerebras{'✅'if KEY_CEREBRAS else'❌'} CF{cf} OR{'✅'if KEY_OPENROUTER else'❌'}")
    try:bot.run(DISCORD_TOKEN,log_handler=None)
    except Exception as e:print(f"❌ {e}")
