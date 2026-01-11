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
if not DISCORD_TOKEN:exit(1)
intents=discord.Intents.default()
intents.message_content=True
bot=commands.Bot(command_prefix=PREFIX,intents=intents,help_command=None)
UA_LIST=["Roblox/WinInet","Synapse-X/2.0","Sentinel/3.0","Krnl/1.0","Fluxus/1.0","ScriptWare/2.0"]
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
        from curl_cffi import requests as r
        _curl=r
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
        import pandas
        _pd=pandas
    return _pd
def get_openpyxl():
    global _openpyxl
    if _openpyxl is None:
        import openpyxl
        _openpyxl=openpyxl
    return _openpyxl
class Database:
    def __init__(self,p="bot.db"):
        self.conn=sqlite3.connect(p,check_same_thread=False)
        self.conn.executescript('CREATE TABLE IF NOT EXISTS user_prefs(uid INTEGER PRIMARY KEY,model TEXT DEFAULT "auto");CREATE TABLE IF NOT EXISTS stats(id INTEGER PRIMARY KEY,cmd TEXT,uid INTEGER,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);CREATE TABLE IF NOT EXISTS blacklist(uid INTEGER PRIMARY KEY);')
    def get_model(self,uid):
        r=self.conn.execute('SELECT model FROM user_prefs WHERE uid=?',(uid,)).fetchone()
        return r[0]if r else"auto"
    def set_model(self,uid,m):
        self.conn.execute('INSERT OR REPLACE INTO user_prefs VALUES(?,?)',(uid,m))
        self.conn.commit()
    def stat(self,c,u):
        self.conn.execute('INSERT INTO stats(cmd,uid)VALUES(?,?)',(c,u))
        self.conn.commit()
    def banned(self,u):return self.conn.execute('SELECT 1 FROM blacklist WHERE uid=?',(u,)).fetchone()is not None
db=Database()
class RL:
    def __init__(self):self.cd=defaultdict(lambda:defaultdict(float))
    def ok(self,u,c,t=5):
        n=time.time()
        if n-self.cd[u][c]<t:return False,t-(n-self.cd[u][c])
        self.cd[u][c]=n
        return True,0
rl=RL()
@dataclass
class Msg:
    role:str
    content:str
    ts:float
class Memory:
    def __init__(self):self.d=defaultdict(list)
    def add(self,u,r,c):
        n=time.time()
        self.d[u]=[m for m in self.d[u]if n-m.ts<1800]
        self.d[u].append(Msg(r,c[:1500],n))
        if len(self.d[u])>15:self.d[u]=self.d[u][-15:]
    def get(self,u):
        n=time.time()
        self.d[u]=[m for m in self.d[u]if n-m.ts<1800]
        return[{"role":m.role,"content":m.content}for m in self.d[u]]
    def clear(self,u):self.d[u]=[]
mem=Memory()
def rate(s=5):
    async def p(i:discord.Interaction)->bool:
        ok,r=rl.ok(i.user.id,i.command.name,s)
        if not ok:
            await i.response.send_message(f"⏳ {r:.0f}s",ephemeral=True)
            return False
        return True
    return app_commands.check(p)
def owner():
    async def p(i:discord.Interaction)->bool:
        if i.user.id not in OWNER_IDS:
            await i.response.send_message("❌",ephemeral=True)
            return False
        return True
    return app_commands.check(p)
