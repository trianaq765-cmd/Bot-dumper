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
KEY_CLAUDE_1=os.getenv("CLAUDE_API_KEY_1")
KEY_CLAUDE_2=os.getenv("CLAUDE_API_KEY_2")
OWNER_IDS=[int(x)for x in os.getenv("OWNER_IDS","0").split(",")if x.isdigit()]
PREFIX=os.getenv("BOT_PREFIX","!")
if not DISCORD_TOKEN:
    print("❌ NO TOKEN!")
    exit(1)
intents=discord.Intents.default()
intents.message_content=True
bot=commands.Bot(command_prefix=PREFIX,intents=intents,help_command=None)
UA_LIST=["Roblox/WinInet","Synapse-X/2.0","Sentinel/3.0","Krnl/1.0","KRNL/2.0","Fluxus/1.0","ScriptWare/2.0","Electron/1.0","Hydrogen/1.0","Codex/1.0","Arceus-X/2.0","Delta/1.0","Trigon/3.0","Evon/1.0","JJSploit/7.0","Comet/1.0","Nihon/1.0","Celery/1.0","Vega-X/1.0","Oxygen-U/1.0"]
claude_key_index=0
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
def get_claude_key():
    """Rotate between Claude API keys"""
    global claude_key_index
    keys=[k for k in[KEY_CLAUDE_1,KEY_CLAUDE_2]if k]
    if not keys:
        return None
    key=keys[claude_key_index%len(keys)]
    claude_key_index+=1
    return key
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
        self.data[uid].append(Msg(role,content,now))
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
    "gemini":"google/gemini-2.5-pro-exp-03-25:free",
    "gemini2":"google/gemini-2.0-flash-001:free",
    "mistral":"mistralai/mistral-small-3.1-24b-instruct:free",
    "qwen":"qwen/qwen3-235b-a22b:free",
    "deepseek":"deepseek/deepseek-chat-v3-0324:free",
    "phi":"microsoft/phi-4:free",
    "llama4":"meta-llama/llama-4-maverick:free"
}
MODEL_NAMES={
    "auto":"🚀 Auto",
    "groq":"⚡ Groq",
    "cerebras":"🧠 Cerebras",
    "sambanova":"🦣 SambaNova",
    "cohere":"🔷 Cohere",
    "claude":"🟠 Claude",
    "or_llama":"🦙 OR Llama",
    "or_gemini":"🔵 OR Gemini",
    "or_qwen":"🟣 OR Qwen",
    "or_deepseek":"🧪 OR DeepSeek",
    "or_mistral":"🔶 OR Mistral",
    "or_phi":"🔷 OR Phi-4",
    "pollinations":"🌺 Pollinations"
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
        model_id=OR_FREE.get(model_key,OR_FREE["llama"])
        logger.info(f"OpenRouter: Trying {model_key} -> {model_id}")
        r=req.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization":f"Bearer {KEY_OPENROUTER}",
                "Content-Type":"application/json",
                "HTTP-Referer":"https://github.com",
                "X-Title":"ExcelBot"
            },
            json={"model":model_id,"messages":msgs,"temperature":0.2,"max_tokens":8000},
            timeout=90
        )
        if r.status_code==200:
            data=r.json()
            if "choices" in data and len(data["choices"])>0:
                content=data["choices"][0]["message"]["content"]
                if content:
                    logger.info(f"OpenRouter {model_key}: Success")
                    return content
        logger.error(f"OpenRouter {model_key}: HTTP {r.status_code} - {r.text[:200]}")
        if model_key!="llama":
            logger.info(f"OpenRouter: Fallback to llama...")
            return call_openrouter(msgs,"llama")
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
def call_claude(msgs):
    """Call Claude API with key rotation"""
    api_key=get_claude_key()
    if not api_key:
        logger.info("Claude: No API keys")
        return None
    try:
        req=get_requests()
        system_msg=""
        messages=[]
        for m in msgs:
            if m["role"]=="system":
                system_msg=m["content"]
            else:
                messages.append({"role":m["role"],"content":m["content"]})
        payload={
            "model":"claude-3-haiku-20240307",
            "max_tokens":4096,
            "messages":messages
        }
        if system_msg:
            payload["system"]=system_msg
        r=req.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":api_key,
                "Content-Type":"application/json",
                "anthropic-version":"2023-06-01"
            },
            json=payload,
            timeout=60
        )
        if r.status_code==200:
            data=r.json()
            if "content" in data and len(data["content"])>0:
                text=data["content"][0].get("text","")
                if text:
                    logger.info("Claude: Success")
                    return text
        elif r.status_code==429:
            logger.warning(f"Claude: Rate limited, trying other key...")
            other_key=get_claude_key()
            if other_key and other_key!=api_key:
                return call_claude(msgs)
        logger.error(f"Claude: HTTP {r.status_code} - {r.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"Claude: {e}")
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
def call_model_direct(model,msgs,prompt):
    """Call specific model directly"""
    if model=="groq":
        return call_groq(msgs),"Groq"
    elif model=="cerebras":
        return call_cerebras(msgs),"Cerebras"
    elif model=="sambanova":
        return call_sambanova(msgs),"SambaNova"
    elif model=="cohere":
        return call_cohere(msgs),"Cohere"
    elif model=="claude":
        return call_claude(msgs),"Claude"
    elif model=="pollinations":
        return call_pollinations(prompt),"Pollinations"
    elif model.startswith("or_"):
        mk=model[3:]
        return call_openrouter(msgs,mk),f"OR({mk})"
    return None,"none"
def ask_ai(prompt,uid=None,model=None):
    """Main AI function with persistent model preference"""
    if model is None or model=="auto":
        if uid:
            model=db.get_user_model(uid)
        else:
            model="auto"
    if uid and model!="auto":
        db.set_user_model(uid,model)
    msgs=[{"role":"system","content":EXCEL_PROMPT}]
    if uid:
        history=mem.get_last_n(uid,10)
        if history:
            msgs.extend(history)
    msgs.append({"role":"user","content":prompt})
    result=None
    used_model="none"
    if model!="auto":
        logger.info(f"Direct call to: {model}")
        result,used_model=call_model_direct(model,msgs,prompt)
        if not result:
            logger.info(f"{model} failed, trying fallbacks...")
            fallbacks=[
                (lambda:call_groq(msgs),"Groq"),
                (lambda:call_cerebras(msgs),"Cerebras"),
                (lambda:call_claude(msgs),"Claude"),
                (lambda:call_openrouter(msgs,"llama"),"OpenRouter")
            ]
            for fn,name in fallbacks:
                result=fn()
                if result:
                    used_model=f"{name}(fallback)"
                    break
    else:
        providers=[
            (lambda:call_groq(msgs),"Groq"),
            (lambda:call_cerebras(msgs),"Cerebras"),
            (lambda:call_claude(msgs),"Claude"),
            (lambda:call_openrouter(msgs,"llama"),"OpenRouter"),
            (lambda:call_sambanova(msgs),"SambaNova"),
            (lambda:call_cohere(msgs),"Cohere"),
            (lambda:call_pollinations(prompt),"Pollinations")
        ]
        for fn,name in providers:
            try:
                result=fn()
                if result:
                    used_model=name
                    break
            except:
                continue
    if not result:
        result='{"action":"text_only","message":"❌ Semua AI tidak tersedia."}'
        used_model="none"
    if uid and result:
        mem.add(uid,"user",prompt)
        clean_response=result
        try:
            parsed=json.loads(result)
            if "message" in parsed:
                clean_response=parsed["message"]
        except:
            pass
        mem.add(uid,"assistant",clean_response[:2000])
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
async def process_ai_request(prompt,uid,gid,attachments=None,model=None):
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
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching,name=f"{PREFIX}help"))
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
                return await message.reply("🚫 Blacklist!")
            ok,remaining=rl.ok(message.author.id,"mention",5)
            if not ok:
                return await message.reply(f"⏳ Tunggu **{remaining:.1f}s**")
            async with message.channel.typing():
                try:
                    attachments=list(message.attachments) if message.attachments else None
                    user_model=db.get_user_model(message.author.id)
                    parsed,resp,used=await process_ai_request(
                        content,message.author.id,
                        message.guild.id if message.guild else None,
                        attachments,user_model
                    )
                    action=parsed.get("action","text_only")
                    msg=parsed.get("message","")
                    if action=="generate_excel":
                        ed=parsed.get("excel_data",{})
                        fn=ed.get("filename","output.xlsx")
                        if not fn.endswith('.xlsx'):fn+='.xlsx'
                        ef=egen.generate(ed)
                        e=discord.Embed(title="📊 Excel!",color=0x217346)
                        e.add_field(name="File",value=f"`{fn}`")
                        e.add_field(name="Model",value=f"`{used}`")
                        await message.reply(embed=e,file=discord.File(ef,fn))
                    else:
                        if not msg:msg=resp
                        chunks=split_msg(msg)
                        await message.reply(f"**🤖 {used}:**\n{chunks[0]}")
                        for c in chunks[1:]:
                            await message.channel.send(c)
                except Exception as ex:
                    await message.reply(f"❌ Error: `{ex}`")
        else:
            cm=db.get_user_model(message.author.id)
            await message.reply(f"👋 Model: **{MODEL_NAMES.get(cm,cm)}**\nKetik pertanyaan!")
        return
    await bot.process_commands(message)
