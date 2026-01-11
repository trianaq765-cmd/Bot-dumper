import discord,os,io,re,time,json,logging,sqlite3
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import quote
from discord import app_commands
from discord.ext import commands
from keep_alive import keep_alive
logging.basicConfig(level=logging.INFO,format='%(asctime)s|%(levelname)s|%(message)s')
logger=logging.getLogger(__name__)
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
_groq=_openai=_curl=_requests=_pd=_openpyxl=None
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
    role:str;content:str;ts:float
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
            if fn.endswith(('.xlsx','.xls')):return FileReader._excel(content)
            elif fn.endswith('.csv'):return FileReader._csv(content)
            elif fn.endswith('.json'):return FileReader._json(content)
            else:return FileReader._text(content,fn)
        except Exception as e:return f"Error: {e}","error",{}
    @staticmethod
    def _excel(content):
        pd=get_pandas()
        sheets=pd.read_excel(io.BytesIO(content),sheet_name=None)
        result=[];meta={"sheets":[],"rows":0}
        for name,df in sheets.items():
            meta["sheets"].append(name);meta["rows"]+=len(df)
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
        if not sheets:sheets=[{"name":"Sheet1","headers":data.get("headers",[]),"data":data.get("data",[])}]
        for sh in sheets:
            ws=wb.create_sheet(title=str(sh.get("name","Sheet1"))[:31])
            headers=sh.get("headers",[]);rows=sh.get("data",[]);formulas=sh.get("formulas",{});styling=sh.get("styling",{})
            hfill=PatternFill(start_color=styling.get("header_color","4472C4"),end_color=styling.get("header_color","4472C4"),fill_type="solid")
            hfont=Font(bold=True,color=styling.get("header_font_color","FFFFFF"))
            border=Border(left=Side(style='thin'),right=Side(style='thin'),top=Side(style='thin'),bottom=Side(style='thin'))
            for ci,h in enumerate(headers,1):
                c=ws.cell(row=1,column=ci,value=str(h));c.font=hfont;c.fill=hfill;c.border=border;c.alignment=Alignment(horizontal='center')
            for ri,row in enumerate(rows,2):
                if not isinstance(row,(list,tuple)):row=[row]
                for ci,val in enumerate(row,1):
                    c=ws.cell(row=ri,column=ci,value=val);c.border=border
                    if isinstance(val,(int,float))and abs(val)>=1000:c.number_format='#,##0'
            for ref,f in formulas.items():
                try:ws[ref]=f;ws[ref].border=border
                except:pass
            summary=sh.get("summary",{})
            if summary and rows:
                lr=len(rows)+1;sr=lr+1
                for cl,f in summary.get("formulas",{}).items():
                    try:ws[f"{cl}{sr}"]=str(f).replace("{last}",str(lr));ws[f"{cl}{sr}"].font=Font(bold=True);ws[f"{cl}{sr}"].border=border
                    except:pass
            for ci in range(1,max(len(headers),1)+1):
                cl=get_column_letter(ci)
                ml=len(str(headers[ci-1]))if ci<=len(headers)else 10
                for r in rows:
                    if isinstance(r,(list,tuple))and ci<=len(r):ml=max(ml,len(str(r[ci-1])))
                ws.column_dimensions[cl].width=min(max(ml+5,15),60)
            ws.freeze_panes='A2'
        out=io.BytesIO();wb.save(out);out.seek(0)
        return out
