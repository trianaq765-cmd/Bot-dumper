import discord,os,io,re,time,json,logging,sqlite3,random
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import quote
from discord import app_commands
from discord.ext import commands
try:from keep_alive import keep_alive
except:keep_alive=lambda:None
logging.basicConfig(level=logging.INFO,format='%(asctime)s|%(levelname)s|%(message)s')
logger=logging.getLogger(__name__)
DISCORD_TOKEN=os.getenv("DISCORD_TOKEN")
KEY_GROQ=os.getenv("GROQ_API_KEY")
KEY_GEMINI=os.getenv("GEMINI_API_KEY")
KEY_OPENROUTER=os.getenv("OPENROUTER_API_KEY")
OWNER_IDS=[int(x)for x in os.getenv("OWNER_IDS","0").split(",")if x.isdigit()]
if not DISCORD_TOKEN:print("❌ NO TOKEN!");exit(1)
intents=discord.Intents.default()
intents.message_content=True
bot=commands.Bot(command_prefix="!",intents=intents)
UA_LIST=["Roblox/WinInet","Synapse-X/2.0","Sentinel/3.0","Krnl/1.0","KRNL/2.0","Fluxus/1.0","ScriptWare/2.0","Electron/1.0","Hydrogen/1.0","Codex/1.0","Arceus-X/2.0","Delta/1.0","Trigon/3.0","Evon/1.0","JJSploit/7.0","Comet/1.0","Nihon/1.0","Celery/1.0","Vega-X/1.0","Oxygen-U/1.0"]
_groq=_curl=_requests=_pd=_openpyxl=None
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
        self.conn.executescript('CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY,uid INTEGER,gid INTEGER,cmd TEXT,prompt TEXT,resp TEXT,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS blacklist(uid INTEGER PRIMARY KEY,reason TEXT,by_uid INTEGER);CREATE TABLE IF NOT EXISTS stats(id INTEGER PRIMARY KEY,cmd TEXT,uid INTEGER,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);')
    def log(self,uid,gid,cmd,p,r):self.conn.execute('INSERT INTO history(uid,gid,cmd,prompt,resp)VALUES(?,?,?,?,?)',(uid,gid,cmd,p,r[:4000]if r else""));self.conn.commit()
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
1. HANYA keluarkan JSON valid, TANPA teks lain sebelum atau sesudah JSON
2. Angka harus number (15000), bukan string ("15000")
3. Teks harus LENGKAP, jangan dipotong

FORMAT WAJIB:
Jika diminta buat/generate Excel:
{"action":"generate_excel","message":"deskripsi singkat","excel_data":{"sheets":[{"name":"Sheet1","headers":["Kolom1","Kolom2","Total"],"data":[["Item1",100,200],["Item2",150,250]],"formulas":{"C2":"=A2*B2","C3":"=A3*B3"},"styling":{"header_color":"4472C4"},"summary":{"formulas":{"B":"=SUM(B2:B{last})","C":"=SUM(C2:C{last})"}}}],"filename":"output.xlsx"}}

Jika hanya jawab pertanyaan:
{"action":"text_only","message":"jawaban lengkap disini"}