@bot.tree.error
async def on_error(i,e):
    try:await i.response.send_message(f"❌ {str(e)[:100]}",ephemeral=True)
    except:pass
@bot.command(name="model",aliases=["m"])
async def prefix_model(ctx,model:str=None):
    valid=list(MODEL_NAMES.keys())
    if not model:
        cm=db.get_user_model(ctx.author.id)
        e=discord.Embed(title="🤖 Model",color=0x3498DB)
        e.add_field(name="Current",value=f"**{MODEL_NAMES.get(cm,cm)}**",inline=False)
        e.add_field(name="Available",value="\n".join([f"`{k}` {v}"for k,v in MODEL_NAMES.items()]),inline=False)
        return await ctx.reply(embed=e)
    model=model.lower()
    if model not in valid:
        return await ctx.reply(f"❌ Invalid! Use: `{', '.join(valid)}`")
    db.set_user_model(ctx.author.id,model)
    await ctx.reply(f"✅ Model: **{MODEL_NAMES.get(model,model)}**")
@bot.command(name="ai",aliases=["ask","chat"])
async def prefix_ai(ctx,*,prompt:str=None):
    if db.banned(ctx.author.id):return await ctx.reply("🚫 Blacklist!")
    ok,r=rl.ok(ctx.author.id,"ai",10)
    if not ok:return await ctx.reply(f"⏳ Tunggu **{r:.1f}s**")
    if not prompt and not ctx.message.attachments:
        return await ctx.reply(f"❌ `{PREFIX}ai <prompt>`")
    async with ctx.typing():
        try:
            att=list(ctx.message.attachments)if ctx.message.attachments else None
            um=db.get_user_model(ctx.author.id)
            parsed,resp,used=await process_ai_request(prompt or"Analisis",ctx.author.id,ctx.guild.id if ctx.guild else None,att,um)
            action=parsed.get("action","text_only")
            msg=parsed.get("message","")
            if action=="generate_excel":
                ed=parsed.get("excel_data",{})
                fn=ed.get("filename","output.xlsx")
                if not fn.endswith('.xlsx'):fn+='.xlsx'
                ef=egen.generate(ed)
                e=discord.Embed(title="📊 Excel!",color=0x217346)
                e.add_field(name="File",value=f"`{fn}`")
                e.add_field(name="Model",value=f"`{used}`")
                await ctx.reply(embed=e,file=discord.File(ef,fn))
            else:
                if not msg:msg=resp
                chunks=split_msg(msg)
                await ctx.reply(f"**🤖 {used}:**\n{chunks[0]}")
                for c in chunks[1:]:await ctx.send(c)
        except Exception as ex:
            await ctx.reply(f"❌ Error: `{ex}`")
