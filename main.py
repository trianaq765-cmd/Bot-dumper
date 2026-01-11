import discord,os,io,re,time,json,logging,sqlite3,random,threading
from collections import defaultdict
from dataclasses import dataclass
from discord import app_commands
from discord.ext import commands

try:
    from keep_alive import keep_alive
except:
    keep_alive=lambda:None

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

if not DISCORD_TOKEN:exit(1)

intents=discord.Intents.default()
intents.message_content=True
bot=commands.Bot(command_prefix=PREFIX,intents=intents,help_command=None)

_groq=_requests=_curl=None

def get_groq():
    global _groq
    if _groq is None and KEY_GROQ:
        from groq import Groq
        _groq=Groq(api_key=KEY_GROQ)
    return _groq

def get_requests():
    global _requests
    if _requests is None:
        import requests
        _requests=requests
    return _requests

def get_curl():
    global _curl
    if _curl is None:
        from curl_cffi import requests as r
        _curl=r
    return _curl

class Database:
    def __init__(self,path="bot.db"):
        self.conn=sqlite3.connect(path,check_same_thread=False)
        self.lock=threading.Lock()
        self.conn.executescript('''CREATE TABLE IF NOT EXISTS user_prefs(uid INTEGER PRIMARY KEY,model TEXT DEFAULT "auto");
CREATE TABLE IF NOT EXISTS stats(id INTEGER PRIMARY KEY,cmd TEXT,uid INTEGER,ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS blacklist(uid INTEGER PRIMARY KEY);''')
    def get_model(self,uid):
        with self.lock:
            r=self.conn.execute('SELECT model FROM user_prefs WHERE uid=?',(uid,)).fetchone()
            return r[0]if r else"auto"
    def set_model(self,uid,model):
        with self.lock:
            self.conn.execute('INSERT OR REPLACE INTO user_prefs VALUES(?,?)',(uid,model))
            self.conn.commit()
    def stat(self,cmd,uid):
        with self.lock:
            self.conn.execute('INSERT INTO stats(cmd,uid)VALUES(?,?)',(cmd,uid))
            self.conn.commit()
    def banned(self,uid):
        with self.lock:
            return self.conn.execute('SELECT 1 FROM blacklist WHERE uid=?',(uid,)).fetchone()is not None

db=Database()

class RateLimiter:
    def __init__(self):
        self.cd=defaultdict(lambda:defaultdict(float))
        self.lock=threading.Lock()
    def check(self,uid,cmd,t=5):
        with self.lock:
            now=time.time()
            if now-self.cd[uid][cmd]<t:
                return False,t-(now-self.cd[uid][cmd])
            self.cd[uid][cmd]=now
            return True,0

rl=RateLimiter()

@dataclass
class Msg:
    role:str
    content:str
    ts:float

class Memory:
    def __init__(self):
        self.data=defaultdict(list)
        self.lock=threading.Lock()
    def add(self,uid,role,content):
        with self.lock:
            now=time.time()
            self.data[uid]=[m for m in self.data[uid]if now-m.ts<1800]
            self.data[uid].append(Msg(role,content[:1500],now))
            if len(self.data[uid])>10:self.data[uid]=self.data[uid][-10:]
    def get(self,uid):
        with self.lock:
            now=time.time()
            self.data[uid]=[m for m in self.data[uid]if now-m.ts<1800]
            return[{"role":m.role,"content":m.content}for m in self.data[uid]]
    def clear(self,uid):
        with self.lock:self.data[uid]=[]

mem=Memory()

SYSTEM_PROMPT='''Kamu adalah AI Assistant yang membantu pengguna dalam berbagai hal. Kamu ramah, sopan, dan informatif. Jawab dalam Bahasa Indonesia kecuali diminta lain.'''

