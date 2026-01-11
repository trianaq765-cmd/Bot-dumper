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
OWNER_IDS=[int(x)for x in os.getenv("OWNER_IDS","0").split(",")if x.isdigit()]
PREFIX=os.getenv("BOT_PREFIX","!")
if not DISCORD_TOKEN:
    print("❌ NO TOKEN!")
    exit(1)
intents=discord.Intents.default()
intents.message_content=True
bot=commands.Bot(command_prefix=PREFIX,intents=intents,help_command=None)
UA_LIST=["Roblox/WinInet","Synapse-X/2.0","Sentinel/3.0","Krnl/1.0","KRNL/2.0","Fluxus/1.0","ScriptWare/2.0","Electron/1.0","Hydrogen/1.0","Codex/1.0","Arceus-X/2.0","Delta/1.0","Trigon/3.0","Evon/1.0","JJSploit/7.0","Comet/1.0","Nihon/1.0","Celery/1.0","Vega-X/1.0","Oxygen-U/1.0"]
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
    def add(self,uid,role,txt):
        now=time.time()
        self.data[uid]=[m for m in self.data[uid]if now-m.ts<1800]
        self.data[uid].append(Msg(role,txt,now))
        if len(self.data[uid])>10:
            self.data[uid]=self.data[uid][-10:]
    def get(self,uid):
        return[{"role":m.role,"content":m.content}for m in self.data[uid]]
    def clear(self,uid):
        self.data[uid]=[]
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
            result.append(f"=== SHEET: {name} ===\nSize: {len(df)}x{len(df.columns)}\nColumns: {','.join(map(str,df.columns.tolist()))}\n{df.to_string(max_rows=50)}")
        return '\n'.join(result),"excel",meta
    @staticmethod
    def _csv(content):
        pd=get_pandas()
        df=pd.read_csv(io.StringIO(content.decode('utf-8',errors='ignore')))
        return f"CSV {len(df)}x{len(df.columns)}\n{df.to_string(max_rows=50)}","csv",{"rows":len(df)}
    @staticmethod
    def _json(content):
        data=json.loads(content.decode('utf-8',errors='ignore'))
        return json.dumps(data,indent=2,ensure_ascii=False)[:8000],"json",{"type":type(data).__name__}
    @staticmethod
    def _text(content,fn):
        txt=content.decode('utf-8',errors='ignore')
        return txt[:8000],fn.split('.')[-1]if'.'in fn else'txt',{}
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
            formulas=sh.get("formulas",{})
            styling=sh.get("styling",{})
            hfill=PatternFill(start_color=styling.get("header_color","4472C4"),end_color=styling.get("header_color","4472C4"),fill_type="solid")
            hfont=Font(bold=True,color=styling.get("header_font_color","FFFFFF"))
            border=Border(left=Side(style='thin'),right=Side(style='thin'),top=Side(style='thin'),bottom=Side(style='thin'))
            for ci,h in enumerate(headers,1):
                c=ws.cell(row=1,column=ci,value=str(h))
                c.font=hfont
                c.fill=hfill
                c.border=border
                c.alignment=Alignment(horizontal='center')
            for ri,row in enumerate(rows,2):
                if not isinstance(row,(list,tuple)):
                    row=[row]
                for ci,val in enumerate(row,1):
                    c=ws.cell(row=ri,column=ci,value=val)
                    c.border=border
                    if isinstance(val,(int,float))and abs(val)>=1000:
                        c.number_format='#,##0'
            for ref,f in formulas.items():
                try:
                    ws[ref]=f
                    ws[ref].border=border
                except:
                    pass
            summary=sh.get("summary",{})
            if summary and rows:
                lr=len(rows)+1
                sr=lr+1
                for cl,f in summary.get("formulas",{}).items():
                    try:
                        ws[f"{cl}{sr}"]=str(f).replace("{last}",str(lr))
                        ws[f"{cl}{sr}"].font=Font(bold=True)
                        ws[f"{cl}{sr}"].border=border
                    except:
                        pass
            for ci in range(1,max(len(headers),1)+1):
                cl=get_column_letter(ci)
                ml=len(str(headers[ci-1]))if ci<=len(headers)else 10
                for r in rows:
                    if isinstance(r,(list,tuple))and ci<=len(r):
                        ml=max(ml,len(str(r[ci-1])))
                ws.column_dimensions[cl].width=min(max(ml+5,15),60)
            ws.freeze_panes='A2'
        out=io.BytesIO()
        wb.save(out)
        out.seek(0)
        return out