@bot.command(name="dump")
async def prefix_dump(ctx,url:str=None,mode:str="auto"):
    if db.banned(ctx.author.id):return await ctx.reply("🚫")
    ok,r=rl.ok(ctx.author.id,"dump",8)
    if not ok:return await ctx.reply(f"⏳ {r:.1f}s")
    if not url:return await ctx.reply(f"❌ `{PREFIX}dump <url>`")
    async with ctx.typing():
        try:
            content,ua,_,_=await process_dump_request(url,mode)
            if not content:return await ctx.reply("💀 Gagal!")
            ext="lua";status="✅";color=0x00FF00;links=[]
            if"<!DOCTYPE"in content[:500]:
                ext="html";color=0xFFFF00;links=extract_potential_links(content)
                status=f"⚠️ HTML - {len(links)} link"if links else"❌ Challenge"
            elif content.strip().startswith("{"):ext="json";status="📋 JSON"
            e=discord.Embed(title="🔓 Dump",description=status,color=color)
            e.add_field(name="Size",value=f"`{len(content):,}b`")
            e.add_field(name="Type",value=f"`.{ext}`")
            if links:e.add_field(name="Links",value="\n".join([f"`{l[:40]}`"for l in links[:3]]),inline=False)
            db.stat("dump",ctx.author.id)
            await ctx.reply(embed=e,file=discord.File(io.BytesIO(content.encode()),f"dump.{ext}"))
        except Exception as ex:await ctx.reply(f"💀 {ex}")