class ExcelGen:
    @staticmethod
    def create(data)->io.BytesIO:
        try:
            openpyxl=get_openpyxl()
            from openpyxl.styles import Font,PatternFill,Border,Side,Alignment
            from openpyxl.utils import get_column_letter
            wb=openpyxl.Workbook()
            wb.remove(wb.active)
            sheets=data.get("sheets",[])
            if not sheets:
                sheets=[{"name":"Sheet1","headers":data.get("headers",[]),"data":data.get("data",[])}]
            for sh in sheets:
                name=str(sh.get("name","Sheet1"))[:31]
                ws=wb.create_sheet(title=name)
                headers=sh.get("headers",[])
                rows=sh.get("data",[])
                hfill=PatternFill(start_color="4472C4",end_color="4472C4",fill_type="solid")
                hfont=Font(bold=True,color="FFFFFF",size=11)
                border=Border(left=Side(style='thin'),right=Side(style='thin'),top=Side(style='thin'),bottom=Side(style='thin'))
                for ci,h in enumerate(headers,1):
                    c=ws.cell(row=1,column=ci,value=str(h))
                    c.font=hfont
                    c.fill=hfill
                    c.border=border
                    c.alignment=Alignment(horizontal='center',vertical='center')
                for ri,row in enumerate(rows,2):
                    if not isinstance(row,(list,tuple)):row=[row]
                    for ci,val in enumerate(row,1):
                        try:
                            if isinstance(val,str)and val.replace('.','').replace('-','').isdigit():
                                val=float(val)if'.'in val else int(val)
                        except:pass
                        c=ws.cell(row=ri,column=ci,value=val)
                        c.border=border
                        if isinstance(val,(int,float)):
                            c.number_format='#,##0'if isinstance(val,int)else'#,##0.00'
                for ci in range(1,len(headers)+1):
                    col=get_column_letter(ci)
                    max_len=len(str(headers[ci-1]))if ci<=len(headers)else 10
                    for row in rows:
                        if isinstance(row,(list,tuple))and ci<=len(row):
                            max_len=max(max_len,len(str(row[ci-1])))
                    ws.column_dimensions[col].width=min(max(max_len+3,12),50)
                ws.freeze_panes='A2'
            out=io.BytesIO()
            wb.save(out)
            out.seek(0)
            logger.info("Excel generated successfully")
            return out
        except Exception as e:
            logger.error(f"Excel generation error: {e}")
            raise
excel=ExcelGen()
SYSTEM_PROMPT='''Kamu adalah Excel Expert AI. WAJIB jawab dalam format JSON yang valid.

ATURAN KETAT:
1. Output HANYA JSON, tanpa teks lain
2. Semua angka harus berupa NUMBER (bukan string)
3. Gunakan double quotes untuk string

FORMAT untuk membuat Excel:
{"action":"generate_excel","message":"Deskripsi file","excel_data":{"sheets":[{"name":"NamaSheet","headers":["Kolom1","Kolom2"],"data":[["Isi1",100],["Isi2",200]]}],"filename":"nama_file.xlsx"}}

FORMAT untuk jawab pertanyaan:
{"action":"text_only","message":"Jawaban kamu disini"}

CONTOH BENAR untuk Excel:
{"action":"generate_excel","message":"Laporan Penjualan","excel_data":{"sheets":[{"name":"Penjualan","headers":["Produk","Qty","Harga","Total"],"data":[["Laptop",5,15000000,75000000],["Mouse",20,150000,3000000]]}],"filename":"laporan_penjualan.xlsx"}}

Jawab dalam Bahasa Indonesia.'''
OR_MODELS={"llama":"meta-llama/llama-3.3-70b-instruct:free","gemini":"google/gemini-2.0-flash-exp:free","qwen":"qwen/qwen3-32b:free","deepseek":"deepseek/deepseek-chat-v3-0324:free"}
CF_MODELS={"llama":"@cf/meta/llama-3.1-8b-instruct","mistral":"@cf/mistral/mistral-7b-instruct-v0.1"}
MODEL_NAMES={"auto":"🚀 Auto","groq":"⚡ Groq","cerebras":"🧠 Cerebras","cloudflare":"☁️ Cloudflare","sambanova":"🦣 SambaNova","cohere":"🔷 Cohere","or_llama":"🦙 OR-Llama","or_gemini":"🔵 OR-Gemini","or_qwen":"🟣 OR-Qwen"}
def call_groq(msgs):
    cl=get_groq()
    if not cl:return None
    try:
        r=cl.chat.completions.create(messages=msgs,model="llama-3.3-70b-versatile",temperature=0.1,max_tokens=4000)
        return r.choices[0].message.content
    except Exception as e:
        logger.error(f"Groq: {e}")
        return None
def call_cerebras(msgs):
    if not KEY_CEREBRAS:return None
    try:
        r=get_requests().post("https://api.cerebras.ai/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_CEREBRAS}","Content-Type":"application/json"},json={"model":"llama-3.3-70b","messages":msgs,"temperature":0.1,"max_tokens":4000},timeout=30)
        if r.status_code==200:return r.json()["choices"][0]["message"]["content"]
        return None
    except Exception as e:
        logger.error(f"Cerebras: {e}")
        return None