egen=ExcelGen()
EXCEL_PROMPT='''KAMU EXCEL EXPERT AI. ATURAN KETAT:
1. HANYA keluarkan JSON valid, TANPA teks lain sebelum atau sesudah JSON
2. Angka harus number (15000), bukan string ("15000")
3. Teks harus LENGKAP, jangan dipotong

FORMAT WAJIB:
Jika diminta buat/generate Excel:
{"action":"generate_excel","message":"deskripsi singkat","excel_data":{"sheets":[{"name":"Sheet1","headers":["Kolom1","Kolom2","Total"],"data":[["Item1",100,200],["Item2",150,250]],"formulas":{"C2":"=A2*B2","C3":"=A3*B3"},"styling":{"header_color":"4472C4"},"summary":{"formulas":{"B":"=SUM(B2:B{last})","C":"=SUM(C2:C{last})"}}}],"filename":"output.xlsx"}}

Jika hanya jawab pertanyaan:
{"action":"text_only","message":"jawaban lengkap disini"}

Jawab dalam Bahasa Indonesia. JANGAN tambahkan teks apapun selain JSON.'''
OR_FREE={
    "llama":"meta-llama/llama-3.3-70b-instruct:free",
    "gemini":"google/gemini-2.0-flash-exp:free",
    "mistral":"mistralai/mistral-7b-instruct:free",
    "qwen":"qwen/qwen-2-7b-instruct:free",
    "deepseek":"deepseek/deepseek-r1:free"
}
def call_groq(msgs):
    cl=get_groq()
    if not cl:
        return None
    try:
        r=cl.chat.completions.create(messages=msgs,model="llama-3.3-70b-versatile",temperature=0.2,max_tokens=8000)
        return r.choices[0].message.content
    except Exception as e:
        logger.error(f"Groq: {e}")
        return None