OR_MODELS={"llama":"meta-llama/llama-3.3-70b-instruct:free","gemini":"google/gemini-2.0-flash-exp:free","qwen":"qwen/qwen-2.5-72b-instruct","deepseek":"deepseek/deepseek-r1"}
MODEL_NAMES={"auto":"🚀 Auto","groq":"⚡ Groq","cerebras":"🧠 Cerebras","sambanova":"🦣 SambaNova","cohere":"🔷 Cohere","or_llama":"🦙 OR-Llama","or_gemini":"🔵 OR-Gemini","or_qwen":"🟣 OR-Qwen","or_deepseek":"🌊 OR-DeepSeek"}
UA_LIST=["Roblox/WinInet","Synapse-X/2.0","Sentinel/3.0","Krnl/1.0","Fluxus/1.0"]

def call_groq(msgs):
    cl=get_groq()
    if not cl:return None
    try:
        r=cl.chat.completions.create(messages=msgs,model="llama-3.3-70b-versatile",temperature=0.7,max_tokens=2000)
        return r.choices[0].message.content
    except Exception as e:
        logger.error(f"Groq:{e}")
        return None

def call_cerebras(msgs):
    if not KEY_CEREBRAS:return None
    try:
        r=get_requests().post("https://api.cerebras.ai/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_CEREBRAS}","Content-Type":"application/json"},json={"model":"llama-3.3-70b","messages":msgs,"temperature":0.7,"max_tokens":2000},timeout=30)
        if r.status_code==200:return r.json()["choices"][0]["message"]["content"]
        return None
    except Exception as e:
        logger.error(f"Cerebras:{e}")
        return None

def call_openrouter(msgs,mk="llama"):
    if not KEY_OPENROUTER:return None
    try:
        mid=OR_MODELS.get(mk,OR_MODELS["llama"])
        r=get_requests().post("https://openrouter.ai/api/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_OPENROUTER}","Content-Type":"application/json","HTTP-Referer":"https://github.com"},json={"model":mid,"messages":msgs,"temperature":0.7,"max_tokens":2000},timeout=60)
        if r.status_code==200:
            data=r.json()
            if"choices"in data and data["choices"]:return data["choices"][0]["message"]["content"]
        logger.error(f"OR {mk}:{r.status_code}")
        return None
    except Exception as e:
        logger.error(f"OR:{e}")
        return None

def call_sambanova(msgs):
    if not KEY_SAMBANOVA:return None
    try:
        r=get_requests().post("https://api.sambanova.ai/v1/chat/completions",headers={"Authorization":f"Bearer {KEY_SAMBANOVA}","Content-Type":"application/json"},json={"model":"Meta-Llama-3.3-70B-Instruct","messages":msgs,"temperature":0.7,"max_tokens":2000},timeout=60)
        if r.status_code==200:return r.json()["choices"][0]["message"]["content"]
        return None
    except Exception as e:
        logger.error(f"SN:{e}")
        return None

def call_cohere(msgs):
    if not KEY_COHERE:return None
    try:
        preamble=""
        hist=[]
        messages=[]
        for m in msgs:
            if m["role"]=="system":preamble=m["content"]
            else:messages.append(m)
        for m in messages[:-1]:
            role="USER"if m["role"]=="user"else"CHATBOT"
            hist.append({"role":role,"message":m["content"]})
        user_msg=messages[-1]["content"]if messages else""
        payload={"model":"command-r-plus-08-2024","message":user_msg,"temperature":0.7}
        if preamble:payload["preamble"]=preamble
        if hist:payload["chat_history"]=hist
        r=get_requests().post("https://api.cohere.com/v1/chat",headers={"Authorization":f"Bearer {KEY_COHERE}","Content-Type":"application/json"},json=payload,timeout=60)
        if r.status_code==200:return r.json().get("text","")
        return None
    except Exception as e:
        logger.error(f"Cohere:{e}")
        return None

def call_ai(model,msgs):
    if model=="groq":return call_groq(msgs),"Groq"
    elif model=="cerebras":return call_cerebras(msgs),"Cerebras"
    elif model=="sambanova":return call_sambanova(msgs),"SambaNova"
    elif model=="cohere":return call_cohere(msgs),"Cohere"
    elif model.startswith("or_"):
        mk=model[3:]
        return call_openrouter(msgs,mk),f"OR-{mk.title()}"
    return None,"none"