def call_openrouter(msgs,mk="llama"):
    if not KEY_OPENROUTER:return None
    try:
        mid=OR_MODELS.get(mk,OR_MODELS["llama"])
        r=get_requests().post("https://openrouter.ai/api/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_OPENROUTER}","Content-Type":"application/json","HTTP-Referer":"https://github.com"},json={"model":mid,"messages":msgs,"temperature":0.1,"max_tokens":4000},timeout=60)
        if r.status_code==200:
            data=r.json()
            if"choices"in data and data["choices"]:
                return data["choices"][0]["message"]["content"]
        logger.error(f"OR {mk}: {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"OR: {e}")
        return None
def call_cloudflare(msgs):
    if not CF_ACCOUNT_ID or not CF_API_TOKEN:return None
    try:
        model=CF_MODELS["llama"]
        url=f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{model}"
        r=get_requests().post(url,headers={"Authorization":f"Bearer {CF_API_TOKEN}","Content-Type":"application/json"},json={"messages":msgs,"max_tokens":2000},timeout=60)
        if r.status_code==200:
            data=r.json()
            if data.get("success")and"result"in data:
                return data["result"].get("response","")
        return None
    except Exception as e:
        logger.error(f"CF: {e}")
        return None
def call_sambanova(msgs):
    if not KEY_SAMBANOVA:return None
    try:
        r=get_requests().post("https://api.sambanova.ai/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_SAMBANOVA}","Content-Type":"application/json"},json={"model":"Meta-Llama-3.3-70B-Instruct","messages":msgs,"temperature":0.1,"max_tokens":4000},timeout=60)
        if r.status_code==200:return r.json()["choices"][0]["message"]["content"]
        return None
    except Exception as e:
        logger.error(f"SN: {e}")
        return None
def call_cohere(msgs):
    if not KEY_COHERE:return None
    try:
        preamble=""
        user_msg=""
        hist=[]
        for m in msgs:
            if m["role"]=="system":preamble=m["content"]
            elif m["role"]=="user":
                if user_msg:hist.append({"role":"USER","message":user_msg})
                user_msg=m["content"]
            elif m["role"]=="assistant":hist.append({"role":"CHATBOT","message":m["content"]})
        payload={"model":"command-r-plus-08-2024","message":user_msg,"temperature":0.1}
        if preamble:payload["preamble"]=preamble
        if hist:payload["chat_history"]=hist
        r=get_requests().post("https://api.cohere.com/v1/chat",headers={"Authorization":f"Bearer {KEY_COHERE}","Content-Type":"application/json"},json=payload,timeout=60)
        if r.status_code==200:return r.json().get("text","")
        return None
    except Exception as e:
        logger.error(f"Cohere: {e}")
        return None
def fix_json(text):
    text=text.strip()
    if text.startswith("```"):
        m=re.search(r'```(?:json)?\s*([\s\S]*?)\s*```',text)
        if m:text=m.group(1).strip()
    text=re.sub(r',\s*([}\]])',r'\1',text)
    text=re.sub(r'(\d)"(\s*[,\}\]])',r'\1\2',text)
    text=re.sub(r'"\s*\+\s*"','',text)
    ob,cb=text.count('{'),text.count('}')
    if ob>cb:text+='}'*(ob-cb)
    osb,csb=text.count('['),text.count(']')
    if osb>csb:text+=']'*(osb-csb)
    return text
def parse_response(resp):
    if not resp:
        return{"action":"text_only","message":"Tidak ada response dari AI"}
    resp=resp.strip()
    resp=fix_json(resp)
    try:
        return json.loads(resp)
    except:pass
    try:
        m=re.search(r'(\{[\s\S]*\})',resp)
        if m:
            jtext=fix_json(m.group(1))
            return json.loads(jtext)
    except:pass
    return{"action":"text_only","message":resp[:1800]}
def call_ai(model,msgs,prompt):
    if model=="groq":return call_groq(msgs),"Groq"
    elif model=="cerebras":return call_cerebras(msgs),"Cerebras"
    elif model=="cloudflare":return call_cloudflare(msgs),"Cloudflare"
    elif model=="sambanova":return call_sambanova(msgs),"SambaNova"
    elif model=="cohere":return call_cohere(msgs),"Cohere"
    elif model.startswith("or_"):
        mk=model[3:]
        return call_openrouter(msgs,mk),f"OR-{mk}"
    return None,"none"