Jawab dalam Bahasa Indonesia. JANGAN tambahkan teks apapun selain JSON.'''
OR_FREE={"llama":"meta-llama/llama-3.3-70b-instruct:free","gemini":"google/gemini-2.0-flash-exp:free","mistral":"mistralai/mistral-7b-instruct:free","qwen":"qwen/qwen-2-7b-instruct:free"}
def call_groq(msgs):
    cl=get_groq()
    if not cl:
        logger.info("Groq: No API key")
        return None
    try:
        logger.info("Groq: Calling...")
        r=cl.chat.completions.create(messages=msgs,model="llama-3.3-70b-versatile",temperature=0.2,max_tokens=8000)
        resp=r.choices[0].message.content
        logger.info(f"Groq: Success, length={len(resp)}")
        return resp
    except Exception as e:
        logger.error(f"Groq: Error - {e}")
        return None
def call_openrouter(msgs,model_key="llama"):
    if not KEY_OPENROUTER:
        logger.info("OpenRouter: No API key")
        return None
    try:
        logger.info(f"OpenRouter ({model_key}): Calling...")
        req=get_requests()
        model_id=OR_FREE.get(model_key,"meta-llama/llama-3.3-70b-instruct:free")
        r=req.post("https://openrouter.ai/api/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_OPENROUTER}","Content-Type":"application/json"},json={"model":model_id,"messages":msgs,"temperature":0.2,"max_tokens":8000},timeout=60)
        if r.status_code==200:
            resp=r.json()["choices"][0]["message"]["content"]
            logger.info(f"OpenRouter: Success, length={len(resp)}")
            return resp
        else:
            logger.error(f"OpenRouter: HTTP {r.status_code}")
            return None
    except Exception as e:
        logger.error(f"OpenRouter: Error - {e}")
        return None
def call_gemini(prompt):
    if not KEY_GEMINI:
        logger.info("Gemini: No API key")
        return None
    try:
        logger.info("Gemini: Calling via REST API...")
        req=get_requests()
        models=["gemini-1.5-flash","gemini-1.5-pro","gemini-2.0-flash-exp"]
        for model in models:
            try:
                url=f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={KEY_GEMINI}"
                payload={"contents":[{"parts":[{"text":f"{EXCEL_PROMPT}\n\nUser: {prompt}"}]}],"generationConfig":{"temperature":0.2,"maxOutputTokens":8000}}
                r=req.post(url,json=payload,timeout=30,headers={"Content-Type":"application/json"})
                if r.status_code==200:
                    data=r.json()
                    if "candidates" in data and len(data["candidates"])>0:
                        candidate=data["candidates"][0]
                        if "content" in candidate and "parts" in candidate["content"]:
                            text=candidate["content"]["parts"][0].get("text","")
                            if text:
                                logger.info(f"Gemini ({model}): Success, length={len(text)}")
                                return text
                elif r.status_code==429:
                    logger.warning(f"Gemini ({model}): Rate limit, trying next...")
                    continue
                elif r.status_code==404:
                    logger.warning(f"Gemini ({model}): Model not found, trying next...")
                    continue
                else:
                    logger.warning(f"Gemini ({model}): HTTP {r.status_code} - {r.text[:100]}")
                    continue
            except Exception as e:
                logger.error(f"Gemini ({model}): {e}")
                continue
        logger.error("Gemini: All models failed")
        return None
    except Exception as e:
        logger.error(f"Gemini: Error - {e}")
        return None
def call_pollinations(prompt):
    try:
        logger.info("Pollinations: Calling...")
        req=get_requests()
        full_prompt=f"{EXCEL_PROMPT}\n\nUser: {prompt}"
        r=req.get(f"https://text.pollinations.ai/{quote(full_prompt[:2000])}",timeout=60)
        if r.ok and len(r.text)>10:
            logger.info(f"Pollinations: Success, length={len(r.text)}")
            return r.text
        return None
    except Exception as e:
        logger.error(f"Pollinations: Error - {e}")
        return None
def ask_ai(prompt,uid=None,model="auto"):
    msgs=[{"role":"system","content":EXCEL_PROMPT},{"role":"user","content":prompt}]
    if uid:
        history=mem.get(uid)
        if history:msgs=[{"role":"system","content":EXCEL_PROMPT}]+history+[{"role":"user","content":prompt}]
    result=None;used_model="none"
    logger.info(f"ask_ai called with model={model}")
    if model=="groq":result=call_groq(msgs);used_model="Groq"
    elif model=="gemini":result=call_gemini(prompt);used_model="Gemini"
    elif model=="pollinations":result=call_pollinations(prompt);used_model="Pollinations"
    elif model.startswith("or_"):mk=model[3:];result=call_openrouter(msgs,mk);used_model=f"OpenRouter({mk})"
    else:
        logger.info("Auto mode: trying Groq first...")
        result=call_groq(msgs)
        if result:used_model="Groq"
        else:
            logger.info("Auto mode: trying OpenRouter...")
            result=call_openrouter(msgs,"llama")
            if result:used_model="OpenRouter"
            else:
                logger.info("Auto mode: trying Gemini...")
                result=call_gemini(prompt)
                if result:used_model="Gemini"
                else:
                    logger.info("Auto mode: trying Pollinations...")
                    result=call_pollinations(prompt)
                    if result:used_model="Pollinations"
    if not result and model!="auto":
        logger.info(f"{model} failed, trying fallbacks...")
        for fn,name in[(lambda:call_groq(msgs),"Groq"),(lambda:call_openrouter(msgs,"llama"),"OpenRouter"),(lambda:call_gemini(prompt),"Gemini"),(lambda:call_pollinations(prompt),"Pollinations")]:
            result=fn()
            if result:used_model=f"{name}(fallback)";break
    if not result:result='{"action":"text_only","message":"❌ Semua AI tidak tersedia saat ini."}';used_model="none"
    if uid and result:mem.add(uid,"user",prompt);mem.add(uid,"assistant",result)
    logger.info(f"Final model used: {used_model}")
    return result,used_model
def fix_json(t):
    t=t.strip()
    t=re.sub(r',(\s*[}\]])',r'\1',t)
    t=re.sub(r'"\s*\.\s*"','","',t)
    t=t.replace("'",'"')
    ob,cb=t.count('{'),t.count('}')
    if ob>cb:t+='}'*(ob-cb)
    os_,cs=t.count('['),t.count(']')
    if os_>cs:t+=']'*(os_-cs)
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
def get_roblox_headers():
    return{"User-Agent":random.choice(UA_LIST),"Roblox-Place-Id":"2753915549","Roblox-Game-Id":"9876543210","Roblox-Universe-Id":"1234567890","Accept":"*/*","Accept-Language":"en-US,en;q=0.9","Accept-Encoding":"gzip,deflate,br","Connection":"keep-alive","Cache-Control":"no-cache"}
def valid_url(u):return u.startswith(("http://","https://"))and not any(x in u.lower()for x in["localhost","127.0.0.1","0.0.0.0","[::1]","127.1"])
def extract_potential_links(html):
    patterns=[r'https?://[^\s"\'<>\)]+\.lua[^\s"\'<>\)]*',r'https?://[^\s"\'<>\)]*(?:raw|get|api|script|load|paste)[^\s"\'<>\)]*',r'https?://(?:pastebin\.com|raw\.githubusercontent\.com|gist\.githubusercontent\.com|rentry\.co|hastebin\.com)[^\s"\'<>\)]+',r'loadstring\s*\(\s*game\s*:\s*HttpGet\s*\(\s*["\']([^"\']+)["\']',r'["\']?(https?://[^\s"\'<>\)]+)["\']?\s*(?:,|\))',r'(?:url|link|script|source)\s*[=:]\s*["\']?(https?://[^\s"\'<>\)]+)']
    links=set()
    for p in patterns:
        for m in re.findall(p,html,re.IGNORECASE):links.add(m if isinstance(m,str)else m[0]if m else"")
    return[l for l in links if l and l.startswith("http")and len(l)>15]
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
    e.add_field(name="AI Keys",value=f"Groq{'✅'if KEY_GROQ else'❌'} Gemini{'✅'if KEY_GEMINI else'❌'} Router{'✅'if KEY_OPENROUTER else'❌'}")
    await i.response.send_message(embed=e)
@bot.tree.command(name="help",description="📚 Panduan bot")
async def help_cmd(i:discord.Interaction):
    e=discord.Embed(title="📚 Excel AI Bot + Script Dumper",description="Bot untuk Excel & Script Dumper Roblox",color=0x217346)
    e.add_field(name="🔓 /dump <url> [mode]",value="Download script Luarmor/Protected\n**Modes:** auto, stealth, aggressive, raw",inline=False)
    e.add_field(name="🤖 /ai <perintah> [file] [model]",value="Tanya AI / Buat Excel\n**Models:** Auto, Groq, Gemini, OpenRouter, Pollinations",inline=False)
    e.add_field(name="🔧 /testai",value="Test koneksi semua AI",inline=False)
    e.add_field(name="📝 Contoh Dump",value="```/dump https://luarmor.net/... mode:stealth\n/dump https://api.luarmor.net/files/v3/loaders/...```",inline=False)
    e.add_field(name="🔧 Lainnya",value="`/clear` `/history` `/stats` `/reload`",inline=False)
    await i.response.send_message(embed=e)
@bot.tree.command(name="dump",description="🔓 Dump script Luarmor/Protected")
@app_commands.describe(url="URL script target",mode="Mode bypass")
@app_commands.choices(mode=[app_commands.Choice(name="🚀 Auto (Recommended)",value="auto"),app_commands.Choice(name="🥷 Stealth (Slow but safe)",value="stealth"),app_commands.Choice(name="⚡ Aggressive (Multi-attempt)",value="aggressive"),app_commands.Choice(name="📄 Raw (Direct request)",value="raw")])
@rate(8)
@noban()
async def dump(i:discord.Interaction,url:str,mode:str="auto"):
    await i.response.defer()
    if not valid_url(url):return await i.followup.send("❌ URL tidak valid!")
    try:
        curl=get_curl()
        content=None;method_used="";chosen_ua="";attempts=[]
        browsers=["chrome110","chrome116","chrome120","edge99","safari15_5"]if mode=="aggressive"else["chrome110"]
        if mode=="stealth":browsers=["safari15_5","chrome110"];time.sleep(random.uniform(0.5,1.5))
        for browser in browsers:
            chosen_ua=random.choice(UA_LIST)
            hdrs=get_roblox_headers()
            hdrs["User-Agent"]=chosen_ua
            try:
                r=curl.get(url,impersonate=browser,headers=hdrs,timeout=20)
                content=r.text;method_used=f"{browser}+{chosen_ua[:15]}";attempts.append(f"✅ {browser}")
                if"<!DOCTYPE"not in content[:200]and"<html"not in content[:100].lower():break
                attempts[-1]=f"⚠️ {browser}(HTML)"
            except Exception as ex:attempts.append(f"❌ {browser}:{str(ex)[:20]}")
        if not content:return await i.followup.send(f"💀 Semua metode gagal!\n```{chr(10).join(attempts)}```")
        ext="lua";status="";color=0x00FF00;potential_links=[]
        if"<!DOCTYPE"in content[:500]or"<html"in content[:200].lower():
            ext="html";color=0xFFFF00
            potential_links=extract_potential_links(content)
            if potential_links:status=f"⚠️ **HTML Detected** - Ditemukan {len(potential_links)} link potensial"
            else:status="❌ **HTML/JS Challenge** - Tidak ada link ditemukan"
        elif content.strip().startswith(("{","[")):ext="json";status="📋 **JSON Response**"
        else:status="✅ **SCRIPT BERHASIL DIDUMP!**";color=0x00FF00
        e=discord.Embed(title="🔓 Dump Result",description=status,color=color)
        e.add_field(name="📦 Size",value=f"`{len(content):,} bytes`",inline=True)
        e.add_field(name="📄 Type",value=f"`.{ext}`",inline=True)
        e.add_field(name="🎭 UA",value=f"`{chosen_ua[:20]}...`",inline=True)
        e.add_field(name="🔧 Method",value=f"`{method_used}`",inline=True)
        e.add_field(name="🌐 Mode",value=f"`{mode}`",inline=True)
        if len(attempts)>1:e.add_field(name="📊 Attempts",value=f"```{chr(10).join(attempts[:5])}```",inline=False)
        if potential_links:
            links_text="\n".join([f"• `{l[:60]}...`"if len(l)>60 else f"• `{l}`"for l in potential_links[:5]])
            e.add_field(name="🔗 Potential Scripts",value=links_text,inline=False)
            if len(potential_links)>5:e.set_footer(text=f"+{len(potential_links)-5} more links found")
        db.stat("dump",i.user.id)
        await i.followup.send(embed=e,file=discord.File(io.BytesIO(content.encode()),f"dump.{ext}"))
    except Exception as ex:
        logger.error(f"Dump error: {ex}")
        await i.followup.send(f"💀 Error: `{str(ex)[:200]}`")
@bot.tree.command(name="testai",description="🔧 Test koneksi semua AI")
@owner()
async def testai(i:discord.Interaction):
    await i.response.defer()
    results=[]
    test_msgs=[{"role":"user","content":"Jawab hanya dengan satu kata: OK"}]
    r=call_groq(test_msgs);results.append(f"{'✅'if r else'❌'} **Groq**: {r[:50].strip()if r else'Failed'}")
    r=call_openrouter(test_msgs,"llama");results.append(f"{'✅'if r else'❌'} **OpenRouter**: {r[:50].strip()if r else'Failed'}")
    r=call_gemini("Jawab hanya dengan satu kata: OK");results.append(f"{'✅'if r else'❌'} **Gemini**: {r[:50].strip()if r else'Failed'}")
    r=call_pollinations("Jawab hanya dengan satu kata: OK");results.append(f"{'✅'if r else'❌'} **Pollinations**: {r[:50].strip()if r else'Failed'}")
    e=discord.Embed(title="🔧 AI Test Results",description="\n".join(results),color=0x3498DB)
    e.set_footer(text="Gemini menggunakan REST API v1beta")
    await i.followup.send(embed=e)
@bot.tree.command(name="ai",description="🤖 Tanya AI / Buat Excel")
@app_commands.describe(perintah="Perintah untuk AI",file="Upload file",model="Pilih AI model")
@app_commands.choices(model=[app_commands.Choice(name="🚀 Auto (Recommended)",value="auto"),app_commands.Choice(name="⚡ Groq (Fast)",value="groq"),app_commands.Choice(name="🧠 Gemini (REST API)",value="gemini"),app_commands.Choice(name="🦙 OpenRouter Llama",value="or_llama"),app_commands.Choice(name="🔵 OpenRouter Gemini",value="or_gemini"),app_commands.Choice(name="🌺 Pollinations",value="pollinations")])
@rate(10)
@noban()
async def ai_cmd(i:discord.Interaction,perintah:str,file:discord.Attachment=None,model:str="auto"):
    await i.response.defer()
    logger.info(f"AI command: model={model}, prompt={perintah[:50]}...")
    try:
        parts=[perintah]
        if file:
            fc,ft,meta=await freader.read(file)
            parts.append(f"\n\n=== FILE: {file.filename} ({ft}) ===\n{json.dumps(meta,ensure_ascii=False)}\n\n{fc}")
        prompt='\n'.join(parts)
        resp,used=ask_ai(prompt,i.user.id,model)
        logger.info(f"AI response received from {used}, length={len(resp)}")
        parsed=parse_ai(resp)
        action=parsed.get("action","text_only")
        msg=parsed.get("message","")
        db.log(i.user.id,i.guild_id,"ai",perintah[:500],msg[:500]if msg else"")
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
                logger.error(f"Excel generation error: {ex}")
                await i.followup.send(f"⚠️ Excel error: `{ex}`\n\nRaw response:\n```json\n{resp[:1000]}```")
        else:
            if not msg:msg=resp
            e=discord.Embed(title="🤖 AI Response",color=0x5865F2)
            e.set_footer(text=f"Model: {used}")
            ch=split_msg(msg)
            await i.followup.send(embed=e,content=ch[0])
            for c in ch[1:]:await i.channel.send(c)
    except Exception as ex:
        logger.error(f"AI command error: {ex}")
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
    for idx,(p,r)in enumerate(h,1):e.add_field(name=f"{idx}. {p[:35]}...",value=f"```{r[:70]}...```",inline=False)
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
    await i.response.send_message(f"🚫 **{user}** di-blacklist: {reason}")
@bot.tree.command(name="unblacklist",description="✅ Unban user (Owner)")
@owner()
@app_commands.describe(user="User target")
async def ubl_cmd(i:discord.Interaction,user:discord.User):
    db.unban(user.id)
    await i.response.send_message(f"✅ **{user}** di-unblacklist")
@bot.tree.command(name="reload",description="🔄 Sync commands (Owner)")
@owner()
async def reload_cmd(i:discord.Interaction):
    await i.response.defer()
    try:s=await bot.tree.sync();await i.followup.send(f"✅ {len(s)} commands synced!")
    except Exception as e:await i.followup.send(f"❌ Error: {e}")
if __name__=="__main__":
    keep_alive()
    time.sleep(1)
    print("🚀 Excel AI Bot + Script Dumper Starting...")
    print(f"📦 Keys: Groq{'✅'if KEY_GROQ else'❌'} Gemini{'✅'if KEY_GEMINI else'❌'} OpenRouter{'✅'if KEY_OPENROUTER else'❌'}")
    print(f"🎭 Loaded {len(UA_LIST)} User-Agents")
    print("🔄 Gemini menggunakan REST API v1beta")
    try:bot.run(DISCORD_TOKEN,log_handler=None)
    except discord.LoginFailure:print("❌ Invalid Token!")
    except Exception as e:print(f"❌ {e}")