def ask_ai(prompt,uid=None,model=None):
    if not model or model=="auto":model=db.get_model(uid)if uid else"auto"
    if uid and model!="auto":db.set_model(uid,model)
    msgs=[{"role":"system","content":SYSTEM_PROMPT}]
    if uid:
        h=mem.get(uid)
        if h:msgs.extend(h[-6:])
    msgs.append({"role":"user","content":prompt})
    result=None
    used="none"
    if model!="auto":
        result,used=call_ai(model,msgs)
        if not result:
            for fn,nm in[(lambda:call_groq(msgs),"Groq"),(lambda:call_cerebras(msgs),"Cerebras"),(lambda:call_openrouter(msgs,"llama"),"OR-Llama")]:
                try:
                    result=fn()
                    if result:used=f"{nm}(fb)";break
                except:continue
    else:
        for fn,nm in[(lambda:call_groq(msgs),"Groq"),(lambda:call_cerebras(msgs),"Cerebras"),(lambda:call_openrouter(msgs,"llama"),"OR-Llama"),(lambda:call_sambanova(msgs),"SN"),(lambda:call_cohere(msgs),"Cohere")]:
            try:
                result=fn()
                if result:used=nm;break
            except:continue
    if not result:return"❌ Semua AI tidak tersedia","none"
    if uid:
        mem.add(uid,"user",prompt[:500])
        mem.add(uid,"assistant",result[:500])
    return result,used

def split_msg(text,limit=1900):
    if not text or not str(text).strip():return["(kosong)"]
    text=str(text).strip()[:3800]
    if len(text)<=limit:return[text]
    chunks=[]
    while text:
        if len(text)<=limit:chunks.append(text);break
        idx=text.rfind('\n',0,limit)
        if idx<=0:idx=text.rfind(' ',0,limit)
        if idx<=0:idx=limit
        chunk=text[:idx].strip()
        if chunk:chunks.append(chunk)
        text=text[idx:].lstrip()
    return chunks if chunks else["(kosong)"]

async def send_response(target,content,used,is_reply=True):
    try:
        if not content or not content.strip():content="(Response kosong)"
        chunks=split_msg(content)
        first=chunks[0]if chunks else"(kosong)"
        if not first.strip():first="(Response kosong)"
        embed=discord.Embed(color=0x5865F2)
        embed.set_footer(text=f"🤖 {used}")
        if is_reply:
            await target.reply(content=first,embed=embed if len(chunks)==1 else None)
            for c in chunks[1:]:
                if c.strip():await target.channel.send(c)
        else:
            await target.followup.send(content=first,embed=embed if len(chunks)==1 else None)
            for c in chunks[1:]:
                if c.strip():await target.channel.send(c)
        return True
    except discord.NotFound:
        logger.warning("Message was deleted")
        return False
    except discord.HTTPException as e:
        logger.error(f"Discord error:{e}")
        return False
    except Exception as e:
        logger.error(f"Send error:{e}")
        return False

@bot.event
async def on_ready():
    logger.info(f'🔥 {bot.user} online | {len(bot.guilds)} servers')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching,name=f"{PREFIX}help"))
    try:
        s=await bot.tree.sync()
        logger.info(f"✅ Synced {len(s)} commands")
    except Exception as e:
        logger.error(f"Sync error:{e}")

