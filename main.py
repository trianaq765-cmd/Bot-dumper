import discord,os,io,re,time,json,random,logging,sqlite3
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import quote
from discord import app_commands
from discord.ext import commands
from keep_alive import keep_alive
logging.basicConfig(level=logging.WARNING)
logger=logging.getLogger(__name__)
logger.setLevel(logging.INFO)
DISCORD_TOKEN=os.getenv("DISCORD_TOKEN")
KEY_GROQ=os.getenv("GROQ_API_KEY")
KEY_GEMINI=os.getenv("GEMINI_API_KEY")
KEY_OPENAI=os.getenv("OPENAI_API_KEY")
KEY_OPENROUTER=os.getenv("OPENROUTER_API_KEY")
SCRAPER_KEY=os.getenv("SCRAPER_API_KEY")
OWNER_IDS=[int(x)for x in os.getenv("OWNER_IDS","0").split(",")if x.isdigit()]
if not DISCORD_TOKEN:print("❌ NO TOKEN!");exit(1)
intents=discord.Intents.default()
intents.message_content=True
bot=commands.Bot(command_prefix="!",intents=intents)
_groq=_openai=_genai=_openrouter=_curl=_requests=_pd=_openpyxl=None
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
def get_openrouter():
    global _openrouter
    if _openrouter is None and KEY_OPENROUTER:
        from openai import OpenAI
        _openrouter=OpenAI(base_url="https://openrouter.ai/api/v1",api_key=KEY_OPENROUTER)
    return _openrouter
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
        self.conn.executescript('CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY,uid INTEGER,gid INTEGER,cmd TEXT,prompt TEXT,resp TEXT,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS blacklist(uid INTEGER PRIMARY KEY,reason TEXT,by_uid INTEGER);CREATE TABLE IF NOT EXISTS stats(id INTEGER PRIMARY KEY,cmd TEXT,uid INTEGER,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);')
    def log(self,uid,gid,cmd,p,r):self.conn.execute('INSERT INTO history(uid,gid,cmd,prompt,resp)VALUES(?,?,?,?,?)',(uid,gid,cmd,p,r[:4000]));self.conn.commit()
    def hist(self,uid,n=5):return self.conn.execute('SELECT prompt,resp FROM history WHERE uid=? ORDER BY ts DESC LIMIT ?',(uid,n)).fetchall()
    def banned(self,uid):return self.conn.execute('SELECT 1 FROM blacklist WHERE uid=?',(uid,)).fetchone()is not None
    def ban(self,uid,r,by):self.conn.execute('INSERT OR REPLACE INTO blacklist VALUES(?,?,?)',(uid,r,by));self.conn.commit()
    def unban(self,uid):self.conn.execute('DELETE FROM blacklist WHERE uid=?',(uid,));self.conn.commit()
    def stat(self,cmd,uid):self.conn.execute('INSERT INTO stats(cmd,uid)VALUES(?,?)',(cmd,uid));self.conn.commit()
    def get_stats(self):return self.conn.execute('SELECT cmd,COUNT(*)FROM stats GROUP BY cmd ORDER BY COUNT(*)DESC').fetchall()
db=Database()
class RL:
    def __init__(self):self.cd=defaultdict(lambda:defaultdict(float))
    def ok(self,uid,cmd,t=5):
        now=time.time()
        if now-self.cd[uid][cmd]<t:return False,t-(now-self.cd[uid][cmd])
        self.cd[uid][cmd]=now
        return True,0
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
@dataclass
class Msg:
    role:str
    content:str
    ts:float
class Memory:
    def __init__(self):self.data=defaultdict(list)
    def add(self,uid,role,txt):
        now=time.time()
        self.data[uid]=[m for m in self.data[uid]if now-m.ts<1800]
        self.data[uid].append(Msg(role,txt,now))
        if len(self.data[uid])>10:self.data[uid]=self.data[uid][-10:]
    def get(self,uid):return[{"role":m.role,"content":m.content}for m in self.data[uid]]
    def clear(self,uid):self.data[uid]=[]