def ask_ai(prompt,uid=None,model=None):
    if not model or model=="auto":
        model=db.get_model(uid)if uid else"auto"
    if uid and model!="auto":
        db.set_model(uid,model)
    msgs=[{"role":"system","content":SYSTEM_PROMPT}]
    if uid:
        hist=mem.get(uid)
        if hist:msgs.extend(hist[-6:])
    msgs.append({"role":"user","content":prompt})
    result=None
    used="none"
    if model!="auto":
        result,used=call_ai(model,msgs,prompt)
        if not result:
            for fn,nm in[(lambda:call_groq(msgs),"Groq"),(lambda:call_cerebras(msgs),"Cerebras"),(lambda:call_openrouter(msgs,"llama"),"OR-llama")]:
                result=fn()
                if result:
                    used=f"{nm}(fb)"
                    break
    else:
        for fn,nm in[(lambda:call_groq(msgs),"Groq"),(lambda:call_cerebras(msgs),"Cerebras"),(lambda:call_cloudflare(msgs),"CF"),(lambda:call_openrouter(msgs,"llama"),"OR"),(lambda:call_sambanova(msgs),"SN"),(lambda:call_cohere(msgs),"Cohere")]:
            try:
                result=fn()
                if result:
                    used=nm
                    break
            except:continue
    if not result:
        return{"action":"text_only","message":"❌ Semua AI tidak tersedia"},"none"
    if uid:
        mem.add(uid,"user",prompt[:500])
        mem.add(uid,"assistant",result[:500])
    parsed=parse_response(result)
    return parsed,used
def split_msg(text,limit=1900):
    if not text:return["(kosong)"]
    text=str(text)[:3800]
    if len(text)<=limit:return[text]
    chunks=[]
    while text:
        if len(text)<=limit:
            chunks.append(text)
            break
        idx=text.rfind('\n',0,limit)
        if idx<=0:idx=text.rfind(' ',0,limit)
        if idx<=0:idx=limit
        chunks.append(text[:idx])
        text=text[idx:].lstrip()
    return chunks if chunks else["(kosong)"]
async def handle_ai_response(ctx_or_msg,parsed,used,is_reply=True):
    """Handle AI response - generate Excel or send text"""
    try:
        action=parsed.get("action","text_only")
        message=parsed.get("message","")
        if action=="generate_excel":
            excel_data=parsed.get("excel_data",{})
            filename=excel_data.get("filename","output.xlsx")
            if not filename.endswith('.xlsx'):
                filename+='.xlsx'
            try:
                file_buffer=excel.create(excel_data)
                embed=discord.Embed(title="📊 Excel Dibuat!",description=message[:500]if message else"File Excel berhasil dibuat",color=0x217346)
                embed.add_field(name="📁 File",value=f"`{filename}`",inline=True)
                embed.add_field(name="🤖 Model",value=f"`{used}`",inline=True)
                sheets=excel_data.get("sheets",[])
                if sheets:
                    total_rows=sum(len(s.get("data",[]))for s in sheets)
                    embed.add_field(name="📋 Data",value=f"`{len(sheets)} sheet, {total_rows} baris`",inline=True)
                embed.set_footer(text="Excel Expert AI")
                if is_reply:
                    await ctx_or_msg.reply(embed=embed,file=discord.File(file_buffer,filename))
                else:
                    await ctx_or_msg.followup.send(embed=embed,file=discord.File(file_buffer,filename))
                return True
            except Exception as e:
                logger.error(f"Excel error: {e}")
                error_msg=f"❌ Gagal membuat Excel: `{str(e)[:100]}`\n\nData yang diterima:\n```json\n{json.dumps(excel_data,indent=2,ensure_ascii=False)[:500]}```"
                if is_reply:
                    await ctx_or_msg.reply(error_msg)
                else:
                    await ctx_or_msg.followup.send(error_msg)
                return False
        else:
            if not message:
                message=str(parsed)[:1500]
            chunks=split_msg(message)
            embed=discord.Embed(color=0x5865F2)
            embed.set_footer(text=f"🤖 {used}")
            if is_reply:
                await ctx_or_msg.reply(content=chunks[0],embed=embed if len(chunks)==1 else None)
                for c in chunks[1:]:
                    await ctx_or_msg.channel.send(c)
            else:
                await ctx_or_msg.followup.send(content=chunks[0],embed=embed if len(chunks)==1 else None)
                for c in chunks[1:]:
                    await ctx_or_msg.channel.send(c)
            return True
    except discord.HTTPException as e:
        logger.error(f"Discord HTTP error: {e}")
        try:
            if is_reply:
                await ctx_or_msg.reply(f"❌ Error Discord: `{str(e)[:100]}`")
            else:
                await ctx_or_msg.followup.send(f"❌ Error Discord: `{str(e)[:100]}`")
        except:pass
        return False
    except Exception as e:
        logger.error(f"Response handler error: {e}")
        return False