egen=ExcelGen()
EXCEL_PROMPT='''KAMU EXCEL EXPERT AI. ATURAN KETAT:
1. HANYA JSON valid, tanpa teks lain
2. Angka = number (15000), bukan string
3. Teks harus LENGKAP

FORMAT:
Generate Excel: {"action":"generate_excel","message":"info","excel_data":{"sheets":[{"name":"Sheet1","headers":["A","B","C"],"data":[["x",1,2]],"formulas":{"C2":"=A2*B2"},"styling":{"header_color":"4472C4"},"summary":{"formulas":{"B":"=SUM(B2:B{last})"}}}],"filename":"output.xlsx"}}
Jawab saja: {"action":"text_only","message":"jawaban"}
Bahasa Indonesia.'''
OR_FREE={"llama":"meta-llama/llama-3.3-70b-instruct:free","gemini":"google/gemini-2.0-flash-exp:free","mistral":"mistralai/mistral-7b-instruct:free","qwen":"qwen/qwen-2-7b-instruct:free"}
GEMINI_MODELS=["gemini-2.0-flash","gemini-1.5-pro","gemini-pro","gemini-1.0-pro"]
def ask_ai(prompt,uid=None,model="auto"):
    msgs=[{"role":"system","content":EXCEL_PROMPT}]
    if uid:msgs.extend(mem.get(uid))
    msgs.append({"role":"user","content":prompt})
    def try_groq():
        cl=get_groq()
        if not cl:return None,None
        try:
            r=cl.chat.completions.create(messages=msgs,model="llama-3.3-70b-versatile",temperature=0.2,max_tokens=8000)
            return r.choices[0].message.content,"Groq"
        except Exception as e:logger.warning(f"Groq:{e}");return None,None
    def try_openai():
        cl=get_openai()
        if not cl:return None,None
        try:
            r=cl.chat.completions.create(model="gpt-4o",messages=msgs,temperature=0.2,max_tokens=8000)
            return r.choices[0].message.content,"OpenAI"
        except Exception as e:logger.warning(f"OpenAI:{e}");return None,None
    def try_gemini():
        if not KEY_GEMINI:return None,None
        try:
            import google.generativeai as genai
            genai.configure(api_key=KEY_GEMINI)
            for mn in GEMINI_MODELS:
                try:
                    m=genai.GenerativeModel(mn)
                    r=m.generate_content(f"{EXCEL_PROMPT}\n\nUser:{prompt}")
                    if r and r.text:return r.text,f"Gemini({mn})"
                except Exception as e:
                    if "404" in str(e)or "not found" in str(e).lower():continue
                    logger.warning(f"Gemini {mn}:{e}");continue
            return None,None
        except Exception as e:logger.warning(f"Gemini:{e}");return None,None
    def try_or(mk="llama"):
        if not KEY_OPENROUTER:return None,None
        try:
            req=get_requests()
            r=req.post("https://openrouter.ai/api/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_OPENROUTER}","Content-Type":"application/json"},json={"model":OR_FREE.get(mk,OR_FREE["llama"]),"messages":msgs,"temperature":0.2},timeout=60)
            if r.status_code==200:return r.json()["choices"][0]["message"]["content"],f"OR:{mk}"
            logger.warning(f"OR:{r.status_code}");return None,None
        except Exception as e:logger.warning(f"OR:{e}");return None,None
    def try_poll():
        try:
            req=get_requests()
            r=req.get(f"https://text.pollinations.ai/{quote(prompt[:1000])}?model=openai&system={quote(EXCEL_PROMPT[:500])}",timeout=60)
            if r.ok and len(r.text)>10:return r.text,"Pollinations"
        except Exception as e:logger.warning(f"Poll:{e}")
        return None,None
    if model=="groq":res,m=try_groq();return(res,m)if res else try_poll()
    elif model=="openai":res,m=try_openai();return(res,m)if res else try_poll()
    elif model=="gemini":res,m=try_gemini();return(res,m)if res else try_poll()
    elif model=="pollinations":return try_poll()
    elif model.startswith("or_"):res,m=try_or(model[3:]);return(res,m)if res else try_poll()
    else:
        for fn in[try_groq,try_gemini,lambda:try_or("llama"),try_openai,try_poll]:
            res,m=fn()
            if res:
                if uid:mem.add(uid,"user",prompt);mem.add(uid,"assistant",res)
                return res,m
    return'{"action":"text_only","message":"❌ Semua AI tidak tersedia."}',"none"
def fix_json(t):
    t=t.strip()
    t=re.sub(r',(\s*[}\]])',r'\1',t)
    t=re.sub(r'"\s*\.\s*"','","',t)
    t=t.replace("'",'"')
    ob,cb=t.count('{'),t.count('}')
    if ob>cb:t+='}'*(ob-cb)
    os,cs=t.count('['),t.count(']')
    if os>cs:t+=']'*(os-cs)
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
            try:return json.loads(m.group(1))
            except:return json.loads(fix_json(m.group(1)))
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
def headers():return{"User-Agent":"Roblox/WinInet","Roblox-Place-Id":"2753915549","Accept-Encoding":"gzip,deflate,br"}
def valid_url(u):return u.startswith(("http://","https://"))and not any(x in u.lower()for x in["localhost","127.0.0.1","0.0.0.0"])
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
    e=discord.Embed(title="📚 Excel AI Bot",description="Bot untuk Excel & Script Dumper",color=0x217346)
    e.add_field(name="🔓 /dump <url>",value="Download script dari URL",inline=False)
    e.add_field(name="🤖 /ai <perintah> [file] [model]",value="Tanya AI / Buat Excel\n`Auto,Groq,OpenAI,Gemini,Pollinations`\n`or_llama,or_gemini,or_mistral,or_qwen`",inline=False)
    e.add_field(name="🔧 /testai",value="Test koneksi semua AI",inline=False)
    e.add_field(name="📝 Contoh",value="```/ai Buatkan invoice PT ABC\n/ai [upload.json] Convert ke Excel\n/ai Rumus hitung diskon```",inline=False)
    e.add_field(name="🔧 Lainnya",value="`/clear` `/history` `/stats` `/reload`",inline=False)
    await i.response.send_message(embed=e)