mem=Memory()
class FileReader:
    @staticmethod
    async def read(attachment)->tuple:
        fn=attachment.filename.lower()
        content=await attachment.read()
        try:
            if fn.endswith(('.xlsx','.xls')):return FileReader._excel(content,fn)
            elif fn.endswith('.csv'):return FileReader._csv(content)
            elif fn.endswith('.json'):return FileReader._json(content)
            else:return FileReader._text(content,fn)
        except Exception as e:return f"Error: {e}","error",{}
    @staticmethod
    def _excel(content,fn):
        pd=get_pandas()
        sheets=pd.read_excel(io.BytesIO(content),sheet_name=None)
        result=[];meta={"sheets":[],"rows":0}
        for name,df in sheets.items():
            meta["sheets"].append(name);meta["rows"]+=len(df)
            result.append(f"\n=== SHEET: {name} ===\nSize: {len(df)}x{len(df.columns)}\nColumns: {', '.join(map(str,df.columns.tolist()))}\nData:\n{df.to_string(max_rows=100)}")
        return '\n'.join(result),"excel",meta
    @staticmethod
    def _csv(content):
        pd=get_pandas()
        df=pd.read_csv(io.StringIO(content.decode('utf-8',errors='ignore')))
        return f"CSV: {len(df)}x{len(df.columns)}\nColumns: {', '.join(df.columns.tolist())}\nData:\n{df.to_string(max_rows=100)}","csv",{"rows":len(df)}
    @staticmethod
    def _json(content):
        data=json.loads(content.decode('utf-8',errors='ignore'))
        return f"JSON:\n{json.dumps(data,indent=2,ensure_ascii=False)[:8000]}","json",{"type":type(data).__name__,"length":len(data)if isinstance(data,list)else 1}
    @staticmethod
    def _text(content,fn):
        txt=content.decode('utf-8',errors='ignore')
        ext=fn.split('.')[-1]if'.'in fn else'txt'
        return f"File ({ext}):\n{txt[:8000]}",ext,{"lines":txt.count(chr(10))+1}
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
        if not sheets:sheets=[{"name":"Sheet1","headers":data.get("headers",[]),"data":data.get("data",[])}]
        for sh in sheets:
            ws=wb.create_sheet(title=str(sh.get("name","Sheet1"))[:31])
            headers=sh.get("headers",[])
            rows=sh.get("data",[])
            formulas=sh.get("formulas",{})
            styling=sh.get("styling",{})
            hc=styling.get("header_color","4472C4")
            hfc=styling.get("header_font_color","FFFFFF")
            hfill=PatternFill(start_color=hc,end_color=hc,fill_type="solid")
            hfont=Font(bold=True,color=hfc)
            border=Border(left=Side(style='thin'),right=Side(style='thin'),top=Side(style='thin'),bottom=Side(style='thin'))
            for ci,h in enumerate(headers,1):
                c=ws.cell(row=1,column=ci,value=str(h))
                c.font=hfont;c.fill=hfill;c.border=border;c.alignment=Alignment(horizontal='center')
            for ri,row in enumerate(rows,2):
                if not isinstance(row,list):row=[row]
                for ci,val in enumerate(row,1):
                    c=ws.cell(row=ri,column=ci,value=val)
                    c.border=border
                    c.alignment=Alignment(horizontal='left'if isinstance(val,str)else'right')
                    cl=get_column_letter(ci)
                    nf=styling.get("number_format",{})
                    if isinstance(nf,dict)and cl in nf:c.number_format=nf[cl]
                    elif isinstance(val,(int,float))and val>=1000:c.number_format='#,##0'
            for ref,f in formulas.items():
                try:ws[ref]=f;ws[ref].border=border;ws[ref].alignment=Alignment(horizontal='right')
                except:pass
            summary=sh.get("summary",{})
            if summary and rows:
                lr=len(rows)+1;sr=lr+1
                sf=summary.get("formulas",{})
                if isinstance(sf,dict):
                    for cl,f in sf.items():
                        af=str(f).replace("{last}",str(lr))
                        try:ws[f"{cl}{sr}"]=af;ws[f"{cl}{sr}"].font=Font(bold=True);ws[f"{cl}{sr}"].border=border;ws[f"{cl}{sr}"].number_format='#,##0'
                        except:pass
            for ci in range(1,max(len(headers),max((len(r)if isinstance(r,list)else 1 for r in rows),default=1))+1):
                cl=get_column_letter(ci)
                max_len=10
                if ci<=len(headers):max_len=max(max_len,len(str(headers[ci-1]))+2)
                for r in rows:
                    if isinstance(r,list)and ci<=len(r):max_len=max(max_len,len(str(r[ci-1]))+2)
                ws.column_dimensions[cl].width=min(max(max_len,12),60)
            ws.freeze_panes='A2'
        out=io.BytesIO();wb.save(out);out.seek(0)
        return out