@bot.event
async def on_ready():
    logger.info(f'🔥 {bot.user} | {len(bot.guilds)} servers')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching,name=f"{PREFIX}help"))
    try:
        await bot.tree.sync()
        logger.info("✅ Commands synced")
    except Exception as e:
        logger.error(f"Sync error: {e}")
@bot.event
async def on_message(msg):
    if msg.author.bot:return
    if bot.user.mentioned_in(msg)and not msg.mention_everyone:
        content=msg.content.replace(f'<@{bot.user.id}>','').replace(f'<@!{bot.user.id}>','').strip()
        if content:
            if db.banned(msg.author.id):
                return await msg.reply("🚫 Kamu diblokir")
            ok,remaining=rl.ok(msg.author.id,"mention",5)
            if not ok:
                return await msg.reply(f"⏳ Tunggu {remaining:.0f}s")
            async with msg.channel.typing():
                try:
                    user_model=db.get_model(msg.author.id)
                    parsed,used=ask_ai(content,msg.author.id,user_model)
                    await handle_ai_response(msg,parsed,used,is_reply=True)
                    db.stat("ai",msg.author.id)
                except Exception as e:
                    logger.error(f"Mention error: {e}")
                    await msg.reply(f"❌ Error: `{str(e)[:100]}`")
        else:
            model=db.get_model(msg.author.id)
            await msg.reply(f"👋 Hai! Model kamu: **{MODEL_NAMES.get(model,model)}**\n\nKetik pertanyaan setelah mention!")
        return
    await bot.process_commands(msg)
@bot.command(name="ai",aliases=["ask","chat"])
async def cmd_ai(ctx,*,prompt:str=None):
    if db.banned(ctx.author.id):return
    ok,r=rl.ok(ctx.author.id,"ai",8)
    if not ok:
        return await ctx.reply(f"⏳ Tunggu {r:.0f}s")
    if not prompt:
        return await ctx.reply(f"❌ Gunakan: `{PREFIX}ai <pertanyaan>`")
    async with ctx.typing():
        try:
            user_model=db.get_model(ctx.author.id)
            parsed,used=ask_ai(prompt,ctx.author.id,user_model)
            await handle_ai_response(ctx.message,parsed,used,is_reply=True)
            db.stat("ai",ctx.author.id)
        except Exception as e:
            logger.error(f"AI cmd error: {e}")
            await ctx.reply(f"❌ Error: `{str(e)[:100]}`")
@bot.command(name="excel",aliases=["buat","create"])
async def cmd_excel(ctx,*,prompt:str=None):
    """Command khusus untuk membuat Excel"""
    if db.banned(ctx.author.id):return
    ok,r=rl.ok(ctx.author.id,"excel",10)
    if not ok:
        return await ctx.reply(f"⏳ Tunggu {r:.0f}s")
    if not prompt:
        return await ctx.reply(f"❌ Gunakan: `{PREFIX}excel <deskripsi>`\nContoh: `{PREFIX}excel buat laporan keuangan bulanan`")
    enhanced_prompt=f"BUAT FILE EXCEL untuk: {prompt}\n\nWAJIB output format generate_excel dengan data yang lengkap dan profesional."
    async with ctx.typing():
        try:
            user_model=db.get_model(ctx.author.id)
            parsed,used=ask_ai(enhanced_prompt,ctx.author.id,user_model)
            if parsed.get("action")!="generate_excel":
                await ctx.reply(f"⚠️ AI tidak menghasilkan Excel. Coba lagi dengan deskripsi lebih spesifik.\n\nResponse: {parsed.get('message','')[:300]}")
                return
            await handle_ai_response(ctx.message,parsed,used,is_reply=True)
            db.stat("excel",ctx.author.id)
        except Exception as e:
            logger.error(f"Excel cmd error: {e}")
            await ctx.reply(f"❌ Error: `{str(e)[:100]}`")
