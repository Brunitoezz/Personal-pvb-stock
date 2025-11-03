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

async def fetch_stock_data():
    """Obtiene los datos del stock de la API"""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(API_URL) as resp:
                if resp.status != 200:
                    return None, f"Error {resp.status} en la API"
                return await resp.json(), None
        except Exception as e:
            return None, f"Error obteniendo stock: {e}"

async def send_stock_message(channel: discord.TextChannel, guild: discord.Guild, data: dict, force_send: bool = False):
    """Envía el mensaje de stock al canal especificado"""
    seed_stock = data.get("seed_stock", [])
    gear_stock = data.get("gear_stock", [])

    # Extraer solo campos relevantes (ignora timestamps que cambian constantemente)
    current_stock_hash = extract_relevant_stock(data)
    
    # Verificar si el stock cambió desde la última vez
    guild_str = str(guild.id)
    if not force_send:
        if guild_str in last_stock_data and last_stock_data[guild_str] == current_stock_hash:
            return False  # No hay cambios, no enviar mensaje
    
    # Actualizar el último stock
    last_stock_data[guild_str] = current_stock_hash
    
    print(f"🔄 Stock {'forzado' if force_send else 'actualizado'} detectado en {guild.name}")

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
    if seed_mentions and not force_send:
        await channel.send(" ".join(seed_mentions))
    
    # Luego enviar el embed
    await channel.send(embed=embed)
    return True

# === COMANDO PARA CONFIGURAR CANAL ===
@bot.tree.command(name="setstockchannel", description="Establece el canal donde se publicará el stock.")
@app_commands.describe(channel="Canal de texto donde se publicará el stock")
async def set_stock_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    config[str(interaction.guild_id)] = {"channel_id": channel.id}
    save_config(config)
    await interaction.response.send_message(f"✅ Canal de stock establecido en {channel.mention}", ephemeral=True)

# === COMANDO PARA REVISAR STOCK MANUALMENTE ===
@bot.tree.command(name="checkstock", description="Revisa el stock manualmente sin alterar el chequeo automático.")
async def check_stock_manual(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    guild_id = str(interaction.guild_id)
    if guild_id not in config:
        await interaction.followup.send("❌ Primero debes configurar un canal con `/setstockchannel`", ephemeral=True)
        return
    
    channel_id = config[guild_id].get("channel_id")
    if not channel_id:
        await interaction.followup.send("❌ Primero debes configurar un canal con `/setstockchannel`", ephemeral=True)
        return
    
    channel = interaction.guild.get_channel(channel_id)
    if not channel or not isinstance(channel, discord.TextChannel):
        await interaction.followup.send("❌ El canal configurado no es válido", ephemeral=True)
        return
    
    data, error = await fetch_stock_data()
    if error:
        await interaction.followup.send(f"❌ {error}", ephemeral=True)
        return
    
    await send_stock_message(channel, interaction.guild, data, force_send=True)
    await interaction.followup.send(f"✅ Stock enviado manualmente a {channel.mention}", ephemeral=True)

# === COMANDO PARA ACTUALIZAR ROLES DE SEMILLAS NUEVAS ===
@bot.tree.command(name="updateseeds", description="Detecta nuevas semillas de la API y crea roles para ellas.")
async def update_seed_roles(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    data, error = await fetch_stock_data()
    if error:
        await interaction.followup.send(f"❌ {error}", ephemeral=True)
        return
    
    seed_stock = data.get("seed_stock", [])
    new_seeds = []
    roles_created = 0
    
    for seed in seed_stock:
        seed_name = seed["display_name"]
        existing_role = discord.utils.get(interaction.guild.roles, name=seed_name)
        
        if not existing_role:
            new_seeds.append(seed_name)
            try:
                await interaction.guild.create_role(
                    name=seed_name, 
                    color=discord.Color.green(), 
                    reason="Nueva semilla detectada en la API"
                )
                roles_created += 1
                print(f"✅ Nuevo rol creado: {seed_name} en {interaction.guild.name}")
            except discord.Forbidden:
                await interaction.followup.send(f"⚠️ No tengo permisos para crear el rol {seed_name}", ephemeral=True)
                return
            except Exception as e:
                await interaction.followup.send(f"❌ Error creando rol {seed_name}: {e}", ephemeral=True)
                return
    
    if roles_created > 0:
        seeds_list = ", ".join(new_seeds)
        await interaction.followup.send(
            f"🎉 Se detectaron **{roles_created}** nuevas semillas y se crearon sus roles:\n{seeds_list}", 
            ephemeral=True
        )
    else:
        await interaction.followup.send("✅ No se detectaron nuevas semillas. Todos los roles ya existen.", ephemeral=True)

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

        data, error = await fetch_stock_data()
        if error:
            print(f"❌ {error}")
            continue

        await send_stock_message(channel, guild, data, force_send=False)

# === INICIO ===
keep_alive()  # Mantiene el bot encendido en Replit
token = os.getenv("TOKEN")
if not token:
    raise ValueError("❌ TOKEN no encontrado en las variables de entorno")
bot.run(token)