egen=ExcelGen()
EXCEL_PROMPT='''KAMU ADALAH EXCEL EXPERT AI. WAJIB PATUHI ATURAN INI:

⚠️ ATURAN UTAMA:
1. HANYA keluarkan JSON valid, TANPA teks tambahan apapun
2. Pastikan semua kurung { } [ ] tertutup dengan benar
3. Gunakan koma (,) bukan titik (.) untuk separator
4. Angka HARUS berupa number (15000000) bukan string ("15000000")
5. Nama/teks harus LENGKAP (Beras bukan ras, Gula bukan la)

📤 FORMAT OUTPUT:

Jika perlu GENERATE Excel:
{"action":"generate_excel","message":"deskripsi","excel_data":{"sheets":[{"name":"Sheet1","headers":["Kolom1","Kolom2","Total"],"data":[["Item1",100,200],["Item2",150,300]],"formulas":{"C2":"=A2*B2","C3":"=A3*B3"},"styling":{"header_color":"4472C4","number_format":{"B":"#,##0","C":"#,##0"}},"summary":{"formulas":{"B":"=SUM(B2:B{last})","C":"=SUM(C2:C{last})"}}}],"filename":"output.xlsx"}}

Jika hanya JAWAB pertanyaan:
{"action":"text_only","message":"jawaban lengkap"}

📊 RUMUS EXCEL: SUM,AVERAGE,COUNT,MAX,MIN,IF,VLOOKUP,HLOOKUP,INDEX,MATCH,SUMIF,COUNTIF,SUMIFS,COUNTIFS,LEFT,RIGHT,MID,LEN,TRIM,CONCATENATE,TEXT,DATE,TODAY,NOW,PMT,FV,PV,ROUND,IFERROR,AND,OR

🇮🇩 Jawab dalam Bahasa Indonesia.'''

# OpenRouter Models
OR_MODELS={
    "claude":"anthropic/claude-3.5-sonnet",
    "gpt4":"openai/gpt-4o-2024-11-20",
    "llama":"meta-llama/llama-3.3-70b-instruct",
    "gemini":"google/gemini-2.0-flash-exp:free",
    "mistral":"mistralai/mistral-large-2411",
    "qwen":"qwen/qwen-2.5-72b-instruct",
    "deepseek":"deepseek/deepseek-chat"
}

def ask_ai_select(prompt,uid=None,model_choice="auto",or_model="claude"):
    msgs=[{"role":"system","content":EXCEL_PROMPT}]
    if uid:msgs.extend(mem.get(uid))
    msgs.append({"role":"user","content":prompt})
    
    def try_groq():
        cl=get_groq()
        if not cl:return None,None
        try:
            r=cl.chat.completions.create(messages=msgs,model="llama-3.3-70b-versatile",temperature=0.2,max_tokens=8000)
            resp=r.choices[0].message.content
            if uid:mem.add(uid,"user",prompt);mem.add(uid,"assistant",resp)
            return resp,"Groq"
        except Exception as e:logger.warning(f"Groq:{e}");return None,None
    
    def try_openai():
        cl=get_openai()
        if not cl:return None,None
        try:
            r=cl.chat.completions.create(model="gpt-4o",messages=msgs,temperature=0.2,max_tokens=8000)
            resp=r.choices[0].message.content
            if uid:mem.add(uid,"user",prompt);mem.add(uid,"assistant",resp)
            return resp,"OpenAI"
        except Exception as e:logger.warning(f"OpenAI:{e}");return None,None
    
    def try_openrouter(model_key="claude"):
        cl=get_openrouter()
        if not cl:return None,None
        model_id=OR_MODELS.get(model_key,OR_MODELS["claude"])
        try:
            r=cl.chat.completions.create(
                model=model_id,
                messages=msgs,
                temperature=0.2,
                max_tokens=8000,
                extra_headers={"HTTP-Referer":"https://discord.com","X-Title":"Excel AI Bot"}
            )
            resp=r.choices[0].message.content
            if uid:mem.add(uid,"user",prompt);mem.add(uid,"assistant",resp)
            return resp,f"OR:{model_key}"
        except Exception as e:logger.warning(f"OpenRouter:{e}");return None,None
    
    def try_gemini():
        g=get_genai()
        if not g:return None,None
        try:
            sf=[{"category":c,"threshold":"BLOCK_NONE"}for c in["HARM_CATEGORY_HARASSMENT","HARM_CATEGORY_HATE_SPEECH","HARM_CATEGORY_SEXUALLY_EXPLICIT","HARM_CATEGORY_DANGEROUS_CONTENT"]]
            m=g.GenerativeModel("gemini-2.0-flash",safety_settings=sf,system_instruction=EXCEL_PROMPT)
            r=m.generate_content(prompt)
            if uid:mem.add(uid,"user",prompt);mem.add(uid,"assistant",r.text)
            return r.text,"Gemini"
        except Exception as e:logger.warning(f"Gemini:{e}");return None,None
    
    def try_poll():
        try:
            req=get_requests()
            url=f"https://text.pollinations.ai/{quote(prompt[:1000])}?model=openai&system={quote(EXCEL_PROMPT[:500])}"
            r=req.get(url,timeout=60)
            if r.ok and len(r.text)>10:
                if uid:mem.add(uid,"user",prompt);mem.add(uid,"assistant",r.text)
                return r.text,"Pollinations"
        except:pass
        return None,None
    
    # Model selection
    if model_choice=="groq":
        r,m=try_groq();return(r,m)if r else('{"action":"text_only","message":"❌ Groq tidak tersedia."}',"none")
    elif model_choice=="openai":
        r,m=try_openai();return(r,m)if r else('{"action":"text_only","message":"❌ OpenAI tidak tersedia."}',"none")
    elif model_choice=="gemini":
        r,m=try_gemini();return(r,m)if r else('{"action":"text_only","message":"❌ Gemini tidak tersedia."}',"none")
    elif model_choice=="pollinations":
        r,m=try_poll();return(r,m)if r else('{"action":"text_only","message":"❌ Pollinations tidak tersedia."}',"none")
    elif model_choice.startswith("or_"):
        or_key=model_choice.replace("or_","")
        r,m=try_openrouter(or_key);return(r,m)if r else('{"action":"text_only","message":"❌ OpenRouter tidak tersedia."}',"none")
    else:  # auto
        for fn in[try_groq,lambda:try_openrouter("claude"),try_openai,try_gemini,try_poll]:
            r,m=fn()
            if r:return r,m
        return'{"action":"text_only","message":"❌ Semua AI tidak tersedia."}',"none"

