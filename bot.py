import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import json
import os
from keep_alive import keep_alive

# === CONFIGURACIÓN ===
API_URL = "https://www.api-giahuy.duckdns.org/api/v3/plantsvsbrainrots/stock"
CHECK_INTERVAL = 30  # 30 segundos para detectar cambios rápidamente
CONFIG_FILE = "config.json"

# Lista completa de todas las semillas posibles en el juego
ALL_SEEDS = [
    "Cactus",
    "Sunflower",
    "Strawberry",
    "Pumpkin",
    "Dragon Fruit",
    "Eggplant",
    "Watermelon",
    "Grape",
    "Cocotank",
    "Carnivorous Plant",
    "Mr. Carrot",
    "Tomatrio",
    "Shroombino",
    "Mango",
    "King Limone"
]

# Almacenar último stock por guild para detectar cambios
last_stock_data = {}

def extract_relevant_stock(data):
    """Extrae solo los campos relevantes para comparación (ignora timestamps)"""
    seed_stock = data.get("seed_stock", [])
    gear_stock = data.get("gear_stock", [])
    
    # Solo extraer item_id, display_name y quantity
    seeds = [{"id": s["item_id"], "name": s["display_name"], "qty": s["quantity"]} 
             for s in seed_stock]
    gears = [{"id": g["item_id"], "name": g["display_name"], "qty": g["quantity"]} 
             for g in gear_stock]
    
    return json.dumps({"seeds": seeds, "gears": gears}, sort_keys=True)

# === CARGAR CONFIG ===
if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "w") as f:
        json.dump({}, f)

def load_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

config = load_config()

# === INTENTS ===
intents = discord.Intents.default()
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# === EVENTOS ===
@bot.event
async def on_ready():
    print(f"✅ Conectado como {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"🔗 Comandos sincronizados: {len(synced)}")
    except Exception as e:
        print(f"❌ Error sincronizando comandos: {e}")
    
    # Pre-crear todos los roles de semillas en todos los servidores configurados
    await create_all_seed_roles()
    
    check_stock.start()

async def create_all_seed_roles():
    """Crea todos los roles de semillas predefinidos en todos los servidores"""
    print("🌱 Verificando y creando roles de semillas...")
    for guild_id in config.keys():
        guild = bot.get_guild(int(guild_id))
        if not guild:
            continue
        
        roles_created = 0
        for seed_name in ALL_SEEDS:
            existing = discord.utils.get(guild.roles, name=seed_name)
            if not existing:
                try:
                    await guild.create_role(name=seed_name, color=discord.Color.green(), reason="Rol automático de semilla")
                    roles_created += 1
                    print(f"  ✅ Rol creado: {seed_name} en {guild.name}")
                except discord.Forbidden:
                    print(f"  ⚠️ Sin permisos para crear rol {seed_name} en {guild.name}")
                except Exception as e:
                    print(f"  ❌ Error creando rol {seed_name}: {e}")
        
        if roles_created > 0:
            print(f"🎉 {roles_created} roles creados en {guild.name}")
        else:
            print(f"✅ Todos los roles ya existen en {guild.name}")

# === COMANDO PARA CONFIGURAR CANAL ===
@bot.tree.command(name="setstockchannel", description="Establece el canal donde se publicará el stock.")
@app_commands.describe(channel="Canal de texto donde se publicará el stock")
async def set_stock_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    config[str(interaction.guild_id)] = {"channel_id": channel.id}
    save_config(config)
    await interaction.response.send_message(f"✅ Canal de stock establecido en {channel.mention}", ephemeral=True)

# === TAREA AUTOMÁTICA ===
@tasks.loop(seconds=CHECK_INTERVAL)
async def check_stock():
    await bot.wait_until_ready()
    for guild_id, guild_data in config.items():
        guild = bot.get_guild(int(guild_id))
        if not guild:
            continue
        channel_id = guild_data.get("channel_id")
        if not channel_id:
            continue
        channel = guild.get_channel(channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            continue

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(API_URL) as resp:
                    if resp.status != 200:
                        print(f"❌ Error {resp.status} en la API")
                        continue
                    data = await resp.json()
            except Exception as e:
                print(f"❌ Error obteniendo stock: {e}")
                continue

        seed_stock = data.get("seed_stock", [])
        gear_stock = data.get("gear_stock", [])

        # Extraer solo campos relevantes (ignora timestamps que cambian constantemente)
        current_stock_hash = extract_relevant_stock(data)
        
        # Verificar si el stock cambió desde la última vez
        guild_str = str(guild_id)
        if guild_str in last_stock_data and last_stock_data[guild_str] == current_stock_hash:
            continue  # No hay cambios, no enviar mensaje
        
        # Actualizar el último stock
        last_stock_data[guild_str] = current_stock_hash
        
        print(f"🔄 Stock actualizado detectado en {guild.name}")

        # Construir menciones de roles de semillas
        seed_mentions = []
        for seed in seed_stock:
            role = discord.utils.get(guild.roles, name=seed["display_name"])
            if role:
                seed_mentions.append(role.mention)
        
        # Crear el embed
        embed = discord.Embed(
            title="🌿 Stock Actual — Plants vs Brainrots",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="Se actualiza cada 5 minutos • Bot chequea cada 30s")

        seed_text = ""
        for seed in seed_stock:
            role = discord.utils.get(guild.roles, name=seed["display_name"])
            mention = role.mention if role else seed["display_name"]
            seed_text += f"{mention} — **{seed['quantity']} disponibles**\n"
        embed.add_field(name="🌱 Semillas", value=seed_text or "Sin semillas disponibles", inline=False)

        gear_text = ""
        for gear in gear_stock:
            gear_text += f"{gear['display_name']} — **{gear['quantity']} disponibles**\n"
        embed.add_field(name="⚙️ Gears", value=gear_text or "Sin gears disponibles", inline=False)

        # Enviar menciones primero (si hay semillas con roles)
        if seed_mentions:
            await channel.send(" ".join(seed_mentions))
        
        # Luego enviar el embed
        await channel.send(embed=embed)

# === INICIO ===
keep_alive()  # Mantiene el bot encendido en Replit
token = os.getenv("TOKEN")
if not token:
    raise ValueError("❌ TOKEN no encontrado en las variables de entorno")
bot.run(token)
