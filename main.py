import discord  
from discord.ext import commands, tasks
import asyncio
import os
import time
import traceback
import gc
import psutil
from pymongo import MongoClient

# 🔥 IMPORTS
import aiohttp
from collections import defaultdict, deque

# 🔮 IMPORT DA AQUA (ARQUIVO SEPARADO)
from aqua_ia import processar_comando_aqua

# ===============================
# TOKEN & MONGO
# ===============================

TOKEN = os.getenv("TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

SIGHTENGINE_USER = os.getenv("SIGHTENGINE_API_USER")
SIGHTENGINE_SECRET = os.getenv("SIGHTENGINE_API_SECRET")

if not TOKEN:
    raise ValueError("TOKEN não encontrado")
if not MONGO_URI:
    raise ValueError("MONGO_URI não configurado")

# ===============================
# CONEXÃO MONGO (COM LOGS)
# ===============================

try:
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    mongo_client.admin.command('ping')
    
    db = mongo_client["bot"]
    votacoes_db = db["votacoes"]
    print("✅ Conexão com o MongoDB estabelecida com sucesso!")
except Exception as e:
    print(f"❌ ERRO CRÍTICO: Não foi possível conectar ao MongoDB!")
    print(f"Detalhes do erro: {e}")
    db = None
    votacoes_db = None

# ===============================
# 🔥 NOVO: DETECTAR AUTOTHREAD
# ===============================

async def tem_autothread_ativo(bot, guild_id, channel_id):
    try:
        data = list(bot.db["autothreads"].find({
            "guild_id": str(guild_id),
            "channel_id": str(channel_id),
            "ativo": True
        }))
        return len(data) > 0
    except:
        return False

# ===============================
# CONFIG
# ===============================

CANAL_PERMITIDO_ID = 1486826621167210621

LINKS_AUTORIZADOS = [
    "mega.nz",
    "drive.google.com",
    "tiktok.com",
    "streamable.com",
    "cdn.nsb.gg"
]

SPAM_LIMITE = 6

CANAIS_IGNORAR_ANTISPAM = [
    1471028250099716127
]

REGRAS = """## ☕ Utilize este tópico corretamente:
• Use este tópico para comentar sobre a edit.
• Mantenha a conversa relacionada à edição avaliada.
• Evite mensagens fora de contexto.

Atenciosamente, equipe da Staff.
"""

# ===============================
# ANTI-SPAM
# ===============================

mensagens_usuario = defaultdict(lambda: deque(maxlen=SPAM_LIMITE))

# ===============================
# NSFW DETECTOR
# ===============================

async def detectar_nsfw(url):
    if not SIGHTENGINE_USER or not SIGHTENGINE_SECRET:
        return False

    endpoint = "https://api.sightengine.com/1.0/check.json"

    params = {
        "url": url,
        "models": "nudity-2.1",
        "api_user": SIGHTENGINE_USER,
        "api_secret": SIGHTENGINE_SECRET
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(endpoint, params=params) as r:
                data = await r.json()

                nudity = data.get("nudity", {})
                sexual = nudity.get("sexual_activity", 0)
                explicit = nudity.get("sexual_display", 0)

                return sexual > 0.6 or explicit > 0.6

    except Exception as e:
        print("Erro IA NSFW:", e)
        return False

# ===============================
# BOT + INTENTS
# ===============================

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(
    command_prefix=".",
    intents=intents,
    help_command=None
)

bot.db = db
bot.votacoes_db = votacoes_db

# ===============================
# FILA
# ===============================

acao_fila = asyncio.Queue()

async def worker_fila():
    while True:
        func, args, kwargs = await acao_fila.get()
        try:
            await func(*args, **kwargs)
        except Exception as e:
            print("Erro na fila:", e)
        await asyncio.sleep(1)

# ===============================
# TASKS
# ===============================

@tasks.loop(minutes=10)
async def limpar_memoria():
    gc.collect()

@tasks.loop(minutes=2)
async def monitor_bot():
    try:
        memoria = psutil.Process().memory_info().rss / 1024 / 1024
        if memoria > 400:
            print(f"⚠️ Memória alta: {memoria:.0f}MB")
    except:
        pass

# ===============================
# AUX
# ===============================

def link_permitido(conteudo):
    conteudo = conteudo.lower()

    if "discord.gg" in conteudo or "discord.com/invite" in conteudo:
        return False

    if "http://" in conteudo or "https://" in conteudo:
        return any(link in conteudo for link in LINKS_AUTORIZADOS)

    return False

def apenas_anexo(message):
    return len(message.attachments) > 0

# ===============================
# EVENTOS
# ===============================

@bot.event
async def on_ready():
    print(f"✅ Bot online como {bot.user}")

    if not limpar_memoria.is_running():
        limpar_memoria.start()

    if not monitor_bot.is_running():
        monitor_bot.start()

    bot.loop.create_task(worker_fila())

    for guild in bot.guilds:
        print(f"🔄 Guild ativa: {guild.name}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # 🔮 INTERCEPTOR INTELIGENTE DA AQUA
    if "aqua" in message.content.lower():
        if not message.author.guild_permissions.administrator:
            await message.channel.send("Não tens autoridade para dar ordens administrativas à Aqua.")
            return
        
        await processar_comando_aqua(message)
        await bot.process_commands(message)
        return

    # 🔞 IMAGENS (NSFW CHECK)
    if message.attachments:
        for anexo in message.attachments:
            if anexo.content_type and "image" in anexo.content_type:
                nsfw = await detectar_nsfw(anexo.url)

                if nsfw:
                    try:
                        await message.delete()
                        await message.author.send(
                            "🚫 Imagem removida automaticamente (detecção de nudez por IA)."
                        )
                    except:
                        pass

                    await bot.process_commands(message)
                    return

    # 🔥 ANTI-SPAM
    if message.channel.id not in CANAIS_IGNORAR_ANTISPAM:
        historico = mensagens_usuario[message.author.id]
        historico.append(message.content)

        if len(historico) == SPAM_LIMITE and len(set(historico)) == 1:
            try:
                await message.channel.purge(
                    limit=50,
                    check=lambda m: (
                        m.author.id == message.author.id and
                        m.content == message.content
                    )
                )
            except:
                pass

            mensagens_usuario[message.author.id].clear()

            await bot.process_commands(message)
            return

    # 🔥 SISTEMA ORIGINAL DE THREADS
    if message.channel.id == CANAL_PERMITIDO_ID:

        # 🔥 CORREÇÃO (NÃO REMOVE NADA)
        if await tem_autothread_ativo(bot, message.guild.id, message.channel.id):
            await bot.process_commands(message)
            return

        permitido = apenas_anexo(message) or link_permitido(message.content)

        if not permitido:
            try:
                await message.delete()
            except:
                pass

            await bot.process_commands(message)
            return

        try:
            thread = await message.create_thread(
                name="Comentários sobre a edit ☕",
                auto_archive_duration=1440
            )

            regras_msg = await thread.send(REGRAS)
            await rules_msg.pin()

        except Exception as e:
            print("Erro ao criar tópico:", e)

        await bot.process_commands(message)
        return

    await bot.process_commands(message)

# ===============================
# ERROS
# ===============================

@bot.event
async def on_error(event, *args, **kwargs):
    with open("erros.txt", "a", encoding="utf-8") as f:
        f.write(f"\nERRO GLOBAL: {event}\n")
        f.write(traceback.format_exc())
        f.write("\n========================\n")

# ===============================
# 📂 CARREGAMENTO DE COGS
# ===============================

async def carregar_cogs():
    if not os.path.exists("./cogs"):
        print("❌ Pasta './cogs' não encontrada.")
        return

    for arquivo in os.listdir("./cogs"):
        if arquivo.endswith(".py"):
            try:
                await bot.load_extension(f"cogs.{arquivo[:-3]}")
                print(f"✅ Cog carregada: {arquivo}")
            except Exception as e:
                print(f"❌ Erro ao carregar {arquivo}: {e}")

# ===============================
# 🚀 SETUP HOOK (Sincronização Slash)
# ===============================

@bot.event
async def setup_hook():
    await carregar_cogs()
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} Slash Commands sincronizados!")
    except Exception as e:
        print(f"❌ Erro ao sincronizar slash commands: {e}")

# ===============================
# START
# ===============================

if __name__ == "__main__":
    bot.run(TOKEN)
    