def fix_json(text):
    text=text.strip()
    text=re.sub(r',(\s*[}\]])',r'\1',text)
    text=re.sub(r'"\s*\.\s*"','","',text)
    text=text.replace("'",'"')
    ob=text.count('{');cb=text.count('}')
    if ob>cb:text+='}'*(ob-cb)
    osb=text.count('[');csb=text.count(']')
    if osb>csb:text+=']'*(osb-csb)
    return text
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
            jt=m.group(1)
            try:return json.loads(jt)
            except:
                jt=fix_json(jt)
                try:return json.loads(jt)
                except:pass
    except:pass
    return{"action":"text_only","message":resp}
def split_msg(t,lim=1900):
    if len(t)<=lim:return[t]
    ch=[];cur=""
    for l in t.split('\n'):
        if len(cur)+len(l)+1>lim:
            if cur:ch.append(cur)
            cur=l
        else:cur+=('\n'if cur else'')+l
    if cur:ch.append(cur)
    return ch or[t[:lim]]
def headers():return{"User-Agent":"Roblox/WinInet","Roblox-Place-Id":"2753915549"}
def valid_url(u):return u.startswith(("http://","https://"))and not any(x in u.lower()for x in["localhost","127.0.0.1"])
@bot.event
async def on_ready():
    logger.info(f'🔥 {bot.user}|{len(bot.guilds)} guilds')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching,name="/help"))
    try:await bot.tree.sync();logger.info("✅ Synced")
    except Exception as e:logger.error(f"Sync:{e}")
@bot.tree.error
async def on_error(i,e):
    try:await i.response.send_message(f"❌ {str(e)[:100]}",ephemeral=True)
    except:pass
@bot.tree.command(name="ping",description="🏓 Cek status bot")
async def ping(i:discord.Interaction):
    e=discord.Embed(title="🏓 Pong!",color=0x00FF00)
    e.add_field(name="Latency",value=f"`{round(bot.latency*1000)}ms`")
    e.add_field(name="Servers",value=f"`{len(bot.guilds)}`")
    e.add_field(name="AI",value=f"G{'✅'if KEY_GROQ else'❌'} O{'✅'if KEY_OPENAI else'❌'} M{'✅'if KEY_GEMINI else'❌'} R{'✅'if KEY_OPENROUTER else'❌'}")
    await i.response.send_message(embed=e)
