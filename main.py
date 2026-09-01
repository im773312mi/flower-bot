import os
import json
import random
import time
from datetime import date
import discord
from discord.ext import commands
from discord import app_commands
import pandas as pd

# 1. 讀取花種資料庫
EXCEL_FILE = "flowers.xlsx"
df_flowers = pd.read_excel(EXCEL_FILE)

# 2. 背包與貨幣數據庫 (inventory.json) 讀寫邏輯
INVENTORY_FILE = "inventory.json"

def load_inventory():
    if os.path.exists(INVENTORY_FILE):
        try:
            with open(INVENTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ 讀取背包失敗: {e}")
            return {}
    return {}

def save_inventory(data):
    with open(INVENTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def get_user_data(inventory, user_id):
    """取得玩家數據，若為舊版格式會自動補齊缺失欄位"""
    if user_id not in inventory:
        inventory[user_id] = {
            "flowers": {},
            "coins": 0,
            "last_daily": "",
            "gacha_date": "",
            "gacha_count": 0
        }
    elif "flowers" not in inventory[user_id]:
        old_flowers = inventory[user_id]
        inventory[user_id] = {
            "flowers": old_flowers,
            "coins": 0,
            "last_daily": "",
            "gacha_date": "",
            "gacha_count": 0
        }
    
    data = inventory[user_id]
    data.setdefault("coins", 0)
    data.setdefault("last_daily", "")
    data.setdefault("gacha_date", "")
    data.setdefault("gacha_count", 0)
    data.setdefault("flowers", {})
    return data

# 防洗版計數器
USER_MESSAGE_TIMES = {}

# 指定擁有者 Username 白名單
ADMIN_USERNAMES = ["muri_xo"]

# 3. 稀有度概率 (60/30/8/2) 與 Discord 顏色標籤對應表
RARITY_CONFIG = {
    "普": {"color": 0x3B82F6, "emoji": "🔵", "weight": 60.0},
    "珍": {"color": 0xA855F7, "emoji": "🟣", "weight": 30.0},
    "華": {"color": 0xF97316, "emoji": "🟠", "weight": 8.0},
    "仙": {"color": 0xEF4444, "emoji": "🔴", "weight": 2.0}
}

# 4. 初始化 Discord Bot (開啟特權 Intent)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# 5. UI 組件定義

class FlowerSelect(discord.ui.Select):
    def __init__(self, user_flowers, df_flowers):
        options = [
            discord.SelectOption(
                label=flower_name,
                description=f"擁有數量：{count}"
            )
            for flower_name, count in user_flowers.items()
        ]
        super().__init__(placeholder="🌸 選擇想欣賞的花朵...", options=options[:25])
        self.df_flowers = df_flowers

    async def callback(self, interaction: discord.Interaction):
        flower_name = self.values[0]
        matched = self.df_flowers[self.df_flowers['Chinese'] == flower_name]
        
        if matched.empty:
            await interaction.response.send_message("❌ 找不到該花朵的詳細資料。", ephemeral=True)
            return
        
        flower = matched.iloc[0]
        rarity = flower['rarity']
        config = RARITY_CONFIG.get(rarity, {"color": 0xFFC0CB, "emoji": "🌸"})

        embed = discord.Embed(
            title=f"🌸 【{flower['Chinese']}】",
            description=f"📜 *{flower['description']}*",
            color=config["color"]
        )
        embed.add_field(name="✨ 稀有度", value=f"{config['emoji']} **{rarity}**", inline=True)
        
        if pd.notna(flower['Link']):
            embed.set_image(url=flower['Link'])

        await interaction.response.send_message(embed=embed, ephemeral=True)

class FlowerBagView(discord.ui.View):
    def __init__(self, user_flowers, df_flowers):
        super().__init__()
        self.add_item(FlowerSelect(user_flowers, df_flowers))

class TradeView(discord.ui.View):
    def __init__(self, sender: discord.Member, target: discord.Member, my_flower: str, my_amount: int, target_flower: str, target_amount: int):
        super().__init__(timeout=60)
        self.sender = sender
        self.target = target
        self.my_flower = my_flower
        self.my_amount = my_amount
        self.target_flower = target_flower
        self.target_amount = target_amount

    @discord.ui.button(label="✅ 同意交易", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("❌ 只有被邀請交易的對象可以接受此交易！", ephemeral=True)
            return
        
        inventory = load_inventory()
        s_data = get_user_data(inventory, str(self.sender.id))
        t_data = get_user_data(inventory, str(self.target.id))

        s_bag = s_data["flowers"]
        t_bag = t_data["flowers"]

        if s_bag.get(self.my_flower, 0) < self.my_amount or t_bag.get(self.target_flower, 0) < self.target_amount:
            await interaction.response.send_message("❌ 交易失敗！其中一方的花朵數量不足。", ephemeral=True)
            self.stop()
            return

        s_bag[self.my_flower] -= self.my_amount
        if s_bag[self.my_flower] <= 0: del s_bag[self.my_flower]
        s_bag[self.target_flower] = s_bag.get(self.target_flower, 0) + self.target_amount

        t_bag[self.target_flower] -= self.target_amount
        if t_bag[self.target_flower] <= 0: del t_bag[self.target_flower]
        t_bag[self.my_flower] = t_bag.get(self.my_flower, 0) + self.my_amount

        save_inventory(inventory)

        for item in self.children: item.disabled = True
        await interaction.response.edit_message(
            content=f"🎉 **交易成功！**\n{self.sender.mention} 用 **{self.my_flower}** × {self.my_amount} 與 {self.target.mention} 的 **{self.target_flower}** × {self.target_amount} 完成了交換！",
            view=self
        )

    @discord.ui.button(label="❌ 拒絕交易", style=discord.ButtonStyle.red)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in [self.target.id, self.sender.id]:
            await interaction.response.send_message("❌ 你無法操作此按鈕！", ephemeral=True)
            return
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(content="❌ 交易已取消。", view=self)

# 6. Bot 事件與斜線指令

@bot.event
async def on_ready():
    print(f"🤖 盲盒 Bot 已成功上線：{bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ 已成功同步 {len(synced)} 個斜線指令")
    except Exception as e:
        print(f"❌ 指令同步失敗: {e}")

# --- 聊天發言賺取 💮 (一分鐘最多 5 💮) ---
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = str(message.author.id)
    current_time = time.time()

    if user_id not in USER_MESSAGE_TIMES:
        USER_MESSAGE_TIMES[user_id] = []

    USER_MESSAGE_TIMES[user_id] = [t for t in USER_MESSAGE_TIMES[user_id] if current_time - t < 60]

    if len(USER_MESSAGE_TIMES[user_id]) < 5:
        USER_MESSAGE_TIMES[user_id].append(current_time)
        inventory = load_inventory()
        user_data = get_user_data(inventory, user_id)
        user_data["coins"] = user_data.get("coins", 0) + 1
        save_inventory(inventory)

    await bot.process_commands(message)

# --- /add_coins (管理員/指定 Username 專用加幣指令) ---
@bot.tree.command(name="add_coins", description="【管理員專用】發放 💮 貨幣給指定的玩家")
@app_commands.describe(target="目標玩家", amount="增加的 💮 數量")
async def add_coins(interaction: discord.Interaction, target: discord.Member, amount: int):
    is_admin = interaction.user.guild_permissions.administrator
    is_specified_owner = interaction.user.name in ADMIN_USERNAMES

    if not (is_admin or is_specified_owner):
        await interaction.response.send_message(
            "🚨 嗶嗶！抓到想偷偷印鈔票的小手手囉！這個是村長（管理員）專屬的魔法指令啦～ 🌸",
            ephemeral=True
        )
        return

    if amount <= 0:
        await interaction.response.send_message("❌ 數量必須大於 0！", ephemeral=True)
        return

    inventory = load_inventory()
    target_data = get_user_data(inventory, str(target.id))
    target_data["coins"] = target_data.get("coins", 0) + amount
    save_inventory(inventory)

    await interaction.response.send_message(
        f"👑 **管理員指令**\n已成功為 {target.mention} 發放 **{amount}** 💮！\n該玩家目前總資產：**{target_data['coins']}** 💮",
        ephemeral=True
    )

# --- /daily (每日簽到) ---
@bot.tree.command(name="daily", description="每日簽到領取 10~50 💮 獎勵！")
async def daily(interaction: discord.Interaction):
    inventory = load_inventory()
    user_id = str(interaction.user.id)
    user_data = get_user_data(inventory, user_id)

    today_str = str(date.today())
    if user_data.get("last_daily") == today_str:
        await interaction.response.send_message("❌ 你今天已經簽到過了，明天再來吧！", ephemeral=True)
        return

    reward = random.randint(10, 50)
    user_data["coins"] = user_data.get("coins", 0) + reward
    user_data["last_daily"] = today_str
    save_inventory(inventory)

    await interaction.response.send_message(
        f"💮 簽到成功！{interaction.user.mention} 獲得了 **{reward}** 💮！\n目前總資產：**{user_data['coins']}** 💮"
    )

# --- /gacha (動態扣費抽卡) ---
@bot.tree.command(name="gacha", description="開啟一個花園盲盒！")
async def gacha(interaction: discord.Interaction):
    inventory = load_inventory()
    user_id = str(interaction.user.id)
    user_data = get_user_data(inventory, user_id)
    
    today_str = str(date.today())
    
    if user_data.get("gacha_date") != today_str:
        user_data["gacha_date"] = today_str
        user_data["gacha_count"] = 0

    current_count = user_data["gacha_count"]
    cost = 100 + (current_count * 20)
    
    if user_data["coins"] < cost:
        next_draw_num = current_count + 1
        await interaction.response.send_message(
            f"❌ 你的 💮 貨幣不足！\n"
            f"今日第 **{next_draw_num}** 次抽卡需要 **{cost}** 💮，你目前只有 **{user_data['coins']}** 💮。\n"
            f"💡 提示：多喺頻道聊天或使用 `/daily` 簽到賺取 💮 吧！",
            ephemeral=True
        )
        return

    user_data["coins"] -= cost
    user_data["gacha_count"] += 1

    rarities = list(RARITY_CONFIG.keys())
    weights = [RARITY_CONFIG[r]["weight"] for r in rarities]
    selected_rarity = random.choices(rarities, weights=weights, k=1)[0]
    
    filtered_df = df_flowers[df_flowers['rarity'] == selected_rarity]
    flower = filtered_df.sample(n=1).iloc[0]
    
    config = RARITY_CONFIG[selected_rarity]
    flower_name = flower['Chinese']
    
    user_data["flowers"][flower_name] = user_data["flowers"].get(flower_name, 0) + 1
    save_inventory(inventory)
    
    next_cost = 100 + (user_data["gacha_count"] * 20)
    
    embed = discord.Embed(
        title="🌸 花園盲盒開啟成功！",
        description=f"獲得花種：**【{flower_name}】**\n\n📜 *{flower['description']}*",
        color=config["color"]
    )
    embed.add_field(name="✨ 稀有度", value=f"{config['emoji']} **{selected_rarity}**", inline=True)
    embed.add_field(name="💸 本次消耗", value=f"**{cost}** 💮", inline=True)
    embed.add_field(name="👛 剩餘資產", value=f"**{user_data['coins']}** 💮", inline=True)
    
    if pd.notna(flower['Link']):
        embed.set_image(url=flower['Link'])
        
    embed.set_footer(
        text=f"今日第 {user_data['gacha_count']} 次抽卡 • 下次抽卡需要 {next_cost} 💮", 
        icon_url=interaction.user.display_avatar.url
    )
    
    await interaction.response.send_message(
        content=f"🎉 {interaction.user.mention} 消耗了 **{cost}** 💮 打開了一個盲盒！已收納至 `/bag`",
        embed=embed
    )

# --- /bag (私密背包選單) ---
@bot.tree.command(name="bag", description="查看私密背包並欣賞花朵圖片")
async def bag(interaction: discord.Interaction):
    inventory = load_inventory()
    user_id = str(interaction.user.id)
    user_data = get_user_data(inventory, user_id)
    user_flowers = user_data.get("flowers", {})

    if not user_flowers:
        await interaction.response.send_message(
            f"🌸 你的背包空空如也，快去 `/gacha` 抽花吧！\n持有資產：**{user_data.get('coins', 0)}** 💮",
            ephemeral=True
        )
        return

    view = FlowerBagView(user_flowers, df_flowers)
    await interaction.response.send_message(
        f"📜 **【個人花卉背包】** (持有：**{user_data.get('coins', 0)}** 💮)\n請從下方選單選擇你想欣賞的花朵：",
        view=view,
        ephemeral=True
    )

# --- /show (公開展示清單) ---
@bot.tree.command(name="show", description="向頻道大家展示你擁有的花朵與財產")
async def show(interaction: discord.Interaction):
    inventory = load_inventory()
    user_id = str(interaction.user.id)
    user_data = get_user_data(inventory, user_id)
    user_flowers = user_data.get("flowers", {})

    embed = discord.Embed(title=f"🌸 {interaction.user.display_name} 的花卉收藏展", color=0x98FB98)
    embed.add_field(name="👛 錢包資產", value=f"**{user_data.get('coins', 0)}** 💮", inline=False)

    if not user_flowers:
        embed.add_field(name="收藏列表", value="*目前還沒有任何花朵*", inline=False)
    else:
        flower_list = "\n".join([f"• **{name}** × {count}" for name, count in user_flowers.items()])
        embed.add_field(name="收藏列表", value=flower_list, inline=False)

    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=embed, ephemeral=False)

# --- /send (贈送花朵) ---
@bot.tree.command(name="send", description="贈送花朵給指定的玩家")
@app_commands.describe(target="接收花朵的玩家", flower_name="要贈送的花朵名稱", amount="數量（預設 1）")
async def send_flower(interaction: discord.Interaction, target: discord.Member, flower_name: str, amount: int = 1):
    if amount <= 0:
        await interaction.response.send_message("❌ 數量必須大於 0！", ephemeral=True)
        return
    if target.id == interaction.user.id:
        await interaction.response.send_message("❌ 你不能贈送花朵給自己！", ephemeral=True)
        return

    inventory = load_inventory()
    sender_data = get_user_data(inventory, str(interaction.user.id))
    target_data = get_user_data(inventory, str(target.id))

    sender_flowers = sender_data["flowers"]
    current_count = sender_flowers.get(flower_name, 0)

    if current_count < amount:
        await interaction.response.send_message(f"❌ 你的背包裡沒有足夠的 **{flower_name}**（目前擁有：{current_count}）！", ephemeral=True)
        return

    sender_flowers[flower_name] -= amount
    if sender_flowers[flower_name] <= 0:
        del sender_flowers[flower_name]

    target_data["flowers"][flower_name] = target_data["flowers"].get(flower_name, 0) + amount

    save_inventory(inventory)
    await interaction.response.send_message(f"🎁 {interaction.user.mention} 成功贈送了 **{flower_name}** × {amount} 給 {target.mention}！")

# --- /trade (雙向交易) ---
@bot.tree.command(name="trade", description="發起雙方花朵交易")
@app_commands.describe(
    target="交易對象",
    my_flower="你想給出的花朵名稱",
    target_flower="你希望換取的花朵名稱",
    my_amount="你想給出的數量（預設 1）",
    target_amount="你希望換取的數量（預設 1）"
)
async def trade(
    interaction: discord.Interaction,
    target: discord.Member,
    my_flower: str,
    target_flower: str,
    my_amount: int = 1,
    target_amount: int = 1
):
    if target.id == interaction.user.id:
        await interaction.response.send_message("❌ 你不能和自己交易！", ephemeral=True)
        return
    if my_amount <= 0 or target_amount <= 0:
        await interaction.response.send_message("❌ 交易數量必須大於 0！", ephemeral=True)
        return

    inventory = load_inventory()
    s_data = get_user_data(inventory, str(interaction.user.id))
    t_data = get_user_data(inventory, str(target.id))

    if s_data["flowers"].get(my_flower, 0) < my_amount:
        await interaction.response.send_message(f"❌ 你背包里的 **{my_flower}** 數量不足！", ephemeral=True)
        return
    if t_data["flowers"].get(target_flower, 0) < target_amount:
        await interaction.response.send_message(f"❌ {target.display_name} 的背包裡沒有足夠的 **{target_flower}**！", ephemeral=True)
        return

    view = TradeView(interaction.user, target, my_flower, my_amount, target_flower, target_amount)
    await interaction.response.send_message(
        content=f"🤝 {target.mention}，{interaction.user.mention} 想用 **{my_flower}** × {my_amount} 與你交換 **{target_flower}** × {target_amount}！請點擊下方按鈕確認：",
        view=view
    )

# 7. 啟動 Bot
TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ 錯誤：未設置 DISCORD_TOKEN 環境變數！")