@bot.command(name="model",aliases=["m"])
async def cmd_model(ctx,model:str=None):
    valid=list(MODEL_NAMES.keys())
    if not model:
        current=db.get_model(ctx.author.id)
        e=discord.Embed(title="🤖 Model AI",color=0x3498DB)
        e.add_field(name="Model Kamu",value=f"**{MODEL_NAMES.get(current,current)}**",inline=False)
        e.add_field(name="Tersedia",value="\n".join([f"`{k}` - {v}"for k,v in MODEL_NAMES.items()]),inline=False)
        e.add_field(name="Cara Ganti",value=f"`{PREFIX}model <nama>`\nContoh: `{PREFIX}model cerebras`",inline=False)
        return await ctx.reply(embed=e)
    model=model.lower()
    if model not in valid:
        return await ctx.reply(f"❌ Model tidak valid!\n\nPilihan: `{', '.join(valid)}`")
    db.set_model(ctx.author.id,model)
    await ctx.reply(f"✅ Model diubah ke: **{MODEL_NAMES.get(model,model)}**")
@bot.command(name="clear",aliases=["reset"])
async def cmd_clear(ctx):
    mem.clear(ctx.author.id)
    await ctx.reply("🧹 Memory percakapan dihapus!")
@bot.command(name="ping")
async def cmd_ping(ctx):
    model=db.get_model(ctx.author.id)
    mem_count=len(mem.get(ctx.author.id))
    e=discord.Embed(title="🏓 Pong!",color=0x00FF00)
    e.add_field(name="Latency",value=f"`{round(bot.latency*1000)}ms`")
    e.add_field(name="Model",value=f"`{MODEL_NAMES.get(model,model)}`")
    e.add_field(name="Memory",value=f"`{mem_count} pesan`")
    await ctx.reply(embed=e)
@bot.command(name="help",aliases=["h"])
async def cmd_help(ctx):
    model=db.get_model(ctx.author.id)
    e=discord.Embed(title="📚 Excel AI Bot",description=f"Model kamu: **{MODEL_NAMES.get(model,model)}**",color=0x217346)
    e.add_field(name="🤖 AI Chat",value=f"`{PREFIX}ai <pertanyaan>` - Tanya AI\n`@{bot.user.name} <pertanyaan>` - Via mention",inline=False)
    e.add_field(name="📊 Excel",value=f"`{PREFIX}excel <deskripsi>` - Buat file Excel\nContoh: `{PREFIX}excel buat invoice perusahaan`",inline=False)
    e.add_field(name="⚙️ Settings",value=f"`{PREFIX}model` - Lihat/ganti model AI\n`{PREFIX}clear` - Hapus memory chat",inline=False)
    e.add_field(name="🔓 Script",value=f"`{PREFIX}dump <url>` - Download script",inline=False)
    await ctx.reply(embed=e)
@bot.command(name="dump")
async def cmd_dump(ctx,url:str=None,mode:str="auto"):
    if not url:
        return await ctx.reply(f"❌ Gunakan: `{PREFIX}dump <url>`")
    ok,r=rl.ok(ctx.author.id,"dump",8)
    if not ok:
        return await ctx.reply(f"⏳ Tunggu {r:.0f}s")
    async with ctx.typing():
        try:
            curl=get_curl()
            ua=random.choice(UA_LIST)
            headers={"User-Agent":ua,"Roblox-Place-Id":"2753915549","Accept":"*/*"}
            r=curl.get(url,impersonate="chrome110",headers=headers,timeout=20)
            content=r.text
            ext="lua"
            if"<!DOCTYPE"in content[:300]:ext="html"
            elif content.strip().startswith("{"):ext="json"
            e=discord.Embed(title="🔓 Dump Result",color=0x00FF00 if ext=="lua"else 0xFFFF00)
            e.add_field(name="Size",value=f"`{len(content):,} bytes`")
            e.add_field(name="Type",value=f"`.{ext}`")
            e.add_field(name="UA",value=f"`{ua[:20]}...`")
            db.stat("dump",ctx.author.id)
            await ctx.reply(embed=e,file=discord.File(io.BytesIO(content.encode()),f"dump.{ext}"))
        except Exception as e:
            await ctx.reply(f"💀 Error: `{str(e)[:100]}`")