@bot.tree.command(name="help",description="📚 Panduan bot")
async def help_cmd(i:discord.Interaction):
    e=discord.Embed(title="📚 Excel AI Bot",description="Bot AI untuk Excel & Script",color=0x217346)
    e.add_field(name="🔓 /dump <url>",value="Download script",inline=False)
    e.add_field(name="🤖 /ai <perintah> [file] [model]",value="Tanya AI / Buat Excel\n\n**Model Tersedia:**\n• Auto, Groq, OpenAI, Gemini\n• OpenRouter: Claude, GPT-4, Llama, Mistral, Qwen, DeepSeek",inline=False)
    e.add_field(name="📝 Contoh",value="```/ai Buatkan invoice PT ABC\n/ai [file.json] Convert ke Excel\n/ai Rumus diskon bertingkat model:or_claude```",inline=False)
    e.add_field(name="🔧 Lainnya",value="`/clear` `/history` `/stats` `/reload`",inline=False)
    await i.response.send_message(embed=e)
@bot.tree.command(name="dump",description="🔓 Download script")
@app_commands.describe(url="URL script",raw="Mode raw")
@rate(10)
@noban()
async def dump(i:discord.Interaction,url:str,raw:bool=False):
    await i.response.defer()
    if not valid_url(url):return await i.followup.send("❌ URL tidak valid!")
    try:
        curl=get_curl();req=get_requests()
        if raw or not SCRAPER_KEY:c=curl.get(url,impersonate="chrome120",headers=headers(),timeout=30).text;m="Raw"
        else:c=req.get('http://api.scraperapi.com',params={'api_key':SCRAPER_KEY,'url':url},headers=headers(),timeout=90).text;m="Scraper"
        ext="lua"
        if"<!DOCTYPE"in c[:500]:ext="html"
        elif c.strip().startswith(("{","[")):ext="json"
        e=discord.Embed(title=f"{'✅'if ext=='lua'else'⚠️'} Dump",color=0x00FF00 if ext=="lua"else 0xFFFF00)
        e.add_field(name="Size",value=f"`{len(c):,}B`")
        e.add_field(name="Type",value=f"`.{ext}`")
        e.add_field(name="Via",value=m)
        db.stat("dump",i.user.id)
        await i.followup.send(embed=e,file=discord.File(io.BytesIO(c.encode()),f"dump.{ext}"))
    except Exception as ex:await i.followup.send(f"💀 {str(ex)[:200]}")
@bot.tree.command(name="ai",description="🤖 Tanya AI / Buat Excel")
@app_commands.describe(perintah="Perintah untuk AI",file="Upload file",model="Pilih AI model")
@app_commands.choices(model=[
    app_commands.Choice(name="🚀 Auto (Tercepat)",value="auto"),
    app_commands.Choice(name="⚡ Groq (Llama 3.3)",value="groq"),
    app_commands.Choice(name="🤖 OpenAI (GPT-4o)",value="openai"),
    app_commands.Choice(name="🧠 Gemini (2.0 Flash)",value="gemini"),
    app_commands.Choice(name="🟣 Claude 3.5 Sonnet",value="or_claude"),
    app_commands.Choice(name="🟢 GPT-4o (Router)",value="or_gpt4"),
    app_commands.Choice(name="🦙 Llama 3.3 70B",value="or_llama"),
    app_commands.Choice(name="🌀 Mistral Large",value="or_mistral"),
    app_commands.Choice(name="🔮 Qwen 2.5 72B",value="or_qwen"),
    app_commands.Choice(name="🌊 DeepSeek Chat",value="or_deepseek"),
    app_commands.Choice(name="🌺 Pollinations (Free)",value="pollinations")])
