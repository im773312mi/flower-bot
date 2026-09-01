import os
import random
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import discord
from discord.ext import commands
import pandas as pd

# 1. 建立輕量網頁服務（供 Render 綁定 Port 及防止休眠）
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write("🌸 我的花園世界 Bot 運作中！".encode('utf-8'))

def start_health_check_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    print(f"🌐 防休眠網頁服務已啟動於 Port {port}")
    server.serve_forever()

# 在背景執行網頁服務
threading.Thread(target=start_health_check_server, daemon=True).start()

# 2. 讀取花種資料庫
EXCEL_FILE = "flowers.xlsx"
df_flowers = pd.read_excel(EXCEL_FILE)

# 3. 稀有度概率 (60/30/8/2) 與 Discord 顏色標籤對應表
RARITY_CONFIG = {
    "普": {"color": 0x3B82F6, "emoji": "🔵", "weight": 60.0},
    "珍": {"color": 0xA855F7, "emoji": "🟣", "weight": 30.0},
    "華": {"color": 0xF97316, "emoji": "🟠", "weight": 8.0},
    "仙": {"color": 0xEF4444, "emoji": "🔴", "weight": 2.0}
}

# 4. 初始化 Discord Bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"🤖 盲盒 Bot 已成功上線：{bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ 已成功同步 {len(synced)} 個斜線指令")
    except Exception as e:
        print(f"❌ 指令同步失敗: {e}")

@bot.tree.command(name="gacha", description="開啟一個花園盲盒！")
async def gacha(interaction: discord.Interaction):
    rarities = list(RARITY_CONFIG.keys())
    weights = [RARITY_CONFIG[r]["weight"] for r in rarities]
    selected_rarity = random.choices(rarities, weights=weights, k=1)[0]
    
    filtered_df = df_flowers[df_flowers['rarity'] == selected_rarity]
    flower = filtered_df.sample(n=1).iloc[0]
    
    config = RARITY_CONFIG[selected_rarity]
    
    embed = discord.Embed(
        title="🌸 花園盲盒開啟成功！",
        description=f"獲得花種：**【{flower['Chinese']}】**\n\n📜 *{flower['description']}*",
        color=config["color"]
    )
    
    embed.add_field(
        name="✨ 稀有度",
        value=f"{config['emoji']} **{selected_rarity}**",
        inline=True
    )
    
    if pd.notna(flower['Link']):
        embed.set_image(url=flower['Link'])
        
    embed.set_footer(
        text=f"開啟者：{interaction.user.display_name} • 我的花園世界", 
        icon_url=interaction.user.display_avatar.url
    )
    
    await interaction.response.send_message(
        content=f"🎉 {interaction.user.mention} 打開了一個盲盒！",
        embed=embed
    )

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ 錯誤：未設置 DISCORD_TOKEN 環境變數！")