@bot.command(name="ping")
async def prefix_ping(ctx):
    cm=db.get_user_model(ctx.author.id)
    e=discord.Embed(title="🏓 Pong!",color=0x00FF00)
    e.add_field(name="Latency",value=f"`{round(bot.latency*1000)}ms`")
    e.add_field(name="Model",value=f"`{MODEL_NAMES.get(cm,cm)}`")
    e.add_field(name="Memory",value=f"`{len(mem.get(ctx.author.id))} msgs`")
    claude_count=len([k for k in[KEY_CLAUDE_1,KEY_CLAUDE_2]if k])
    e.add_field(name="Claude Keys",value=f"`{claude_count}`")
    await ctx.reply(embed=e)
@bot.command(name="help",aliases=["h"])
async def prefix_help(ctx):
    cm=db.get_user_model(ctx.author.id)
    e=discord.Embed(title="📚 Excel AI Bot",description=f"Model: **{MODEL_NAMES.get(cm,cm)}**",color=0x217346)
    e.add_field(name="💬 Usage",value=f"• @{bot.user.name} <prompt>\n• `{PREFIX}ai <prompt>`",inline=False)
    e.add_field(name="🤖 AI",value=f"`{PREFIX}ai` `{PREFIX}model` `{PREFIX}clear`",inline=False)
    e.add_field(name="🔓 Dump",value=f"`{PREFIX}dump <url>`",inline=False)
    e.add_field(name="📋 Models",value="`auto` `groq` `cerebras` `claude` `sambanova` `cohere`\n`or_llama` `or_gemini` `or_qwen` `or_deepseek` `or_mistral`",inline=False)
    await ctx.reply(embed=e)
@bot.command(name="clear")
async def prefix_clear(ctx):
    mem.clear(ctx.author.id)
    await ctx.reply("🧹 Memory cleared!")