@rate(10)
@noban()
async def ai_cmd(i:discord.Interaction,perintah:str,file:discord.Attachment=None,model:str="auto"):
    await i.response.defer()
    try:
        parts=[perintah]
        if file:
            fc,ft,meta=await freader.read(file)
            parts.append(f"\n\n=== FILE: {file.filename} ({ft}) ===\n{json.dumps(meta)}\n\n{fc}")
        prompt='\n'.join(parts)
        resp,used=ask_ai_select(prompt,i.user.id,model)
        parsed=parse_ai(resp)
        action=parsed.get("action","text_only")
        msg=parsed.get("message","")
        db.log(i.user.id,i.guild_id,"ai",perintah[:500],msg[:500])
        db.stat("ai",i.user.id)
        if action=="generate_excel":
            ed=parsed.get("excel_data",{})
            fn=ed.get("filename","output.xlsx")
            if not fn.endswith('.xlsx'):fn+='.xlsx'
            try:
                ef=egen.generate(ed)
                e=discord.Embed(title="📊 Excel Created!",color=0x217346)
                e.add_field(name="📄 File",value=f"`{fn}`",inline=True)
                e.add_field(name="🤖 Model",value=f"`{used}`",inline=True)
                sheets=ed.get("sheets",[])
                if sheets:
                    rows=sum(len(s.get("data",[]))for s in sheets)
                    e.add_field(name="📊 Rows",value=f"`{rows}`",inline=True)
                if msg:e.add_field(name="💬 Info",value=msg[:400],inline=False)
                await i.followup.send(embed=e,file=discord.File(ef,fn))
            except Exception as ex:
                logger.error(f"Excel:{ex}")
                await i.followup.send(f"⚠️ Excel error: `{ex}`\n\n```json\n{resp[:1500]}```")
        else:
            if not msg:msg=resp
            e=discord.Embed(title="🤖 AI Response",color=0x5865F2)
            e.set_footer(text=f"Model: {used}")
            ch=split_msg(msg)
            await i.followup.send(embed=e,content=ch[0])
            for c in ch[1:]:await i.channel.send(c)
    except Exception as ex:
        logger.error(f"AI:{ex}")
        await i.followup.send(f"❌ Error: `{str(ex)[:200]}`")
@bot.tree.command(name="clear",description="🧹 Hapus memory")
async def clear_cmd(i:discord.Interaction):
    mem.clear(i.user.id)
    await i.response.send_message("🧹 Memory dihapus!",ephemeral=True)
@bot.tree.command(name="history",description="📜 History chat")
@app_commands.describe(limit="Jumlah (max 10)")
async def history_cmd(i:discord.Interaction,limit:int=5):
    h=db.hist(i.user.id,min(limit,10))
    if not h:return await i.response.send_message("📭 Kosong.",ephemeral=True)
    e=discord.Embed(title="📜 History",color=0x3498DB)
    for idx,(p,r)in enumerate(h,1):e.add_field(name=f"{idx}. {p[:35]}...",value=f"```{r[:70]}...```",inline=False)
    await i.response.send_message(embed=e,ephemeral=True)
@bot.tree.command(name="stats",description="📊 Stats (Owner)")
@owner()
async def stats_cmd(i:discord.Interaction):
    st=db.get_stats()
    e=discord.Embed(title="📊 Stats",color=0x3498DB)
    e.add_field(name="Servers",value=f"`{len(bot.guilds)}`")
    e.add_field(name="Users",value=f"`{sum(g.member_count or 0 for g in bot.guilds):,}`")
    if st:e.add_field(name="Usage",value="\n".join([f"`{c}`: {n}x"for c,n in st[:8]]),inline=False)
    await i.response.send_message(embed=e)
@bot.tree.command(name="blacklist",description="🚫 Ban (Owner)")
@owner()
@app_commands.describe(user="User",reason="Alasan")
async def bl_cmd(i:discord.Interaction,user:discord.User,reason:str=""):
    db.ban(user.id,reason,i.user.id)
    await i.response.send_message(f"🚫 {user} banned")
@bot.tree.command(name="unblacklist",description="✅ Unban (Owner)")
@owner()
@app_commands.describe(user="User")
async def ubl_cmd(i:discord.Interaction,user:discord.User):
    db.unban(user.id)
    await i.response.send_message(f"✅ {user} unbanned")
@bot.tree.command(name="reload",description="🔄 Sync (Owner)")
@owner()
async def reload_cmd(i:discord.Interaction):
    await i.response.defer()
    try:s=await bot.tree.sync();await i.followup.send(f"✅ {len(s)} synced!")
    except Exception as e:await i.followup.send(f"❌ {e}")
if __name__=="__main__":
    keep_alive()
    time.sleep(1)
    print(f"🚀 Excel AI Bot Starting...")
    print(f"📦 Groq{'✅'if KEY_GROQ else'❌'} OpenAI{'✅'if KEY_OPENAI else'❌'} Gemini{'✅'if KEY_GEMINI else'❌'} OpenRouter{'✅'if KEY_OPENROUTER else'❌'}")
    try:bot.run(DISCORD_TOKEN,log_handler=None)
    except discord.LoginFailure:print("❌ Invalid Token!")
    except Exception as e:print(f"❌ {e}")