def call_openrouter(msgs,model_key="llama"):
    if not KEY_OPENROUTER:
        return None
    try:
        req=get_requests()
        model_id=OR_FREE.get(model_key,"meta-llama/llama-3.3-70b-instruct:free")
        r=req.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization":f"Bearer {KEY_OPENROUTER}",
                "Content-Type":"application/json",
                "HTTP-Referer":"https://github.com",
                "X-Title":"ExcelBot"
            },
            json={"model":model_id,"messages":msgs,"temperature":0.2,"max_tokens":8000},
            timeout=60
        )
        if r.status_code==200:
            data=r.json()
            if "choices" in data and len(data["choices"])>0:
                return data["choices"][0]["message"]["content"]
        logger.error(f"OpenRouter: HTTP {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"OpenRouter: {e}")
        return None
def call_cerebras(msgs):
    if not KEY_CEREBRAS:
        return None
    try:
        req=get_requests()
        r=req.post(
            "https://api.cerebras.ai/v1/chat/completions",
            headers={"Authorization":f"Bearer {KEY_CEREBRAS}","Content-Type":"application/json"},
            json={"model":"llama-3.3-70b","messages":msgs,"temperature":0.2,"max_tokens":8000},
            timeout=30
        )
        if r.status_code==200:
            return r.json()["choices"][0]["message"]["content"]
        logger.error(f"Cerebras: HTTP {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"Cerebras: {e}")
        return None
def call_sambanova(msgs):
    if not KEY_SAMBANOVA:
        return None
    try:
        req=get_requests()
        r=req.post(
            "https://api.sambanova.ai/v1/chat/completions",
            headers={"Authorization":f"Bearer {KEY_SAMBANOVA}","Content-Type":"application/json"},
            json={"model":"Meta-Llama-3.3-70B-Instruct","messages":msgs,"temperature":0.2,"max_tokens":8000},
            timeout=60
        )
        if r.status_code==200:
            return r.json()["choices"][0]["message"]["content"]
        logger.error(f"SambaNova: HTTP {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"SambaNova: {e}")
        return None
def call_cohere(msgs):
    if not KEY_COHERE:
        return None
    try:
        req=get_requests()
        chat_history=[]
        preamble=""
        user_msg=""
        for m in msgs:
            if m["role"]=="system":
                preamble=m["content"]
            elif m["role"]=="user":
                if user_msg:
                    chat_history.append({"role":"USER","message":user_msg})
                user_msg=m["content"]
            elif m["role"]=="assistant":
                chat_history.append({"role":"CHATBOT","message":m["content"]})
        payload={"model":"command-r-plus-08-2024","message":user_msg,"temperature":0.2,"max_tokens":4000}
        if preamble:
            payload["preamble"]=preamble
        if chat_history:
            payload["chat_history"]=chat_history
        r=req.post(
            "https://api.cohere.com/v1/chat",
            headers={"Authorization":f"Bearer {KEY_COHERE}","Content-Type":"application/json"},
            json=payload,
            timeout=60
        )
        if r.status_code==200:
            return r.json().get("text","")
        logger.error(f"Cohere: HTTP {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"Cohere: {e}")
        return None
def call_pollinations(prompt):
    try:
        req=get_requests()
        r=req.post(
            "https://text.pollinations.ai/",
            headers={"Content-Type":"application/json"},
            json={
                "messages":[{"role":"system","content":"You are a helpful assistant."},{"role":"user","content":prompt}],
                "model":"openai",
                "seed":random.randint(1,99999)
            },
            timeout=60
        )
        if r.ok and r.text and len(r.text)>5 and "<!DOCTYPE" not in r.text[:100]:
            return r.text
        return None
    except Exception as e:
        logger.error(f"Pollinations: {e}")
        return None
def ask_ai(prompt,uid=None,model="auto"):
    msgs=[{"role":"system","content":EXCEL_PROMPT},{"role":"user","content":prompt}]
    if uid:
        history=mem.get(uid)
        if history:
            msgs=[{"role":"system","content":EXCEL_PROMPT}]+history+[{"role":"user","content":prompt}]
    result=None
    used_model="none"
    if model=="groq":
        result=call_groq(msgs)
        used_model="Groq" if result else "none"
    elif model=="cerebras":
        result=call_cerebras(msgs)
        used_model="Cerebras" if result else "none"
    elif model=="sambanova":
        result=call_sambanova(msgs)
        used_model="SambaNova" if result else "none"
    elif model=="cohere":
        result=call_cohere(msgs)
        used_model="Cohere" if result else "none"
    elif model=="pollinations":
        result=call_pollinations(prompt)
        used_model="Pollinations" if result else "none"
    elif model.startswith("or_"):
        mk=model[3:]
        result=call_openrouter(msgs,mk)
        used_model=f"OpenRouter({mk})" if result else "none"
    else:
        for fn,name in [
            (lambda:call_groq(msgs),"Groq"),
            (lambda:call_cerebras(msgs),"Cerebras"),
            (lambda:call_openrouter(msgs,"llama"),"OpenRouter"),
            (lambda:call_sambanova(msgs),"SambaNova"),
            (lambda:call_cohere(msgs),"Cohere"),
            (lambda:call_pollinations(prompt),"Pollinations")
        ]:
            try:
                result=fn()
                if result:
                    used_model=name
                    break
            except:
                continue
    if not result and model!="auto":
        result=call_groq(msgs)
        if result:
            used_model="Groq(fallback)"
    if not result:
        result='{"action":"text_only","message":"❌ Semua AI tidak tersedia."}'
        used_model="none"
    if uid and result:
        mem.add(uid,"user",prompt)
        mem.add(uid,"assistant",result)
    return result,used_model
def fix_json(t):
    t=t.strip()
    t=re.sub(r',(\s*[}\]])',r'\1',t)
    t=t.replace("'",'"')
    ob,cb=t.count('{'),t.count('}')
    if ob>cb:
        t+='}'*(ob-cb)
    osb,csb=t.count('['),t.count(']')
    if osb>csb:
        t+=']'*(osb-csb)
    return t
def parse_ai(resp):
    resp=resp.strip()
    if resp.startswith('```'):
        m=re.search(r'```(?:json)?\s*([\s\S]*?)\s*```',resp)
        if m:
            resp=m.group(1).strip()
    try:
        return json.loads(resp)
    except:
        pass
    try:
        m=re.search(r'(\{[\s\S]*\})',resp)
        if m:
            jt=m.group(1)
            try:
                return json.loads(jt)
            except:
                jt=fix_json(jt)
                try:
                    return json.loads(jt)
                except:
                    pass
    except:
        pass
    return{"action":"text_only","message":resp}
def split_msg(t,lim=1900):
    if len(t)<=lim:
        return[t]
    ch=[]
    cur=""
    for l in t.split('\n'):
        if len(cur)+len(l)+1>lim:
            if cur:
                ch.append(cur)
            cur=l
        else:
            cur+=('\n'if cur else'')+l
    if cur:
        ch.append(cur)
    return ch or[t[:lim]]
def get_roblox_headers():
    return{
        "User-Agent":random.choice(UA_LIST),
        "Roblox-Place-Id":"2753915549",
        "Roblox-Game-Id":"9876543210",
        "Accept":"*/*",
        "Connection":"keep-alive"
    }
def valid_url(u):
    return u.startswith(("http://","https://"))and not any(x in u.lower()for x in["localhost","127.0.0.1","0.0.0.0"])
def extract_potential_links(html):
    patterns=[
        r'https?://[^\s"\'<>\)]+\.lua',
        r'https?://[^\s"\'<>\)]*(?:raw|get|api|script|paste)[^\s"\'<>\)]*',
        r'https?://(?:pastebin\.com|raw\.githubusercontent\.com)[^\s"\'<>\)]+'
    ]
    links=set()
    for p in patterns:
        for m in re.findall(p,html,re.IGNORECASE):
            if m:
                links.add(m)
    return[l for l in links if l.startswith("http")]
async def process_ai_request(prompt,uid,gid,attachments=None,model="auto"):
    parts=[prompt]
    if attachments:
        for att in attachments:
            fc,ft,meta=await freader.read(att)
            parts.append(f"\n\n=== FILE: {att.filename} ===\n{fc}")
    full_prompt='\n'.join(parts)
    resp,used=ask_ai(full_prompt,uid,model)
    parsed=parse_ai(resp)
    action=parsed.get("action","text_only")
    msg=parsed.get("message","")
    db.log(uid,gid,"ai",prompt[:500],msg[:500]if msg else"")
    db.stat("ai",uid)
    return parsed,resp,used
async def process_dump_request(url,mode="auto"):
    if not valid_url(url):
        return None,"❌ URL tidak valid!",None,[]
    curl=get_curl()
    content=None
    method_used=""
    chosen_ua=""
    attempts=[]
    browsers=["chrome110","chrome116","chrome120","edge99","safari15_5"]if mode=="aggressive"else["chrome110"]
    if mode=="stealth":
        browsers=["safari15_5","chrome110"]
        time.sleep(random.uniform(0.5,1.5))
    for browser in browsers:
        chosen_ua=random.choice(UA_LIST)
        hdrs=get_roblox_headers()
        hdrs["User-Agent"]=chosen_ua
        try:
            r=curl.get(url,impersonate=browser,headers=hdrs,timeout=20)
            content=r.text
            method_used=f"{browser}"
            attempts.append(f"✅ {browser}")
            if"<!DOCTYPE"not in content[:200]:
                break
            attempts[-1]=f"⚠️ {browser}(HTML)"
        except Exception as ex:
            attempts.append(f"❌ {browser}")
    return content,chosen_ua,method_used,attempts
@bot.event
async def on_ready():
    logger.info(f'🔥 {bot.user}|{len(bot.guilds)} guilds')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching,name=f"{PREFIX}help atau @mention"))
    try:
        await bot.tree.sync()
        logger.info("✅ Synced")
    except Exception as e:
        logger.error(f"Sync:{e}")
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if bot.user.mentioned_in(message) and not message.mention_everyone:
        content=message.content.replace(f'<@{bot.user.id}>','').replace(f'<@!{bot.user.id}>','').strip()
        if content:
            if db.banned(message.author.id):
                await message.reply("🚫 Kamu di-blacklist!")
                return
            ok,remaining=rl.ok(message.author.id,"mention",5)
            if not ok:
                await message.reply(f"⏳ Tunggu **{remaining:.1f}s**")
                return
            async with message.channel.typing():
                try:
                    attachments=list(message.attachments) if message.attachments else None
                    parsed,resp,used=await process_ai_request(
                        content,
                        message.author.id,
                        message.guild.id if message.guild else None,
                        attachments
                    )
                    action=parsed.get("action","text_only")
                    msg=parsed.get("message","")
                    if action=="generate_excel":
                        ed=parsed.get("excel_data",{})
                        fn=ed.get("filename","output.xlsx")
                        if not fn.endswith('.xlsx'):
                            fn+='.xlsx'
                        ef=egen.generate(ed)
                        e=discord.Embed(title="📊 Excel Created!",color=0x217346)
                        e.add_field(name="File",value=f"`{fn}`")
                        e.add_field(name="Model",value=f"`{used}`")
                        if msg:
                            e.add_field(name="Info",value=msg[:300],inline=False)
                        await message.reply(embed=e,file=discord.File(ef,fn))
                    else:
                        if not msg:
                            msg=resp
                        chunks=split_msg(msg)
                        await message.reply(f"**🤖 {used}:**\n{chunks[0]}")
                        for c in chunks[1:]:
                            await message.channel.send(c)
                except Exception as ex:
                    await message.reply(f"❌ Error: `{ex}`")
        else:
            await message.reply(f"👋 Hai! Ketik pertanyaan setelah mention saya.\nContoh: `@{bot.user.name} apa itu rumus VLOOKUP?`")
        return
    await bot.process_commands(message)
@bot.tree.error
async def on_error(i,e):
    try:
        await i.response.send_message(f"❌ {str(e)[:100]}",ephemeral=True)
    except:
        pass
@bot.command(name="ai",aliases=["ask","chat","tanya"])
async def prefix_ai(ctx,*,prompt:str=None):
    if db.banned(ctx.author.id):
        return await ctx.reply("🚫 Kamu di-blacklist!")
    ok,remaining=rl.ok(ctx.author.id,"ai",10)
    if not ok:
        return await ctx.reply(f"⏳ Tunggu **{remaining:.1f}s**")
    if not prompt and not ctx.message.attachments:
        return await ctx.reply(f"❌ Gunakan: `{PREFIX}ai <pertanyaan>`")
    async with ctx.typing():
        try:
            attachments=list(ctx.message.attachments) if ctx.message.attachments else None
            parsed,resp,used=await process_ai_request(
                prompt or "Analisis file ini",
                ctx.author.id,
                ctx.guild.id if ctx.guild else None,
                attachments
            )
            action=parsed.get("action","text_only")
            msg=parsed.get("message","")
            if action=="generate_excel":
                ed=parsed.get("excel_data",{})
                fn=ed.get("filename","output.xlsx")
                if not fn.endswith('.xlsx'):
                    fn+='.xlsx'
                ef=egen.generate(ed)
                e=discord.Embed(title="📊 Excel Created!",color=0x217346)
                e.add_field(name="File",value=f"`{fn}`")
                e.add_field(name="Model",value=f"`{used}`")
                if msg:
                    e.add_field(name="Info",value=msg[:300],inline=False)
                await ctx.reply(embed=e,file=discord.File(ef,fn))
            else:
                if not msg:
                    msg=resp
                chunks=split_msg(msg)
                await ctx.reply(f"**🤖 {used}:**\n{chunks[0]}")
                for c in chunks[1:]:
                    await ctx.send(c)
        except Exception as ex:
            await ctx.reply(f"❌ Error: `{ex}`")
@bot.command(name="dump",aliases=["get","download"])
async def prefix_dump(ctx,url:str=None,mode:str="auto"):
    if db.banned(ctx.author.id):
        return await ctx.reply("🚫 Kamu di-blacklist!")
    ok,remaining=rl.ok(ctx.author.id,"dump",8)
    if not ok:
        return await ctx.reply(f"⏳ Tunggu **{remaining:.1f}s**")
    if not url:
        return await ctx.reply(f"❌ Gunakan: `{PREFIX}dump <url> [mode]`")
    async with ctx.typing():
        try:
            content,chosen_ua,method_used,attempts=await process_dump_request(url,mode)
            if not content:
                return await ctx.reply("💀 Gagal dump!")
            ext="lua"
            status="✅ **BERHASIL!**"
            color=0x00FF00
            potential_links=[]
            if"<!DOCTYPE"in content[:500]:
                ext="html"
                color=0xFFFF00
                potential_links=extract_potential_links(content)
                status=f"⚠️ **HTML** - {len(potential_links)} link" if potential_links else "❌ **HTML/JS Challenge**"
            elif content.strip().startswith("{"):
                ext="json"
                status="📋 **JSON**"
            e=discord.Embed(title="🔓 Dump",description=status,color=color)
            e.add_field(name="Size",value=f"`{len(content):,}b`")
            e.add_field(name="Type",value=f"`.{ext}`")
            e.add_field(name="UA",value=f"`{chosen_ua[:15]}...`")
            if potential_links:
                e.add_field(name="🔗 Links",value="\n".join([f"`{l[:50]}`"for l in potential_links[:3]]),inline=False)
            db.stat("dump",ctx.author.id)
            await ctx.reply(embed=e,file=discord.File(io.BytesIO(content.encode()),f"dump.{ext}"))
        except Exception as ex:
            await ctx.reply(f"💀 Error: `{ex}`")
@bot.command(name="ping")
async def prefix_ping(ctx):
    e=discord.Embed(title="🏓 Pong!",color=0x00FF00)
    e.add_field(name="Latency",value=f"`{round(bot.latency*1000)}ms`")
    e.add_field(name="Servers",value=f"`{len(bot.guilds)}`")
    await ctx.reply(embed=e)
@bot.command(name="help",aliases=["h"])
async def prefix_help(ctx):
    e=discord.Embed(title="📚 Excel AI Bot",description="Multi-AI Bot",color=0x217346)
    e.add_field(name="💬 Cara Pakai",value=f"• **Mention**: @{bot.user.name} pertanyaan\n• **Prefix**: `{PREFIX}ai pertanyaan`\n• **Slash**: `/ai pertanyaan`",inline=False)
    e.add_field(name=f"🤖 {PREFIX}ai <prompt>",value="Tanya AI / Buat Excel",inline=False)
    e.add_field(name=f"🔓 {PREFIX}dump <url>",value="Download script",inline=False)
    e.add_field(name=f"🧹 {PREFIX}clear",value="Hapus memory",inline=False)
    await ctx.reply(embed=e)
@bot.command(name="clear",aliases=["reset"])
async def prefix_clear(ctx):
    mem.clear(ctx.author.id)
    await ctx.reply("🧹 Memory dihapus!")
@bot.command(name="history",aliases=["hist"])
async def prefix_history(ctx,limit:int=5):
    h=db.hist(ctx.author.id,min(limit,10))
    if not h:
        return await ctx.reply("📭 History kosong")
    e=discord.Embed(title="📜 History",color=0x3498DB)
    for idx,(p,r)in enumerate(h,1):
        e.add_field(name=f"{idx}. {p[:30]}...",value=f"```{r[:50]}...```",inline=False)
    await ctx.reply(embed=e)
@bot.command(name="testai")
@commands.is_owner()
async def prefix_testai(ctx):
    async with ctx.typing():
        results=[]
        test_msgs=[{"role":"user","content":"Say: OK"}]
        providers=[
            ("Groq",lambda:call_groq(test_msgs)),
            ("Cerebras",lambda:call_cerebras(test_msgs)),
            ("SambaNova",lambda:call_sambanova(test_msgs)),
            ("Cohere",lambda:call_cohere(test_msgs)),
            ("OpenRouter",lambda:call_openrouter(test_msgs,"llama")),
            ("Pollinations",lambda:call_pollinations("Say: OK"))
        ]
        for name,fn in providers:
            try:
                r=fn()
                status="✅" if r else "❌"
                text=r[:40].strip().replace('\n',' ') if r else "Failed"
                results.append(f"{status} **{name}**: {text}")
            except:
                results.append(f"❌ **{name}**: Error")
        e=discord.Embed(title="🔧 AI Test",description="\n".join(results),color=0x3498DB)
        await ctx.reply(embed=e)
@bot.command(name="stats")
@commands.is_owner()
async def prefix_stats(ctx):
    st=db.get_stats()
    e=discord.Embed(title="📊 Stats",color=0x3498DB)
    e.add_field(name="Servers",value=f"`{len(bot.guilds)}`")
    e.add_field(name="Users",value=f"`{sum(g.member_count or 0 for g in bot.guilds):,}`")
    if st:
        e.add_field(name="Usage",value="\n".join([f"`{c}`: {n}x"for c,n in st[:5]]),inline=False)
    await ctx.reply(embed=e)
@bot.tree.command(name="ping",description="🏓 Cek status")
async def slash_ping(i:discord.Interaction):
    e=discord.Embed(title="🏓 Pong!",color=0x00FF00)
    e.add_field(name="Latency",value=f"`{round(bot.latency*1000)}ms`")
    e.add_field(name="Servers",value=f"`{len(bot.guilds)}`")
    await i.response.send_message(embed=e)
@bot.tree.command(name="help",description="📚 Panduan")
async def slash_help(i:discord.Interaction):
    e=discord.Embed(title="📚 Excel AI Bot",color=0x217346)
    e.add_field(name="💬 Cara Pakai",value=f"• Mention: @{bot.user.name} pertanyaan\n• Prefix: `{PREFIX}ai pertanyaan`\n• Slash: `/ai pertanyaan`",inline=False)
    await i.response.send_message(embed=e)
@bot.tree.command(name="dump",description="🔓 Dump script")
@app_commands.describe(url="URL script",mode="Mode")
@app_commands.choices(mode=[
    app_commands.Choice(name="Auto",value="auto"),
    app_commands.Choice(name="Stealth",value="stealth"),
    app_commands.Choice(name="Aggressive",value="aggressive")
])
@rate(8)
@noban()
async def slash_dump(i:discord.Interaction,url:str,mode:str="auto"):
    await i.response.defer()
    try:
        content,chosen_ua,method_used,attempts=await process_dump_request(url,mode)
        if not content:
            return await i.followup.send("💀 Gagal!")
        ext="lua"
        status="✅ **BERHASIL!**"
        color=0x00FF00
        potential_links=[]
        if"<!DOCTYPE"in content[:500]:
            ext="html"
            color=0xFFFF00
            potential_links=extract_potential_links(content)
            status=f"⚠️ **HTML** - {len(potential_links)} link" if potential_links else "❌ **HTML/JS Challenge**"
        elif content.strip().startswith("{"):
            ext="json"
            status="📋 **JSON**"
        e=discord.Embed(title="🔓 Dump",description=status,color=color)
        e.add_field(name="Size",value=f"`{len(content):,}b`")
        e.add_field(name="Type",value=f"`.{ext}`")
        if potential_links:
            e.add_field(name="🔗 Links",value="\n".join([f"`{l[:50]}`"for l in potential_links[:3]]),inline=False)
        db.stat("dump",i.user.id)
        await i.followup.send(embed=e,file=discord.File(io.BytesIO(content.encode()),f"dump.{ext}"))
    except Exception as ex:
        await i.followup.send(f"💀 Error: `{ex}`")
@bot.tree.command(name="ai",description="🤖 Tanya AI")
@app_commands.describe(perintah="Perintah",file="File",model="Model")
@app_commands.choices(model=[
    app_commands.Choice(name="Auto",value="auto"),
    app_commands.Choice(name="Groq",value="groq"),
    app_commands.Choice(name="Cerebras",value="cerebras"),
    app_commands.Choice(name="SambaNova",value="sambanova"),
    app_commands.Choice(name="Cohere",value="cohere"),
    app_commands.Choice(name="OR Llama",value="or_llama"),
    app_commands.Choice(name="Pollinations",value="pollinations")
])
@rate(10)
@noban()
async def slash_ai(i:discord.Interaction,perintah:str,file:discord.Attachment=None,model:str="auto"):
    await i.response.defer()
    try:
        attachments=[file] if file else None
        parsed,resp,used=await process_ai_request(perintah,i.user.id,i.guild_id,attachments,model)
        action=parsed.get("action","text_only")
        msg=parsed.get("message","")
        if action=="generate_excel":
            ed=parsed.get("excel_data",{})
            fn=ed.get("filename","output.xlsx")
            if not fn.endswith('.xlsx'):
                fn+='.xlsx'
            ef=egen.generate(ed)
            e=discord.Embed(title="📊 Excel Created!",color=0x217346)
            e.add_field(name="File",value=f"`{fn}`")
            e.add_field(name="Model",value=f"`{used}`")
            await i.followup.send(embed=e,file=discord.File(ef,fn))
        else:
            if not msg:
                msg=resp
            e=discord.Embed(title="🤖 AI",color=0x5865F2)
            e.set_footer(text=f"Model: {used}")
            ch=split_msg(msg)
            await i.followup.send(embed=e,content=ch[0])
            for c in ch[1:]:
                await i.channel.send(c)
    except Exception as ex:
        await i.followup.send(f"❌ Error: `{ex}`")
@bot.tree.command(name="clear",description="🧹 Hapus memory")
async def slash_clear(i:discord.Interaction):
    mem.clear(i.user.id)
    await i.response.send_message("🧹 Cleared!",ephemeral=True)
@bot.tree.command(name="testai",description="🔧 Test AI")
@owner()
async def slash_testai(i:discord.Interaction):
    await i.response.defer()
    results=[]
    test_msgs=[{"role":"user","content":"Say: OK"}]
    providers=[
        ("Groq",lambda:call_groq(test_msgs)),
        ("Cerebras",lambda:call_cerebras(test_msgs)),
        ("SambaNova",lambda:call_sambanova(test_msgs)),
        ("Cohere",lambda:call_cohere(test_msgs)),
        ("OpenRouter",lambda:call_openrouter(test_msgs,"llama")),
        ("Pollinations",lambda:call_pollinations("Say: OK"))
    ]
    for name,fn in providers:
        try:
            r=fn()
            status="✅" if r else "❌"
            text=r[:40].strip().replace('\n',' ') if r else "Failed"
            results.append(f"{status} **{name}**: {text}")
        except:
            results.append(f"❌ **{name}**: Error")
    e=discord.Embed(title="🔧 AI Test",description="\n".join(results),color=0x3498DB)
    await i.followup.send(embed=e)
@bot.tree.command(name="reload",description="🔄 Sync")
@owner()
async def slash_reload(i:discord.Interaction):
    await i.response.defer()
    try:
        s=await bot.tree.sync()
        await i.followup.send(f"✅ {len(s)} synced")
    except Exception as e:
        await i.followup.send(f"❌ {e}")
if __name__=="__main__":
    keep_alive()
    print("🚀 Starting...")
    print(f"📦 Prefix: {PREFIX}")
    print(f"📦 Groq{'✅'if KEY_GROQ else'❌'} Cerebras{'✅'if KEY_CEREBRAS else'❌'} SN{'✅'if KEY_SAMBANOVA else'❌'} Cohere{'✅'if KEY_COHERE else'❌'} OR{'✅'if KEY_OPENROUTER else'❌'}")
    try:
        bot.run(DISCORD_TOKEN,log_handler=None)
    except Exception as e:
        print(f"❌ {e}")