@bot.tree.command(name="dump",description="🔓 Download script dari URL")
@app_commands.describe(url="URL script",raw="Mode raw tanpa proxy")
@rate(10)
@noban()
async def dump(i:discord.Interaction,url:str,raw:bool=False):
    await i.response.defer()
    if not valid_url(url):return await i.followup.send("❌ URL tidak valid!")
    try:
        curl=get_curl();req=get_requests()
        if raw or not SCRAPER_KEY:c=curl.get(url,impersonate="chrome120",headers=headers(),timeout=30).text;m="Raw"
        else:c=req.get('http://api.scraperapi.com',params={'api_key':SCRAPER_KEY,'url':url,'keep_headers':'true'},headers=headers(),timeout=90).text;m="Scraper"
        ext="lua"
        if"<!DOCTYPE"in c[:500]:ext="html"
        elif c.strip().startswith(("{","[")):ext="json"
        e=discord.Embed(title=f"{'✅'if ext=='lua'else'⚠️'} Dump",color=0x00FF00 if ext=="lua"else 0xFFFF00)
        e.add_field(name="📦 Size",value=f"`{len(c):,} bytes`")
        e.add_field(name="📄 Type",value=f"`.{ext}`")
        e.add_field(name="🔧 Via",value=m)
        db.stat("dump",i.user.id)
        await i.followup.send(embed=e,file=discord.File(io.BytesIO(c.encode()),f"dump.{ext}"))
    except Exception as ex:await i.followup.send(f"💀 Error: `{str(ex)[:200]}`")
@bot.tree.command(name="testai",description="🔧 Test koneksi semua AI")
@owner()
async def testai(i:discord.Interaction):
    await i.response.defer()
    results=[];t="Jawab: OK"
    # Groq
    try:
        cl=get_groq()
        if cl:cl.chat.completions.create(messages=[{"role":"user","content":t}],model="llama-3.3-70b-versatile",max_tokens=10);results.append("✅ **Groq**")
        else:results.append("❌ **Groq**: No Key")
    except Exception as e:results.append(f"❌ **Groq**: `{str(e)[:40]}`")
    # OpenAI
    try:
        cl=get_openai()
        if cl:cl.chat.completions.create(model="gpt-4o",messages=[{"role":"user","content":t}],max_tokens=10);results.append("✅ **OpenAI**")
        else:results.append("❌ **OpenAI**: No Key")
    except Exception as e:results.append(f"❌ **OpenAI**: `{str(e)[:40]}`")
    # Gemini - try multiple models
    try:
        if KEY_GEMINI:
            import google.generativeai as genai
            genai.configure(api_key=KEY_GEMINI)
            found=False
            for mn in GEMINI_MODELS:
                try:
                    genai.GenerativeModel(mn).generate_content(t)
                    results.append(f"✅ **Gemini** ({mn})")
                    found=True
                    break
                except Exception as e:
                    if "404" in str(e)or "not found" in str(e).lower():continue
                    results.append(f"❌ **Gemini** ({mn}): `{str(e)[:30]}`")
                    found=True
                    break
            if not found:results.append("❌ **Gemini**: No valid model found")
        else:results.append("❌ **Gemini**: No Key")
    except Exception as e:results.append(f"❌ **Gemini**: `{str(e)[:40]}`")
    # OpenRouter
    try:
        if KEY_OPENROUTER:
            req=get_requests()
            r=req.post("https://openrouter.ai/api/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_OPENROUTER}","Content-Type":"application/json"},json={"model":"meta-llama/llama-3.3-70b-instruct:free","messages":[{"role":"user","content":t}]},timeout=30)
            if r.status_code==200:results.append("✅ **OpenRouter**")
            else:results.append(f"❌ **OpenRouter**: HTTP {r.status_code}")
        else:results.append("❌ **OpenRouter**: No Key")
    except Exception as e:results.append(f"❌ **OpenRouter**: `{str(e)[:40]}`")
    # Pollinations
    try:
        req=get_requests()
        r=req.get(f"https://text.pollinations.ai/{quote(t)}?model=openai",timeout=30)
        if r.ok:results.append("✅ **Pollinations**")
        else:results.append(f"❌ **Pollinations**: HTTP {r.status_code}")
    except Exception as e:results.append(f"❌ **Pollinations**: `{str(e)[:40]}`")
    e=discord.Embed(title="🔧 AI Connection Test",description="\n".join(results),color=0x3498DB)
    await i.followup.send(embed=e)