@bot.command(name="testai")
@commands.is_owner()
async def cmd_testai(ctx):
    async with ctx.typing():
        results=[]
        test_msgs=[{"role":"user","content":"Respond with exactly: OK"}]
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
                status="✅"if r else"❌"
                preview=r[:30].strip()if r else"Failed"
                results.append(f"{status} **{name}**: {preview}")
            except Exception as e:
                results.append(f"❌ **{name}**: {str(e)[:20]}")
        e=discord.Embed(title="🔧 AI Provider Test",description="\n".join(results),color=0x3498DB)
        await ctx.reply(embed=e)
@bot.tree.command(name="ai",description="Tanya AI")
@app_commands.describe(prompt="Pertanyaan atau perintah")
@rate(8)
async def slash_ai(i:discord.Interaction,prompt:str):
    await i.response.defer()
    try:
        user_model=db.get_model(i.user.id)
        parsed,used=ask_ai(prompt,i.user.id,user_model)
        await handle_ai_response(i,parsed,used,is_reply=False)
        db.stat("ai",i.user.id)
    except Exception as e:
        await i.followup.send(f"❌ Error: `{str(e)[:100]}`")
@bot.tree.command(name="excel",description="Buat file Excel")
@app_commands.describe(deskripsi="Deskripsi Excel yang ingin dibuat")
@rate(10)
async def slash_excel(i:discord.Interaction,deskripsi:str):
    await i.response.defer()
    enhanced=f"BUAT FILE EXCEL untuk: {deskripsi}\n\nWAJIB output format generate_excel."
    try:
        user_model=db.get_model(i.user.id)
        parsed,used=ask_ai(enhanced,i.user.id,user_model)
        await handle_ai_response(i,parsed,used,is_reply=False)
        db.stat("excel",i.user.id)
    except Exception as e:
        await i.followup.send(f"❌ Error: `{str(e)[:100]}`")
@bot.tree.command(name="model",description="Set model AI")
@app_commands.describe(model="Pilih model")
@app_commands.choices(model=[app_commands.Choice(name=v,value=k)for k,v in MODEL_NAMES.items()])
async def slash_model(i:discord.Interaction,model:str=None):
    if model:
        db.set_model(i.user.id,model)
        await i.response.send_message(f"✅ Model: **{MODEL_NAMES.get(model,model)}**",ephemeral=True)
    else:
        current=db.get_model(i.user.id)
        await i.response.send_message(f"🤖 Model: **{MODEL_NAMES.get(current,current)}**",ephemeral=True)
@bot.tree.command(name="clear",description="Hapus memory chat")
async def slash_clear(i:discord.Interaction):
    mem.clear(i.user.id)
    await i.response.send_message("🧹 Memory dihapus!",ephemeral=True)
@bot.tree.command(name="ping",description="Cek status bot")
async def slash_ping(i:discord.Interaction):
    await i.response.send_message(f"🏓 `{round(bot.latency*1000)}ms`")
@bot.tree.command(name="reload",description="Sync commands")
@owner()
async def slash_reload(i:discord.Interaction):
    await i.response.defer()
    try:
        s=await bot.tree.sync()
        await i.followup.send(f"✅ {len(s)} commands synced")
    except Exception as e:
        await i.followup.send(f"❌ {e}")
if __name__=="__main__":
    keep_alive()
    print("🚀 Excel AI Bot Starting...")
    print(f"📦 Prefix: {PREFIX}")
    cf="✅"if CF_ACCOUNT_ID and CF_API_TOKEN else"❌"
    print(f"🔑 Groq{'✅'if KEY_GROQ else'❌'} Cerebras{'✅'if KEY_CEREBRAS else'❌'} CF{cf} OR{'✅'if KEY_OPENROUTER else'❌'}")
    try:
        bot.run(DISCORD_TOKEN,log_handler=None)
    except Exception as e:
        print(f"❌ {e}")