@bot.command(name="history")
async def prefix_history(ctx):
    h=mem.get_last_n(ctx.author.id,5)
    if not h:return await ctx.reply("📭 Empty")
    e=discord.Embed(title="📜 Memory",color=0x3498DB)
    for i,m in enumerate(h,1):
        role="👤"if m["role"]=="user"else"🤖"
        e.add_field(name=f"{i}. {role}",value=f"```{m['content'][:80]}...```",inline=False)
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
            ("Claude",lambda:call_claude(test_msgs)),
            ("SambaNova",lambda:call_sambanova(test_msgs)),
            ("Cohere",lambda:call_cohere(test_msgs)),
            ("OR-Llama",lambda:call_openrouter(test_msgs,"llama")),
            ("OR-Gemini",lambda:call_openrouter(test_msgs,"gemini")),
            ("OR-Qwen",lambda:call_openrouter(test_msgs,"qwen")),
            ("OR-DeepSeek",lambda:call_openrouter(test_msgs,"deepseek")),
            ("Pollinations",lambda:call_pollinations("Say: OK"))
        ]
        for name,fn in providers:
            try:
                r=fn()
                s="✅"if r else"❌"
                t=r[:30].strip().replace('\n',' ')if r else"Failed"
                results.append(f"{s} **{name}**: {t}")
            except Exception as ex:
                results.append(f"❌ **{name}**: {str(ex)[:20]}")
        e=discord.Embed(title="🔧 AI Test",description="\n".join(results),color=0x3498DB)
        claude_keys=len([k for k in[KEY_CLAUDE_1,KEY_CLAUDE_2]if k])
        e.set_footer(text=f"Claude keys: {claude_keys}")
        await ctx.reply(embed=e)
@bot.command(name="stats")
@commands.is_owner()
async def prefix_stats(ctx):
    st=db.get_stats()
    e=discord.Embed(title="📊 Stats",color=0x3498DB)
    e.add_field(name="Servers",value=f"`{len(bot.guilds)}`")
    e.add_field(name="Users",value=f"`{sum(g.member_count or 0 for g in bot.guilds):,}`")
    if st:e.add_field(name="Usage",value="\n".join([f"`{c}`: {n}x"for c,n in st[:5]]),inline=False)
    await ctx.reply(embed=e)
@bot.tree.command(name="model",description="🤖 Set AI model")
@app_commands.describe(model="Model")
@app_commands.choices(model=[
    app_commands.Choice(name="🚀 Auto",value="auto"),
    app_commands.Choice(name="⚡ Groq",value="groq"),
    app_commands.Choice(name="🧠 Cerebras",value="cerebras"),
    app_commands.Choice(name="🟠 Claude",value="claude"),
    app_commands.Choice(name="🦣 SambaNova",value="sambanova"),
    app_commands.Choice(name="🔷 Cohere",value="cohere"),
    app_commands.Choice(name="🦙 OR Llama",value="or_llama"),
    app_commands.Choice(name="🔵 OR Gemini",value="or_gemini"),
    app_commands.Choice(name="🟣 OR Qwen",value="or_qwen"),
    app_commands.Choice(name="🧪 OR DeepSeek",value="or_deepseek"),
    app_commands.Choice(name="🌺 Pollinations",value="pollinations")
])
async def slash_model(i:discord.Interaction,model:str=None):
    if model:
        db.set_user_model(i.user.id,model)
        await i.response.send_message(f"✅ Model: **{MODEL_NAMES.get(model,model)}**",ephemeral=True)
    else:
        cm=db.get_user_model(i.user.id)
        await i.response.send_message(f"🤖 Model: **{MODEL_NAMES.get(cm,cm)}**",ephemeral=True)
@bot.tree.command(name="ai",description="🤖 Ask AI")
@app_commands.describe(prompt="Prompt",file="File")
@rate(10)
@noban()
async def slash_ai(i:discord.Interaction,prompt:str,file:discord.Attachment=None):
    await i.response.defer()
    try:
        att=[file]if file else None
        um=db.get_user_model(i.user.id)
        parsed,resp,used=await process_ai_request(prompt,i.user.id,i.guild_id,att,um)
        action=parsed.get("action","text_only")
        msg=parsed.get("message","")
        if action=="generate_excel":
            ed=parsed.get("excel_data",{})
            fn=ed.get("filename","output.xlsx")
            if not fn.endswith('.xlsx'):fn+='.xlsx'
            ef=egen.generate(ed)
            e=discord.Embed(title="📊 Excel!",color=0x217346)
            e.add_field(name="Model",value=f"`{used}`")
            await i.followup.send(embed=e,file=discord.File(ef,fn))
        else:
            if not msg:msg=resp
            ch=split_msg(msg)
            await i.followup.send(f"**🤖 {used}:**\n{ch[0]}")
            for c in ch[1:]:await i.channel.send(c)
    except Exception as ex:
        await i.followup.send(f"❌ {ex}")