@bot.tree.command(name="ai",description="🤖 Tanya AI / Buat Excel")
@app_commands.describe(perintah="Perintah untuk AI",file="Upload file",model="Pilih AI")
@app_commands.choices(model=[
    app_commands.Choice(name="🚀 Auto",value="auto"),
    app_commands.Choice(name="⚡ Groq",value="groq"),
    app_commands.Choice(name="🤖 OpenAI",value="openai"),
    app_commands.Choice(name="🧠 Gemini",value="gemini"),
    app_commands.Choice(name="🦙 Llama (Free)",value="or_llama"),
    app_commands.Choice(name="🔵 Gemini (Free)",value="or_gemini"),
    app_commands.Choice(name="🌀 Mistral (Free)",value="or_mistral"),
    app_commands.Choice(name="🔮 Qwen (Free)",value="or_qwen"),
    app_commands.Choice(name="🌺 Pollinations",value="pollinations")])
@rate(10)
@noban()
async def ai_cmd(i:discord.Interaction,perintah:str,file:discord.Attachment=None,model:str="auto"):
    await i.response.defer()
    try:
        parts=[perintah]
        if file:
            fc,ft,meta=await freader.read(file)
            parts.append(f"\n\n=== FILE: {file.filename} ({ft}) ===\n{json.dumps(meta,ensure_ascii=False)}\n\n{fc}")
        prompt='\n'.join(parts)
        resp,used=ask_ai(prompt,i.user.id,model)
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
                if sheets:e.add_field(name="📊 Rows",value=f"`{sum(len(s.get('data',[]))for s in sheets)}`",inline=True)
                if msg:e.add_field(name="💬 Info",value=msg[:400],inline=False)
                await i.followup.send(embed=e,file=discord.File(ef,fn))
            except Exception as ex:
                logger.error(f"Excel:{ex}")
                await i.followup.send(f"⚠️ Excel error: `{ex}`\n```json\n{resp[:1500]}```")
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
@bot.tree.command(name="clear",description="🧹 Hapus memory chat")
async def clear_cmd(i:discord.Interaction):
    mem.clear(i.user.id)
    await i.response.send_message("🧹 Memory dihapus!",ephemeral=True)
@bot.tree.command(name="history",description="📜 Lihat history chat")
@app_commands.describe(limit="Jumlah (max 10)")
async def history_cmd(i:discord.Interaction,limit:int=5):
    h=db.hist(i.user.id,min(limit,10))
    if not h:return await i.response.send_message("📭 History kosong.",ephemeral=True)
    e=discord.Embed(title="📜 Chat History",color=0x3498DB)
    for idx,(p,r)in enumerate(h,1):e.add_field(name=f"{idx}. {p[:35]}{'...'if len(p)>35 else''}",value=f"```{r[:70]}{'...'if len(r)>70 else''}```",inline=False)
    await i.response.send_message(embed=e,ephemeral=True)
@bot.tree.command(name="stats",description="📊 Statistik bot (Owner)")
@owner()
async def stats_cmd(i:discord.Interaction):
    st=db.get_stats()
    e=discord.Embed(title="📊 Bot Stats",color=0x3498DB)
    e.add_field(name="🌐 Servers",value=f"`{len(bot.guilds)}`")
    e.add_field(name="👥 Users",value=f"`{sum(g.member_count or 0 for g in bot.guilds):,}`")
    if st:e.add_field(name="📈 Usage",value="\n".join([f"`{c}`: {n}x"for c,n in st[:8]]),inline=False)
    await i.response.send_message(embed=e)
@bot.tree.command(name="blacklist",description="🚫 Ban user (Owner)")
@owner()
@app_commands.describe(user="User target",reason="Alasan")
async def bl_cmd(i:discord.Interaction,user:discord.User,reason:str="No reason"):
    db.ban(user.id,reason,i.user.id)
    await i.response.send_message(f"🚫 **{user}** telah di-blacklist: {reason}")
@bot.tree.command(name="unblacklist",description="✅ Unban user (Owner)")
@owner()
@app_commands.describe(user="User target")
async def ubl_cmd(i:discord.Interaction,user:discord.User):
    db.unban(user.id)
    await i.response.send_message(f"✅ **{user}** telah di-unblacklist")
@bot.tree.command(name="reload",description="🔄 Sync commands (Owner)")
@owner()
async def reload_cmd(i:discord.Interaction):
    await i.response.defer()
    try:s=await bot.tree.sync();await i.followup.send(f"✅ {len(s)} commands synced!")
    except Exception as e:await i.followup.send(f"❌ Error: {e}")
if __name__=="__main__":
    keep_alive()
    time.sleep(1)
    print(f"🚀 Excel AI Bot Starting...")
    print(f"📦 Groq{'✅'if KEY_GROQ else'❌'} OpenAI{'✅'if KEY_OPENAI else'❌'} Gemini{'✅'if KEY_GEMINI else'❌'} OpenRouter{'✅'if KEY_OPENROUTER else'❌'}")
    try:bot.run(DISCORD_TOKEN,log_handler=None)
    except discord.LoginFailure:print("❌ Invalid Token!")
    except Exception as e:print(f"❌ {e}")