@bot.event
async def on_message(msg):
    if msg.author.bot:return
    if bot.user.mentioned_in(msg)and not msg.mention_everyone:
        content=msg.content.replace(f'<@{bot.user.id}>','').replace(f'<@!{bot.user.id}>','').strip()
        if content:
            if db.banned(msg.author.id):return await msg.reply("🚫 Blocked")
            ok,rem=rl.check(msg.author.id,"mention",5)
            if not ok:return await msg.reply(f"⏳ {rem:.0f}s")
            async with msg.channel.typing():
                try:
                    result,used=ask_ai(content,msg.author.id)
                    await send_response(msg,result,used,True)
                    db.stat("ai",msg.author.id)
                except Exception as e:
                    logger.error(f"AI error:{e}")
                    try:await msg.reply(f"❌ Error")
                    except:pass
        else:
            m=db.get_model(msg.author.id)
            await msg.reply(f"👋 Hai! Model: **{MODEL_NAMES.get(m,m)}**\n\nKetik pertanyaan setelah mention!")
        return
    await bot.process_commands(msg)

@bot.command(name="ai",aliases=["ask","chat"])
async def cmd_ai(ctx,*,prompt:str=None):
    if db.banned(ctx.author.id):return
    ok,rem=rl.check(ctx.author.id,"ai",5)
    if not ok:return await ctx.reply(f"⏳ {rem:.0f}s")
    if not prompt:return await ctx.reply(f"❌ `{PREFIX}ai <pertanyaan>`")
    async with ctx.typing():
        try:
            result,used=ask_ai(prompt,ctx.author.id)
            await send_response(ctx.message,result,used,True)
            db.stat("ai",ctx.author.id)
        except Exception as e:
            logger.error(f"AI cmd:{e}")
            await ctx.reply("❌ Error")

@bot.command(name="model",aliases=["m"])
async def cmd_model(ctx,model:str=None):
    valid=list(MODEL_NAMES.keys())
    if not model:
        cur=db.get_model(ctx.author.id)
        e=discord.Embed(title="🤖 Model AI",color=0x3498DB)
        e.add_field(name="Current",value=f"**{MODEL_NAMES.get(cur,cur)}**",inline=False)
        e.add_field(name="Available",value="\n".join([f"`{k}` - {v}"for k,v in MODEL_NAMES.items()]),inline=False)
        return await ctx.reply(embed=e)
    model=model.lower()
    if model not in valid:return await ctx.reply(f"❌ Invalid! Options: `{', '.join(valid)}`")
    db.set_model(ctx.author.id,model)
    await ctx.reply(f"✅ Model: **{MODEL_NAMES.get(model,model)}**")

@bot.command(name="clear",aliases=["reset"])
async def cmd_clear(ctx):
    mem.clear(ctx.author.id)
    await ctx.reply("🧹 Memory cleared!")

@bot.command(name="ping")
async def cmd_ping(ctx):
    m=db.get_model(ctx.author.id)
    e=discord.Embed(title="🏓 Pong!",color=0x00FF00)
    e.add_field(name="Latency",value=f"`{round(bot.latency*1000)}ms`")
    e.add_field(name="Model",value=f"`{MODEL_NAMES.get(m,m)}`")
    await ctx.reply(embed=e)

@bot.command(name="help",aliases=["h"])
async def cmd_help(ctx):
    m=db.get_model(ctx.author.id)
    e=discord.Embed(title="📚 AI Bot Help",description=f"Model: **{MODEL_NAMES.get(m,m)}**",color=0x5865F2)
    e.add_field(name="🤖 AI",value=f"`{PREFIX}ai <text>` - Chat\n`@bot <text>` - Via mention",inline=False)
    e.add_field(name="⚙️ Settings",value=f"`{PREFIX}model [name]` - View/change model\n`{PREFIX}clear` - Clear memory",inline=False)
    e.add_field(name="🔧 Utils",value=f"`{PREFIX}dump <url>` - Download script\n`{PREFIX}ping` - Check status",inline=False)
    await ctx.reply(embed=e)