@bot.tree.command(name="dump",description="🔓 Dump")
@app_commands.describe(url="URL",mode="Mode")
@app_commands.choices(mode=[app_commands.Choice(name="Auto",value="auto"),app_commands.Choice(name="Stealth",value="stealth"),app_commands.Choice(name="Aggressive",value="aggressive")])
@rate(8)
@noban()
async def slash_dump(i:discord.Interaction,url:str,mode:str="auto"):
    await i.response.defer()
    try:
        content,ua,_,_=await process_dump_request(url,mode)
        if not content:return await i.followup.send("💀 Failed!")
        ext="lua";status="✅";color=0x00FF00
        if"<!DOCTYPE"in content[:500]:ext="html";color=0xFFFF00;status="⚠️ HTML"
        elif content.strip().startswith("{"):ext="json";status="📋"
        e=discord.Embed(title="🔓 Dump",description=status,color=color)
        e.add_field(name="Size",value=f"`{len(content):,}b`")
        db.stat("dump",i.user.id)
        await i.followup.send(embed=e,file=discord.File(io.BytesIO(content.encode()),f"dump.{ext}"))
    except Exception as ex:await i.followup.send(f"💀 {ex}")
@bot.tree.command(name="clear",description="🧹 Clear memory")
async def slash_clear(i:discord.Interaction):
    mem.clear(i.user.id)
    await i.response.send_message("🧹 Cleared!",ephemeral=True)
@bot.tree.command(name="ping",description="🏓 Ping")
async def slash_ping(i:discord.Interaction):
    await i.response.send_message(f"🏓 `{round(bot.latency*1000)}ms`")
@bot.tree.command(name="help",description="📚 Help")
async def slash_help(i:discord.Interaction):
    await i.response.send_message(f"📚 Use `{PREFIX}help` for full guide!")
@bot.tree.command(name="testai",description="🔧 Test AI")
@owner()
async def slash_testai(i:discord.Interaction):
    await i.response.defer()
    results=[]
    test=[{"role":"user","content":"Say: OK"}]
    for n,f in[("Groq",lambda:call_groq(test)),("Cerebras",lambda:call_cerebras(test)),("Claude",lambda:call_claude(test)),("OR-Llama",lambda:call_openrouter(test,"llama")),("OR-Gemini",lambda:call_openrouter(test,"gemini"))]:
        try:
            r=f()
            results.append(f"{'✅'if r else'❌'} **{n}**: {r[:25] if r else'Fail'}")
        except:results.append(f"❌ **{n}**: Error")
    await i.followup.send(embed=discord.Embed(title="🔧 Test",description="\n".join(results),color=0x3498DB))
@bot.tree.command(name="reload",description="🔄 Sync")
@owner()
async def slash_reload(i:discord.Interaction):
    await i.response.defer()
    try:s=await bot.tree.sync();await i.followup.send(f"✅ {len(s)}")
    except Exception as e:await i.followup.send(f"❌ {e}")
if __name__=="__main__":
    keep_alive()
    print("🚀 Starting...")
    print(f"📦 Prefix: {PREFIX}")
    claude_count=len([k for k in[KEY_CLAUDE_1,KEY_CLAUDE_2]if k])
    print(f"📦 Groq{'✅'if KEY_GROQ else'❌'} Cerebras{'✅'if KEY_CEREBRAS else'❌'} Claude({claude_count}) OR{'✅'if KEY_OPENROUTER else'❌'}")
    try:bot.run(DISCORD_TOKEN,log_handler=None)
    except Exception as e:print(f"❌ {e}")
