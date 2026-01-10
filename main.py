import discord
import os
import io
import re
import random
from discord import app_commands
from discord.ext import commands
from curl_cffi import requests
from keep_alive import keep_alive

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# List User Agent untuk Download
UA_LIST = ["Roblox/WinInet", "Delta Android/2.0", "Synapse-X/2.0"]

@bot.event
async def on_ready():
    print(f'🔥 Bot Siap: {bot.user}')
    await bot.tree.sync()

# ==========================================
# 🧠 OTAK SCANNER (MENGGANTIKAN FUNGSI LUA)
# ==========================================
def analyze_script_content(content):
    report = {
        "key_systems": [],
        "webhooks": [],
        "loadstrings": [],
        "potential_urls": [],
        "is_obfuscated": False
    }

    # 1. Cek Obfuscation (Luraph/IronBrew)
    if "Luraph" in content or "\\x4c\\x75\\x72\\x61" in content or "IronBrew" in content:
        report["is_obfuscated"] = True

    # 2. Cari URL (Regex Powerful)
    # Ini menggantikan fungsi "Memory Scan" di Lua
    regex_url = r'https?://[^\s"\'<>`]+'
    all_links = re.findall(regex_url, content)

    for link in all_links:
        # Bersihkan link dari karakter sisa
        link = link.rstrip(";,)}")
        
        # Kategori: Key System (Work.ink / Linkvertise / Pastebin)
        if any(x in link for x in ["work.ink", "linkvertise", "loot-link", "link-hub", "pastebin"]):
            if link not in report["key_systems"]:
                report["key_systems"].append(link)
        
        # Kategori: Webhook (Pencuri Akun)
        elif "discord.com/api/webhooks" in link:
            report["webhooks"].append(link)
        
        # Kategori: External Loader
        elif "raw.githubusercontent" in link or "script" in link.lower() or "loader" in link.lower():
            if link not in report["loadstrings"]:
                report["loadstrings"].append(link)
        
        # Sisanya masuk ke potensial
        elif "roblox.com" not in link and len(link) < 150:
            if link not in report["potential_urls"]:
                report["potential_urls"].append(link)

    return report

# ==========================================
# COMMAND: /scan
# ==========================================
@bot.tree.command(name="scan", description="Scan script untuk mencari Key System, Webhook, & URL tersembunyi")
@app_commands.describe(url="URL Script (Raw)")
async def scan(interaction: discord.Interaction, url: str):
    await interaction.response.defer()

    try:
        # 1. Download Script (Meniru Executor)
        headers = {"User-Agent": random.choice(UA_LIST)}
        response = requests.get(url, impersonate="chrome110", headers=headers, timeout=15)

        if response.status_code != 200:
            return await interaction.followup.send(f"❌ Gagal download. Status: {response.status_code}")

        content = response.text
        if len(content) > 2000000: # Limit 2MB biar bot ga crash
            return await interaction.followup.send("⚠️ Script terlalu besar untuk discan!")

        # 2. Analisa Script
        data = analyze_script_content(content)

        # 3. Buat Laporan (Embed)
        embed = discord.Embed(title="🔍 Hasil Scan Script", color=discord.Color.yellow())
        embed.add_field(name="Target", value=f"`{url}`", inline=False)
        
        # Tampilkan Key Systems (Work.ink, dll)
        if data["key_systems"]:
            links_text = "\n".join([f"• `{x}`" for x in data["key_systems"][:5]]) # Max 5 link
            embed.add_field(name="🔑 Key Systems Ditemukan", value=links_text, inline=False)
        else:
            embed.add_field(name="🔑 Key Systems", value="Tidak ditemukan (Mungkin diobfuscate)", inline=False)

        # Tampilkan Loadstrings
        if data["loadstrings"]:
            load_text = "\n".join([f"• `{x}`" for x in data["loadstrings"][:5]])
            embed.add_field(name="📥 External Loaders", value=load_text, inline=False)

        # Warning Webhook
        if data["webhooks"]:
            embed.add_field(name="🚨 WEBHOOK DETECTED", value=f"⚠️ Ditemukan {len(data['webhooks'])} Webhook Discord! (Potensi Logger)", inline=False)
            embed.color = discord.Color.red()

        # Status Obfuscation
        if data["is_obfuscated"]:
            embed.set_footer(text="⚠️ Script ini Ter-Obfuscate (Luraph/Lainnya). Hasil scan mungkin tidak lengkap.")
        else:
            embed.set_footer(text="✅ Script Open Source (Raw). Hasil scan akurat.")

        # Kirim File Hasil Lengkap
        result_text = f"--- SCAN REPORT FOR: {url} ---\n\n"
        result_text += f"[KEY SYSTEMS]\n" + "\n".join(data["key_systems"]) + "\n\n"
        result_text += f"[WEBHOOKS]\n" + "\n".join(data["webhooks"]) + "\n\n"
        result_text += f"[ALL URLS FOUND]\n" + "\n".join(data["potential_urls"]) + "\n" + "\n".join(data["loadstrings"])

        file_data = io.BytesIO(result_text.encode("utf-8"))
        
        await interaction.followup.send(embed=embed, file=discord.File(file_data, filename="Scan_Result.txt"))

    except Exception as e:
        await interaction.followup.send(f"💀 Error: {str(e)}")

# ==========================================
# COMMAND: /dump (Tetap Ada)
# ==========================================
@bot.tree.command(name="dump", description="Download script file saja")
async def dump(interaction: discord.Interaction, url: str):
    await interaction.response.defer()
    try:
        response = requests.get(url, impersonate="chrome110", headers={"User-Agent": "Roblox/WinInet"})
        if response.status_code == 200:
            file = io.BytesIO(response.content)
            await interaction.followup.send(f"✅ Dumped!", file=discord.File(file, filename="Script.lua"))
        else:
            await interaction.followup.send("❌ Gagal.")
    except:
        await interaction.followup.send("❌ Error.")

keep_alive()
try:
    bot.run(os.getenv("DISCORD_TOKEN"))
except:
    print("Token Invalid")