@bot.command(name="dump")
async def cmd_dump(ctx,url:str=None):
    if not url:return await ctx.reply(f"❌ `{PREFIX}dump <url>`")
    ok,rem=rl.check(ctx.author.id,"dump",8)
    if not ok:return await ctx.reply(f"⏳ {rem:.0f}s")
    async with ctx.typing():
        try:
            curl=get_curl()
            ua=random.choice(UA_LIST)
            headers={"User-Agent":ua,"Roblox-Place-Id":"2753915549","Accept":"*/*"}
            resp=curl.get(url,impersonate="chrome110",headers=headers,timeout=20)
            content=resp.text[:1024*1024]
            ext="lua"
            if"<!DOCTYPE"in content[:300]:ext="html"
            elif content.strip().startswith("{"):ext="json"
            e=discord.Embed(title="🔓 Dump",color=0x00FF00)
            e.add_field(name="Size",value=f"`{len(content):,}b`")
            e.add_field(name="Type",value=f"`.{ext}`")
            db.stat("dump",ctx.author.id)
            await ctx.reply(embed=e,file=discord.File(io.BytesIO(content.encode()),f"dump.{ext}"))
        except Exception as e:
            await ctx.reply(f"❌ {str(e)[:100]}")

@bot.command(name="testai")
async def cmd_testai(ctx):
    if ctx.author.id not in OWNER_IDS:return
    async with ctx.typing():
        results=[]
        test=[{"role":"user","content":"Say OK"}]
        for name,fn in[("Groq",lambda:call_groq(test)),("Cerebras",lambda:call_cerebras(test)),("OR-Llama",lambda:call_openrouter(test,"llama")),("SambaNova",lambda:call_sambanova(test))]:
            try:
                r=fn()
                s="✅"if r else"❌"
                results.append(f"{s} **{name}**:{(r[:20]if r else'Fail')}")
            except Exception as ex:
                results.append(f"❌ **{name}**:{str(ex)[:20]}")
        e=discord.Embed(title="🔧 AI Test",description="\n".join(results),color=0x3498DB)
        await ctx.reply(embed=e)

@bot.tree.command(name="ai",description="Chat with AI")
@app_commands.describe(prompt="Your message")
async def slash_ai(i:discord.Interaction,prompt:str):
    await i.response.defer()
    try:
        result,used=ask_ai(prompt,i.user.id)
        await send_response(i,result,used,False)
        db.stat("ai",i.user.id)
    except Exception as e:
        await i.followup.send(f"❌ Error")

@bot.tree.command(name="model",description="Change AI model")
@app_commands.describe(model="Select model")
@app_commands.choices(model=[app_commands.Choice(name=v,value=k)for k,v in MODEL_NAMES.items()])
async def slash_model(i:discord.Interaction,model:str=None):
    if model:
        db.set_model(i.user.id,model)
        await i.response.send_message(f"✅ Model: **{MODEL_NAMES.get(model,model)}**",ephemeral=True)
    else:
        cur=db.get_model(i.user.id)
        await i.response.send_message(f"🤖 Model: **{MODEL_NAMES.get(cur,cur)}**",ephemeral=True)

@bot.tree.command(name="clear",description="Clear chat memory")
async def slash_clear(i:discord.Interaction):
    mem.clear(i.user.id)
    await i.response.send_message("🧹 Cleared!",ephemeral=True)

@bot.tree.command(name="ping",description="Check bot status")
async def slash_ping(i:discord.Interaction):
    await i.response.send_message(f"🏓 `{round(bot.latency*1000)}ms`")

if __name__=="__main__":
    keep_alive()
    print("="*50)
    print("🚀 AI Bot Starting...")
    print(f"📦 Prefix: {PREFIX}")
    print(f"👑 Owners: {OWNER_IDS}")
    print("🔑 API Keys:")
    print(f"   Groq: {'✅'if KEY_GROQ else'❌'}")
    print(f"   Cerebras: {'✅'if KEY_CEREBRAS else'❌'}")
    print(f"   OpenRouter: {'✅'if KEY_OPENROUTER else'❌'}")
    print(f"   SambaNova: {'✅'if KEY_SAMBANOVA else'❌'}")
    print(f"   Cohere: {'✅'if KEY_COHERE else'❌'}")
    print("="*50)
    bot.run(DISCORD_TOKEN,log_handler=None)
