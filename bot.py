import discord
from discord.ext import commands, tasks
from discord import app_commands, Interaction
import sqlite3
import os
from datetime import datetime, timedelta
import sys
import openpyxl
import random
from zoneinfo import ZoneInfo

# Discord Bot v2.0 - Raffle Feature Added

# 設置 UTF-8 編碼支持
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 初始化機器人
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# 全局錯誤處理
@bot.tree.error
async def on_app_command_error(interaction: Interaction, error: app_commands.AppCommandError):
    """全局命令錯誤處理"""
    print(f"[ERROR] 命令錯誤: {type(error).__name__}: {error}")
    # 不嘗試回應，因為互動可能已經過期或無效
    # 每個命令都應該有自己的錯誤處理

# 數據庫設置
DB_PATH = 'game_data.db'

# 身份組設置
REQUIRED_ROLE_ID = 1478704657512796292  # 拍賣行填寫權限身份組
REMINDER_ROLE_ID = 1478704657512796292  # 定時提醒身份組

# 頻道設置
ANNOUNCEMENT_CHANNEL_ID = 1323970071869259806  # 每日報名名單公告頻道
REMINDER_CHANNEL_ID = 1478705299845152768  # 定時提醒頻道

# 台灣時區
TZ_TAIPEI = ZoneInfo("Asia/Taipei")

# 最後一次發送公告的日期（用於防止重複發送）
last_announcement_date = None

# 定時提醒狀態追蹤（防止重複發送）
last_reminder_mon_wed_fri_12pm_date = None
last_reminder_sat_11am_date = None
last_reminder_sun_8_55pm_date = None
last_reminder_sun_9_25pm_date = None
last_reminder_biweekly_thu_9_45pm_date = None
last_reminder_wed_9pm_date = None
last_reminder_equip_date = None

# 迷霧模式狀態
mist_mode_enabled = False
mist_mode_channel_id = None

# 優先級用戶名列表
def load_priority_usernames():
    """從 id.xlsx 讀取優先級用戶名"""
    try:
        wb = openpyxl.load_workbook('id.xlsx')
        ws = wb.active
        priority_users = set()

        for row in ws.iter_rows(values_only=True):
            if row and row[0] and row[0] != 'ID':  # 跳過表頭
                username = str(row[0]).strip()
                priority_users.add(username)

        print(f"[INFO] 已加載 {len(priority_users)} 個優先級用戶: {priority_users}")
        return priority_users
    except Exception as e:
        print(f"[ERROR] 讀取優先級用戶失敗: {e}")
        return set()

PRIORITY_USERNAMES = load_priority_usernames()

def init_database():
    """初始化數據庫"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT NOT NULL,
        game_name TEXT NOT NULL,
        equip_days INTEGER NOT NULL,
        max_fate_cost INTEGER NOT NULL,
        is_priority INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        queue_priority INTEGER DEFAULT 0
    )''')

    # 添加 is_priority 列如果不存在
    try:
        c.execute('ALTER TABLE users ADD COLUMN is_priority INTEGER DEFAULT 0')
        print("[INFO] 已添加 is_priority 列")
    except sqlite3.OperationalError:
        pass  # 列已存在
    
    # 添加 queue_priority 列用於控制優先級用戶插隊
    try:
        c.execute('ALTER TABLE users ADD COLUMN queue_priority INTEGER DEFAULT 0')
        print("[INFO] 已添加 queue_priority 列用於優先級用戶插隊控制")
    except sqlite3.OperationalError:
        pass  # 列已存在

    # 創建抽獎表
    c.execute('''CREATE TABLE IF NOT EXISTS raffles (
        raffle_id INTEGER PRIMARY KEY AUTOINCREMENT,
        creator_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        winners_count INTEGER NOT NULL,
        message_id INTEGER,
        channel_id INTEGER,
        start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        end_time TIMESTAMP NOT NULL,
        status TEXT DEFAULT 'active'
    )''')

    # 創建抽獎報名表
    c.execute('''CREATE TABLE IF NOT EXISTS raffle_entries (
        entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
        raffle_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        username TEXT NOT NULL,
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(raffle_id) REFERENCES raffles(raffle_id),
        UNIQUE(raffle_id, user_id)
    )''')

    conn.commit()
    conn.close()

def get_actual_dates(user_id):
    """計算用戶的實際開始和結束日期

    根據優先級和提交順序計算日期：
    1. 優先級用戶排在前面，按提交時間排序
    2. 普通用戶排在後面，按提交時間排序
    """
    from datetime import timedelta

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 獲取所有用戶，按優先級、隊列優先級和時間排序
    # queue_priority=1的用戶排在最前面（在優先級用戶之中）
    c.execute('''SELECT user_id, equip_days, created_at, queue_priority
                 FROM users
                 ORDER BY 
                   CASE 
                     WHEN queue_priority = 1 AND is_priority = 1 THEN 0
                     ELSE 1
                   END,
                   is_priority DESC, 
                   created_at ASC''')
    all_users = c.fetchall()

    # 查詢目標用戶的信息
    c.execute('SELECT created_at, equip_days FROM users WHERE user_id = ?', (user_id,))
    user_info = c.fetchone()
    conn.close()

    if not user_info:
        return None, None

    user_created_at, user_equip_days = user_info

    # 計算實際日期
    current_start = None
    for uid, equip_days, created_at, queue_priority in all_users:
        if current_start is None:
            try:
                current_start = datetime.fromisoformat(created_at)
                # 如果是offset-naive的，添加時區信息
                if current_start.tzinfo is None:
                    current_start = current_start.replace(tzinfo=TZ_TAIPEI)
            except:
                return None, None

        if uid == user_id:
            end_date = current_start + timedelta(days=user_equip_days)
            return current_start, end_date

        # 計算下一個用戶的開始日期
        current_start = current_start + timedelta(days=equip_days) + timedelta(days=1)

    return None, None

def get_current_executing_user():
    """獲取當前正在收裝備的用戶ID（基於計算得出的開始/結束日期）"""
    from datetime import timedelta
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 獲取所有用戶，按優先級和隊列優先級排序
    c.execute('''SELECT user_id, equip_days, created_at, queue_priority
                 FROM users
                 ORDER BY 
                   CASE 
                     WHEN queue_priority = 1 AND is_priority = 1 THEN 0
                     ELSE 1
                   END,
                   is_priority DESC, 
                   created_at ASC''')
    all_users = c.fetchall()
    conn.close()

    if not all_users:
        return None

    # 計算第一個用戶的開始和結束日期
    try:
        current_start = datetime.fromisoformat(all_users[0][2])
        # 如果是offset-naive的，添加時區信息
        if current_start.tzinfo is None:
            current_start = current_start.replace(tzinfo=TZ_TAIPEI)
    except:
        return None
    
    current_end = current_start + timedelta(days=all_users[0][1])
    
    now = datetime.now(TZ_TAIPEI)
    
    # 檢查第一個用戶是否在進行中
    if current_start.replace(hour=0, minute=0, second=0, microsecond=0) <= now.replace(hour=0, minute=0, second=0, microsecond=0) <= current_end.replace(hour=23, minute=59, second=59):
        return all_users[0][0]  # 返回用戶ID
    
    return None

class EquipmentForm(discord.ui.Modal):
    """拍賣行信息表單"""
    title = "拍賣行信息表單"

    game_name = discord.ui.TextInput(
        label="1. 遊戲名稱",
        placeholder="輸入你的遊戲名稱",
        required=True,
        max_length=100
    )
    equip_days = discord.ui.TextInput(
        label="2. 收裝備天數",
        placeholder="例如：1 (最多 3 天)",
        required=True,
        max_length=1
    )
    max_fate_cost = discord.ui.TextInput(
        label="3. 天命最多花費多少",
        placeholder="例如：500 (最少 50)",
        required=True,
        max_length=10
    )

    async def on_submit(self, interaction: Interaction):
        # 先延遲回應以確保有足夠時間處理數據庫操作
        await interaction.response.defer(ephemeral=True)

        try:
            # 驗證輸入
            try:
                equip_days = int(self.equip_days.value)
                max_fate_cost = int(self.max_fate_cost.value)
            except ValueError:
                await interaction.followup.send(
                    "[ERROR] 天數和花費必須是數字",
                    ephemeral=True
                )
                return

            # 驗證天數範圍 (1-3天)
            if equip_days < 1 or equip_days > 3:
                await interaction.followup.send(
                    "[ERROR] 收裝備天數必須介於 1-3 天之間",
                    ephemeral=True
                )
                return

            # 驗證天命花費最低值 (最少50)
            if max_fate_cost < 50:
                await interaction.followup.send(
                    "[ERROR] 天命花費最少為 50",
                    ephemeral=True
                )
                return

            # 檢查是否為優先級用戶
            is_priority = 1 if interaction.user.name in PRIORITY_USERNAMES else 0
            
            # 判斷是否需要優先級插隊
            queue_priority = 0
            if is_priority == 1:
                # 檢查是否有人正在收裝備
                current_user_id = get_current_executing_user()
                if current_user_id is not None and current_user_id != interaction.user.id:
                    # 有其他人正在進行中，新的優先級用戶應該排在第二順位
                    queue_priority = 1

            # 保存到數據庫
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()

            # 檢查是否已存在此用戶
            c.execute('SELECT equip_days, created_at FROM users WHERE user_id = ?', (interaction.user.id,))
            existing = c.fetchone()

            now = datetime.now(TZ_TAIPEI)
            now_iso = now.isoformat()

            # 如果用戶已經存在，檢查他們的報名日期是否結束
            if existing:
                old_equip_days, created_at = existing
                # 計算舊的結束日期
                try:
                    start_date = datetime.fromisoformat(created_at)
                    # 如果是offset-naive的，添加時區信息
                    if start_date.tzinfo is None:
                        start_date = start_date.replace(tzinfo=TZ_TAIPEI)
                except:
                    # 如果解析失敗，刪除舊記錄
                    c.execute('DELETE FROM users WHERE user_id = ?', (interaction.user.id,))
                    conn.commit()
                    # 繼續創建新記錄
                    start_date = None
                
                if start_date:
                    end_date = start_date + timedelta(days=old_equip_days)

                    # 檢查是否還在報名期間內（或尚未開始）
                    if now < end_date.replace(hour=23, minute=59, second=59):
                        # 報名還沒結束
                        remaining_days = (end_date.date() - now.date()).days + 1
                        await interaction.followup.send(
                            f"[ERROR] 你已經有一個活動中的報名！\n"
                            f"預計結束日期: {end_date.strftime('%m月%d號')}\n"
                            f"請等待報名結束後再重新報名 (還有約 {remaining_days} 天)",
                            ephemeral=True
                        )
                        conn.close()
                        return

                    # 報名已結束，刪除舊記錄
                    c.execute('DELETE FROM users WHERE user_id = ?', (interaction.user.id,))
                else:
                    # 無法解析日期，直接刪除舊記錄
                    c.execute('DELETE FROM users WHERE user_id = ?', (interaction.user.id,))

            # 創建新記錄（無論是新用戶還是舊報名已結束的用戶）
            c.execute('''INSERT INTO users
                (user_id, username, game_name, equip_days, max_fate_cost, is_priority, created_at, queue_priority)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (interaction.user.id, interaction.user.name,
                 self.game_name.value, equip_days, max_fate_cost, is_priority, now_iso, queue_priority))

            conn.commit()
            conn.close()

            # 回應用戶（僅用戶可見）
            priority_text = "✨ [優先級用戶]" if is_priority else ""
            queue_status = ""
            if queue_priority == 1:
                queue_status = "\n\n🔔 [特別提醒] 由於你是優先級用戶且當前有人在收裝備，你已加入優先隊列，將排在第二順位！"
            
            await interaction.followup.send(
                f"[OK] 信息已保存! {priority_text}{queue_status}\n\n"
                f"遊戲名稱: {self.game_name.value}\n"
                f"收裝備天數: {equip_days} 天\n"
                f"最高天命花費: {max_fate_cost}\n\n"
                f"📢 收裝備排序名單將在今天晚上 22:00 公布(超過22點就是隔天公布)",
                ephemeral=True
            )
        except Exception as e:
            print(f"[ERROR] Modal提交錯誤: {type(e).__name__}: {str(e)}")
            try:
                await interaction.followup.send(
                    f"[ERROR] 出現錯誤: {str(e)}",
                    ephemeral=True
                )
            except:
                pass

class RaffleForm(discord.ui.Modal):
    """抽獎活動表單"""
    title = "創建抽獎活動"

    title_input = discord.ui.TextInput(
        label="1. 活動名稱",
        placeholder="輸入活動名稱",
        required=True,
        max_length=100
    )
    content_input = discord.ui.TextInput(
        label="2. 活動內容",
        placeholder="活動詳細說明",
        required=True,
        max_length=1000
    )
    days_input = discord.ui.TextInput(
        label="3. 活動天數",
        placeholder="例如：3（代表3天後抽獎）",
        required=True,
        max_length=2
    )
    winners_input = discord.ui.TextInput(
        label="4. 得獎人數",
        placeholder="例如：5",
        required=True,
        max_length=3
    )

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            # 提取並驗證輸入
            title = self.title_input.value
            content = self.content_input.value

            try:
                days = int(self.days_input.value)
                winners_count = int(self.winners_input.value)
            except ValueError:
                await interaction.followup.send(
                    "[ERROR] 活動天數和得獎人數必須是數字",
                    ephemeral=True
                )
                return

            # 驗證天數範圍
            if days < 1 or days > 30:
                await interaction.followup.send(
                    "[ERROR] 活動天數必須介於 1-30 天之間",
                    ephemeral=True
                )
                return

            # 驗證得獎人數
            if winners_count < 1 or winners_count > 100:
                await interaction.followup.send(
                    "[ERROR] 得獎人數必須介於 1-100 之間",
                    ephemeral=True
                )
                return

            # 計算結束時間
            now = datetime.now(TZ_TAIPEI)
            end_time = now + timedelta(days=days)
            end_time_iso = end_time.isoformat()
            now_iso = now.isoformat()

            # 保存到數據庫
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()

            c.execute('''INSERT INTO raffles
                (creator_id, title, content, winners_count, start_time, end_time, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (interaction.user.id, title, content,
                 winners_count, now_iso, end_time_iso, 'active'))

            raffle_id = c.lastrowid
            conn.commit()
            conn.close()

            # 發送抽獎公告
            embed = discord.Embed(
                title=f"🎰 {title}",
                description=content,
                color=discord.Color.gold()
            )
            embed.add_field(name="活動結束時間", value=end_time.strftime("%Y-%m-%d %H:%M:%S"), inline=False)
            embed.add_field(name="得獎人數", value=f"{winners_count} 人", inline=False)
            embed.add_field(name="活動天數", value=f"{days} 天", inline=False)
            embed.set_footer(text=f"抽獎 ID: {raffle_id} | 點擊下方按鈕報名")

            view = RaffleButtonView(raffle_id)
            msg = await interaction.channel.send(embed=embed, view=view)

            # 保存訊息 ID
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('UPDATE raffles SET message_id = ?, channel_id = ? WHERE raffle_id = ?',
                     (msg.id, interaction.channel_id, raffle_id))
            conn.commit()
            conn.close()

            await interaction.followup.send(
                f"✅ 抽獎活動已創建！\n抽獎 ID: {raffle_id}\n結束時間: {end_time.strftime('%m/%d %H:%M')}",
                ephemeral=True
            )
        except Exception as e:
            print(f"[ERROR] 抽獎表單錯誤: {type(e).__name__}: {str(e)}")
            try:
                await interaction.followup.send(
                    f"[ERROR] 出現錯誤: {str(e)}",
                    ephemeral=True
                )
            except:
                pass


class RaffleButtonView(discord.ui.View):
    """抽獎按鈕視圖"""
    def __init__(self, raffle_id):
        super().__init__(timeout=None)
        self.raffle_id = raffle_id

    @discord.ui.button(label="報名抽獎")
    async def join_button(self, interaction: Interaction, button: discord.ui.Button):
        """報名或取消報名"""
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception as e:
            print(f"[ERROR] defer 失敗: {str(e)}")
            return

        try:
            print(f"[DEBUG] 報名抽獎 - raffle_id: {self.raffle_id}, user: {interaction.user.name} ({interaction.user.id})")
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()

            # 檢查用戶是否已報名
            c.execute('SELECT entry_id FROM raffle_entries WHERE raffle_id = ? AND user_id = ?',
                     (self.raffle_id, interaction.user.id))
            existing = c.fetchone()

            if existing:
                # 已報名，移除報名
                c.execute('DELETE FROM raffle_entries WHERE raffle_id = ? AND user_id = ?',
                         (self.raffle_id, interaction.user.id))
                message = "✅ 已取消報名"
                print(f"[DEBUG] 取消報名成功 - raffle_id: {self.raffle_id}, user_id: {interaction.user.id}")
            else:
                # 未報名，添加報名
                c.execute('''INSERT INTO raffle_entries (raffle_id, user_id, username)
                    VALUES (?, ?, ?)''',
                    (self.raffle_id, interaction.user.id, interaction.user.name))
                message = "✅ 報名成功"
                print(f"[DEBUG] 報名成功 - raffle_id: {self.raffle_id}, user_id: {interaction.user.id}")

            conn.commit()
            conn.close()

            try:
                await interaction.followup.send(message, ephemeral=True)
            except Exception as send_error:
                print(f"[ERROR] 發送報名結果失敗: {str(send_error)}")
        except sqlite3.IntegrityError as int_error:
            print(f"[ERROR] 報名重複或數據約束錯誤: {str(int_error)}")
            try:
                await interaction.followup.send("✅ 已取消報名", ephemeral=True)
            except:
                pass
        except sqlite3.Error as db_error:
            print(f"[ERROR] 報名數據庫錯誤: {str(db_error)}")
            try:
                await interaction.followup.send(f"[ERROR] 數據庫錯誤: {str(db_error)}", ephemeral=True)
            except:
                pass
        except Exception as e:
            print(f"[ERROR] 報名按鈕錯誤: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            try:
                await interaction.followup.send(f"[ERROR] 出現錯誤: {str(e)}", ephemeral=True)
            except:
                pass

    @discord.ui.button(label="查看報名人數")
    async def check_button(self, interaction: Interaction, button: discord.ui.Button):
        """查看報名人數"""
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception as e:
            print(f"[ERROR] defer 失敗: {str(e)}")
            return

        try:
            print(f"[DEBUG] 查看報名 - raffle_id: {self.raffle_id}, user: {interaction.user.name}")
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()

            # 獲取報名人數
            c.execute('SELECT COUNT(*) FROM raffle_entries WHERE raffle_id = ?', (self.raffle_id,))
            count_result = c.fetchone()
            count = count_result[0] if count_result else 0
            print(f"[DEBUG] 報名人數查詢成功: {count}")

            # 獲取抽獎資訊
            c.execute('SELECT title, end_time, winners_count FROM raffles WHERE raffle_id = ?',
                     (self.raffle_id,))
            raffle_info = c.fetchone()
            conn.close()

            if raffle_info:
                title, end_time, winners_count = raffle_info
                print(f"[DEBUG] 抽獎資訊: {title}, 結束時間: {end_time}")
                
                end_time_obj = datetime.fromisoformat(end_time)
                remaining = end_time_obj - datetime.now(TZ_TAIPEI)

                embed = discord.Embed(
                    title=f"📊 {title} - 報名統計",
                    color=discord.Color.blue()
                )
                embed.add_field(name="當前報名人數", value=f"{count} 人", inline=False)
                embed.add_field(name="得獎人數", value=f"{winners_count} 人", inline=False)
                embed.add_field(name="中獎機率", value=f"{round(winners_count/max(count,1)*100, 2)}%", inline=False)
                embed.add_field(name="距離結束", value=f"{remaining.days} 天 {remaining.seconds//3600} 小時", inline=False)

                try:
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    print(f"[DEBUG] 發送報名統計成功")
                except Exception as send_error:
                    print(f"[ERROR] 發送 followup 失敗: {str(send_error)}")
            else:
                print(f"[ERROR] 找不到抽獎資訊 - raffle_id: {self.raffle_id}")
                try:
                    await interaction.followup.send("[ERROR] 找不到抽獎資訊", ephemeral=True)
                except Exception as send_error:
                    print(f"[ERROR] 發送錯誤訊息失敗: {str(send_error)}")
        except sqlite3.Error as db_error:
            print(f"[ERROR] 數據庫錯誤: {str(db_error)}")
            try:
                await interaction.followup.send(f"[ERROR] 數據庫錯誤: {str(db_error)}", ephemeral=True)
            except:
                pass
        except Exception as e:
            print(f"[ERROR] 查看報名錯誤: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            try:
                await interaction.followup.send(f"[ERROR] 出現錯誤: {str(e)}", ephemeral=True)
            except:
                pass

    @discord.ui.button(label="結束抽獎 (管理員)")
    async def end_raffle_button(self, interaction: Interaction, button: discord.ui.Button):
        """提早結束抽獎 (管理員限定)"""
        await interaction.response.defer(ephemeral=True)

        try:
            # 檢查是否是管理員或有對應身份組
            if not (interaction.user.guild_permissions.administrator or
                   any(role.id == REQUIRED_ROLE_ID for role in interaction.user.roles)):
                await interaction.followup.send(
                    "[ERROR] 只有管理員可以提早結束抽獎",
                    ephemeral=True
                )
                return

            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()

            # 獲取抽獎信息
            c.execute('SELECT title, winners_count FROM raffles WHERE raffle_id = ? AND status = ?',
                     (self.raffle_id, 'active'))
            raffle_info = c.fetchone()

            if not raffle_info:
                await interaction.followup.send("[ERROR] 找不到活動或活動已結束", ephemeral=True)
                conn.close()
                return

            title, winners_count = raffle_info

            # 獲取所有報名者
            c.execute('SELECT user_id, username FROM raffle_entries WHERE raffle_id = ? ORDER BY RANDOM()',
                     (self.raffle_id,))
            entries = c.fetchall()

            if not entries:
                await interaction.followup.send("[ERROR] 沒有報名者", ephemeral=True)
                c.execute('UPDATE raffles SET status = ? WHERE raffle_id = ?', ('no_entries', self.raffle_id))
                conn.commit()
                conn.close()
                return

            # 隨機抽取得獎者
            selected_count = min(winners_count, len(entries))
            winners = entries[:selected_count]

            # 構建得獎者名單
            winners_list = []
            winners_mention = []
            for user_id, username in winners:
                winners_list.append(f"<@{user_id}> ({username})")
                winners_mention.append(f"<@{user_id}>")

            # 獲取頻道發布得獎名單
            c.execute('SELECT channel_id FROM raffles WHERE raffle_id = ?', (self.raffle_id,))
            channel_id = c.fetchone()[0]
            channel = discord.utils.get(interaction.guild.channels, id=channel_id)

            if channel:
                embed = discord.Embed(
                    title=f"🎉 {title} - 抽獎結果 (提早結束)",
                    color=discord.Color.gold()
                )
                embed.add_field(
                    name=f"得獎者 ({selected_count}/{winners_count})",
                    value="\n".join(winners_list),
                    inline=False
                )
                embed.add_field(
                    name="總報名人數",
                    value=f"{len(entries)} 人",
                    inline=False
                )

                # 發送訊息
                mention_str = " ".join(winners_mention)
                await channel.send(f"🎊 恭喜得獎者！{mention_str}", embed=embed)

            # 更新狀態
            c.execute('UPDATE raffles SET status = ? WHERE raffle_id = ?', ('drawn', self.raffle_id))
            conn.commit()
            conn.close()

            await interaction.followup.send(
                f"✅ 抽獎已提早結束！\n得獎人數: {selected_count} 人",
                ephemeral=True
            )
        except Exception as e:
            print(f"[ERROR] 提早結束抽獎錯誤: {str(e)}")
            await interaction.followup.send(
                f"[ERROR] 出現錯誤: {str(e)}",
                ephemeral=True
            )

@bot.event
async def on_ready():
    """機器人上線事件"""
    print(f'{bot.user} 已上線！')
    print(f"機器人 ID: {bot.user.id}")

    # 啟動定時提醒任務
    if not daily_reminder.is_running():
        daily_reminder.start()
        print("[INFO] 已啟動每日提醒任務")

    if not announcement_schedule.is_running():
        announcement_schedule.start()
        print("[INFO] 已啟動每日名單公告任務")

    # 啟動新的定時提醒任務
    if not reminder_mon_wed_fri_12pm.is_running():
        reminder_mon_wed_fri_12pm.start()
        print("[INFO] 已啟動周一/三/五中午提醒")

    if not reminder_sat_11am.is_running():
        reminder_sat_11am.start()
        print("[INFO] 已啟動周六早上提醒")

    if not reminder_sun_8_55pm.is_running():
        reminder_sun_8_55pm.start()
        print("[INFO] 已啟動周日20:55提醒")

    if not reminder_sun_9_25pm.is_running():
        reminder_sun_9_25pm.start()
        print("[INFO] 已啟動周日21:25提醒")

    if not reminder_biweekly_thu_9_45pm.is_running():
        reminder_biweekly_thu_9_45pm.start()
        print("[INFO] 已啟動兩週一次週四提醒")

    if not reminder_wed_9pm.is_running():
        reminder_wed_9pm.start()
        print("[INFO] 已啟動周三晚上提醒")

    if not check_raffle_ended.is_running():
        check_raffle_ended.start()
        print("[INFO] 已啟動抽獎檢查任務")

    try:
        synced = await bot.tree.sync()
        print(f"[OK] 已同步 {len(synced)} 個命令")
        for cmd in synced:
            print(f"  - {cmd.name}")
    except Exception as e:
        print(f"[ERROR] 同步命令時出錯: {e}")
        import traceback
        traceback.print_exc()

@tasks.loop(minutes=1)
async def daily_reminder():
    """每天晚上22:10提醒明天要開始收裝備的人"""
    global last_reminder_equip_date
    try:
        now = datetime.now(TZ_TAIPEI)
        
        # 檢查是否是22:10
        if now.hour != 22 or now.minute != 10:
            return
        
        # 檢查是否已在今天發送過（防止重複發送）
        if last_reminder_equip_date == now.date():
            return

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # 獲取所有用戶，按優先級、隊列優先級和時間排序
        c.execute('''SELECT user_id, username, equip_days, created_at, is_priority, queue_priority
                     FROM users
                     ORDER BY 
                       CASE 
                         WHEN queue_priority = 1 AND is_priority = 1 THEN 0
                         ELSE 1
                       END,
                       is_priority DESC, 
                       created_at ASC''')
        all_users = c.fetchall()
        conn.close()

        if not all_users:
            return

        # 計算所有用戶的開始日期
        tomorrow = (datetime.now(TZ_TAIPEI) + timedelta(days=1)).date()
        users_starting_tomorrow = []

        current_start = None
        for user_id, username, equip_days, created_at, is_priority, queue_priority in all_users:
            if current_start is None:
                try:
                    current_start = datetime.fromisoformat(created_at)
                    # 如果是offset-naive的，添加時區信息
                    if current_start.tzinfo is None:
                        current_start = current_start.replace(tzinfo=TZ_TAIPEI)
                except:
                    continue

            start_date = current_start.date()

            # 檢查是否是明天開始
            if start_date == tomorrow:
                users_starting_tomorrow.append((user_id, username))

            # 計算下一個用戶的開始日期
            current_start = current_start + timedelta(days=equip_days) + timedelta(days=1)

        # 如果有人明天開始，發送提醒
        if users_starting_tomorrow:
            channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
            if channel:
                for user_id, username in users_starting_tomorrow:
                    message = f"<@{user_id}> 可以開始收裝備啦～"
                    await channel.send(message)
                print(f"[INFO] 已發送明日收裝備提醒: {[username for _, username in users_starting_tomorrow]}")
            
            last_reminder_equip_date = now.date()
    except Exception as e:
        print(f"[ERROR] 定時提醒任務出錯: {e}")

@tasks.loop(minutes=1)
async def announcement_schedule():
    """每天晚上22:00發布當天的報名名單"""
    global last_announcement_date
    try:
        # 使用台灣時區獲取當前時間
        now = datetime.now(TZ_TAIPEI)
        
        # 檢查是否是22:00~22:05分鐘之間
        if now.hour != 22 or now.minute > 5:
            return
        
        # 檢查是否已在今天發送過（防止重複發送）
        if last_announcement_date == now.date():
            return

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # 獲取所有用戶，按優先級、隊列優先級和時間排序
        c.execute('''SELECT username, game_name, equip_days, created_at, is_priority, user_id, queue_priority
                     FROM users
                     ORDER BY 
                       CASE 
                         WHEN queue_priority = 1 AND is_priority = 1 THEN 0
                         ELSE 1
                       END,
                       is_priority DESC, 
                       created_at ASC''')
        all_users = c.fetchall()
        conn.close()

        if not all_users:
            return

        channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        if not channel:
            print(f"[ERROR] 找不到公告頻道 ID: {ANNOUNCEMENT_CHANNEL_ID}")
            return

        # 構建報名名單
        embed = discord.Embed(
            title="📋 今日報名名單 - 拍賣行排序",
            color=discord.Color.gold(),
            timestamp=datetime.now(TZ_TAIPEI)
        )

        current_start = None
        for i, (username, game_name, equip_days, created_at, is_priority, user_id, queue_priority) in enumerate(all_users, 1):
            if current_start is None:
                try:
                    current_start = datetime.fromisoformat(created_at)
                    # 如果是offset-naive的，添加時區信息
                    if current_start.tzinfo is None:
                        current_start = current_start.replace(tzinfo=TZ_TAIPEI)
                except:
                    continue

            start_date = current_start
            end_date = start_date + timedelta(days=equip_days)
            start_str = start_date.strftime("%m月%d號")
            end_str = end_date.strftime("%m月%d號")

            priority_badge = "✨" if is_priority else ""
            queue_badge = "📍" if queue_priority == 1 else ""  # 標記優先級插隊用戶
            user_mention = f"<@{user_id}>"
            embed.add_field(
                name=f"#{i} {priority_badge}{queue_badge} {username}",
                value=f"遊戲名稱: {game_name}\n開始日期: {start_str}\n收裝備天數: {equip_days} 天\n結束日期: {end_str}",
                inline=False
            )

            current_start = end_date + timedelta(days=1)

        embed.set_footer(text=f"總共 {len(all_users)} 個報名用戶 | ✨ 優先級用戶 | 📍 優先隊列用戶")

        # 發送公告
        await channel.send(embed=embed, view=CancelSignupView())
        last_announcement_date = now.date()
        print(f"[INFO] 已發送當日報名名單公告，共 {len(all_users)} 人")

    except Exception as e:
        print(f"[ERROR] 名單公告任務出錯: {e}")

# 定時提醒系列任務
@tasks.loop(minutes=1)
async def reminder_mon_wed_fri_12pm():
    """每週一、三、五 中午12點提醒"""
    global last_reminder_mon_wed_fri_12pm_date
    try:
        now = datetime.now(TZ_TAIPEI)
        weekday = now.weekday()  # 0=Monday, 6=Sunday

        # 檢查是否是週一(0)、週三(2)、週五(4) 且是12:00點
        if weekday in [0, 2, 4] and now.hour == 12 and now.minute == 0:
            # 檢查是否已在今天發送過
            if last_reminder_mon_wed_fri_12pm_date == now.date():
                return
            
            channel = bot.get_channel(REMINDER_CHANNEL_ID)
            if channel:
                role_mention = f"<@&{REMINDER_ROLE_ID}>"
                message = f"{role_mention} 大家今天記得鎮魔呦～"
                await channel.send(message)
                last_reminder_mon_wed_fri_12pm_date = now.date()
                print(f"[INFO] 已發送週一/三/五中午提醒")
    except Exception as e:
        print(f"[ERROR] 周一三五提醒出錯: {e}")

@tasks.loop(minutes=1)
async def reminder_sat_11am():
    """每週六 早上11點提醒"""
    global last_reminder_sat_11am_date
    try:
        now = datetime.now(TZ_TAIPEI)
        weekday = now.weekday()  # 5=Saturday

        if weekday == 5 and now.hour == 11 and now.minute == 0:
            # 檢查是否已在今天發送過
            if last_reminder_sat_11am_date == now.date():
                return
            
            channel = bot.get_channel(REMINDER_CHANNEL_ID)
            if channel:
                role_mention = f"<@&{REMINDER_ROLE_ID}>"
                message = f"{role_mention} 今晚9點有宗門亂鬥～記得報名參加"
                await channel.send(message)
                last_reminder_sat_11am_date = now.date()
                print(f"[INFO] 已發送週六早上提醒")
    except Exception as e:
        print(f"[ERROR] 周六提醒出錯: {e}")

@tasks.loop(minutes=1)
async def reminder_sun_8_55pm():
    """每週日 晚上8:55分提醒"""
    global last_reminder_sun_8_55pm_date
    try:
        now = datetime.now(TZ_TAIPEI)
        weekday = now.weekday()  # 6=Sunday

        if weekday == 6 and now.hour == 20 and now.minute == 55:
            # 檢查是否已在今天發送過
            if last_reminder_sun_8_55pm_date == now.date():
                return
            
            channel = bot.get_channel(REMINDER_CHANNEL_ID)
            if channel:
                role_mention = f"<@&{REMINDER_ROLE_ID}>"
                message = f"{role_mention} 八荒要開始啦！大家速速上線"
                await channel.send(message)
                last_reminder_sun_8_55pm_date = now.date()
                print(f"[INFO] 已發送週日20:55提醒")
    except Exception as e:
        print(f"[ERROR] 周日20:55提醒出錯: {e}")

@tasks.loop(minutes=1)
async def reminder_sun_9_25pm():
    """每週日 晚上9:25分提醒"""
    global last_reminder_sun_9_25pm_date
    try:
        now = datetime.now(TZ_TAIPEI)
        weekday = now.weekday()  # 6=Sunday

        if weekday == 6 and now.hour == 21 and now.minute == 25:
            # 檢查是否已在今天發送過
            if last_reminder_sun_9_25pm_date == now.date():
                return
            
            channel = bot.get_channel(REMINDER_CHANNEL_ID)
            if channel:
                role_mention = f"<@&{REMINDER_ROLE_ID}>"
                message = f"{role_mention} 天下要開打了！上線集合集合"
                await channel.send(message)
                last_reminder_sun_9_25pm_date = now.date()
                print(f"[INFO] 已發送週日21:25提醒")
    except Exception as e:
        print(f"[ERROR] 周日21:25提醒出錯: {e}")

@tasks.loop(minutes=1)
async def reminder_biweekly_thu_9_45pm():
    """每兩週的週四 晚上9:45分提醒（從2026年4月17日開始）"""
    global last_reminder_biweekly_thu_9_45pm_date
    try:
        now = datetime.now(TZ_TAIPEI)
        weekday = now.weekday()  # 3=Thursday

        if weekday == 3 and now.hour == 21 and now.minute == 45:
            # 計算距離基準日期 2026-04-17 的天數
            base_date = datetime(2026, 4, 17).date()
            current_date = now.date()
            days_diff = (current_date - base_date).days

            # 如果是基準日期的倍數個14天（偶數週）
            if days_diff >= 0 and days_diff % 14 == 0:
                # 檢查是否已在今天發送過
                if last_reminder_biweekly_thu_9_45pm_date == now.date():
                    return
                
                channel = bot.get_channel(REMINDER_CHANNEL_ID)
                if channel:
                    role_mention = f"<@&{REMINDER_ROLE_ID}>"
                    message = f"{role_mention} 仙魔訣要結算啦！記得上線ko對手～"
                    await channel.send(message)
                    last_reminder_biweekly_thu_9_45pm_date = now.date()
                    print(f"[INFO] 已發送兩週一次的週四21:45提醒")
    except Exception as e:
        print(f"[ERROR] 兩週提醒出錯: {e}")

@tasks.loop(minutes=1)
async def reminder_wed_9pm():
    """每週三晚上九點提醒"""
    global last_reminder_wed_9pm_date
    try:
        now = datetime.now(TZ_TAIPEI)
        weekday = now.weekday()  # 2=Wednesday

        if weekday == 2 and now.hour == 21 and now.minute == 0:
            # 檢查是否已在今天發送過
            if last_reminder_wed_9pm_date == now.date():
                return
            
            channel = bot.get_channel(REMINDER_CHANNEL_ID)
            if channel:
                role_mention = f"<@&{REMINDER_ROLE_ID}>"
                message = f"{role_mention} 宗門對決要結束了！還有次數的成員記得打呦"
                await channel.send(message)
                last_reminder_wed_9pm_date = now.date()
                print(f"[INFO] 已發送週三晚上提醒")
    except Exception as e:
        print(f"[ERROR] 周三晚上提醒出錯: {e}")

@tasks.loop(minutes=1)
async def check_raffle_ended():
    """每分鐘檢查是否有抽獎需要執行"""
    try:
        now = datetime.now(TZ_TAIPEI)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # 查詢所有已結束且未執行抽獎的活動
        c.execute('''SELECT raffle_id, channel_id, message_id, title, winners_count
                     FROM raffles
                     WHERE status = 'active' AND end_time <= ?''',
                 (now.isoformat(),))
        ended_raffles = c.fetchall()

        for raffle_id, channel_id, message_id, title, winners_count in ended_raffles:
            # 獲取所有報名者
            c.execute('SELECT user_id, username FROM raffle_entries WHERE raffle_id = ? ORDER BY RANDOM()',
                     (raffle_id,))
            entries = c.fetchall()

            if not entries:
                # 沒有報名者，更新狀態
                c.execute('UPDATE raffles SET status = ? WHERE raffle_id = ?', ('no_entries', raffle_id))
                conn.commit()
                continue

            # 隨機抽取得獎者
            selected_count = min(winners_count, len(entries))
            winners = entries[:selected_count]

            # 構建得獎者名單
            winners_list = []
            winners_mention = []
            for user_id, username in winners:
                winners_list.append(f"<@{user_id}> ({username})")
                winners_mention.append(f"<@{user_id}>")

            # 發布得獎名單
            channel = bot.get_channel(channel_id)
            if channel:
                embed = discord.Embed(
                    title=f"🎉 {title} - 抽獎結果",
                    color=discord.Color.gold()
                )
                embed.add_field(
                    name=f"得獎者 ({selected_count}/{winners_count})",
                    value="\n".join(winners_list),
                    inline=False
                )
                embed.add_field(
                    name="總報名人數",
                    value=f"{len(entries)} 人",
                    inline=False
                )

                # 發送得獎訊息
                mention_str = " ".join(winners_mention)
                await channel.send(f"🎊 恭喜得獎者！{mention_str}", embed=embed)

            # 更新狀態為已抽獎
            c.execute('UPDATE raffles SET status = ? WHERE raffle_id = ?', ('drawn', raffle_id))
            conn.commit()

            print(f"[INFO] 抽獎 {raffle_id} ({title}) 已執行，得獎人數: {selected_count}")

        conn.close()
    except Exception as e:
        print(f"[ERROR] 抽獎檢查出錯: {e}")

@bot.tree.command(name="填寫拍賣行表單", description="填寫個人資訊")
async def fill_form(interaction: Interaction):
    """打開表單（需要特定身份組）"""
    # 檢查是否擁有指定身份組
    if not any(role.id == REQUIRED_ROLE_ID for role in interaction.user.roles):
        await interaction.response.send_message(
            "[ERROR] 此指令僅限擁有特定身分組的成員使用",
            ephemeral=True
        )
        return

    # 打開表單
    await interaction.response.send_modal(EquipmentForm())

@bot.tree.command(name="查詢報名人數", description="查詢所有用戶報名信息")
async def query_equipment(interaction: Interaction):
    """查詢所有用戶的裝備信息（管理員限定）"""
    try:
        # 檢查是否為管理員
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "[ERROR] 此指令僅限管理員使用",
                ephemeral=True
            )
            return

        from datetime import timedelta

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # 按優先級、隊列優先級和提交時間排序
        c.execute('''SELECT username, game_name, equip_days, created_at, is_priority, queue_priority
                     FROM users
                     ORDER BY 
                       CASE 
                         WHEN queue_priority = 1 AND is_priority = 1 THEN 0
                         ELSE 1
                       END,
                       is_priority DESC, 
                       created_at ASC''')
        all_users = c.fetchall()
        conn.close()

        if not all_users:
            await interaction.response.send_message(
                "還沒有人填寫表單",
                ephemeral=False
            )
            return

        # 構建輸出信息
        embed = discord.Embed(
            title="[STAT] 裝備收集統計",
            color=discord.Color.blue(),
            timestamp=datetime.now(TZ_TAIPEI)
        )

        # 計算所有用戶的實際開始和結束日期
        current_start = None
        for i, (username, game_name, equip_days, created_at, is_priority, queue_priority) in enumerate(all_users, 1):
            if current_start is None:
                # 第一個用戶的開始日期是他的填寫日期
                try:
                    current_start = datetime.fromisoformat(created_at)
                    # 如果是offset-naive的，添加時區信息
                    if current_start.tzinfo is None:
                        current_start = current_start.replace(tzinfo=TZ_TAIPEI)
                except:
                    continue

            start_date = current_start
            end_date = start_date + timedelta(days=equip_days)
            start_str = start_date.strftime("%m月%d號")
            end_str = end_date.strftime("%m月%d號")

            priority_badge = "✨" if is_priority else ""
            queue_badge = "📍" if queue_priority == 1 else ""
            embed.add_field(
                name=f"#{i} {priority_badge}{queue_badge} {username}",
                value=f"遊戲名稱: {game_name}\n開始日期: {start_str}\n收裝備天數: {equip_days} 天\n結束日期: {end_str}",
                inline=False
            )

            # 下一個用戶的開始日期是當前用戶結束日期的下一天
            current_start = end_date + timedelta(days=1)

        embed.set_footer(text=f"總共 {len(all_users)} 個用戶 | ✨ 優先級用戶 | 📍 優先隊列用戶")

        await interaction.response.send_message(embed=embed, view=CancelSignupView(), ephemeral=False)
    except Exception as e:
        await interaction.response.send_message(
            f"[ERROR] 查詢失敗: {str(e)}",
            ephemeral=True
        )

@bot.tree.command(name="測試公告", description="手動發送今日報名名單和明日提醒（管理員限定）")
async def test_announcement(interaction: Interaction):
    """手動發送名單公告和明日提醒（用於測試）"""
    try:
        # 檢查是否為管理員
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "[ERROR] 此指令僅限管理員使用",
                ephemeral=True
            )
            return

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # 獲取所有用戶，按優先級、隊列優先級和時間排序
        c.execute('''SELECT username, game_name, equip_days, created_at, is_priority, user_id, queue_priority
                     FROM users
                     ORDER BY 
                       CASE 
                         WHEN queue_priority = 1 AND is_priority = 1 THEN 0
                         ELSE 1
                       END,
                       is_priority DESC, 
                       created_at ASC''')
        all_users = c.fetchall()
        conn.close()

        if not all_users:
            await interaction.response.send_message(
                "還沒有人填寫表單",
                ephemeral=True
            )
            return

        channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message(
                f"[ERROR] 找不到公告頻道 ID: {ANNOUNCEMENT_CHANNEL_ID}",
                ephemeral=True
            )
            return

        # 構建報名名單
        embed = discord.Embed(
            title="📋 測試 - 今日報名名單 - 裝備收集排序",
            color=discord.Color.gold(),
            timestamp=datetime.now(TZ_TAIPEI)
        )

        current_start = None
        for i, (username, game_name, equip_days, created_at, is_priority, user_id, queue_priority) in enumerate(all_users, 1):
            if current_start is None:
                try:
                    current_start = datetime.fromisoformat(created_at)
                    # 如果是offset-naive的，添加時區信息
                    if current_start.tzinfo is None:
                        current_start = current_start.replace(tzinfo=TZ_TAIPEI)
                except:
                    continue

            start_date = current_start
            end_date = start_date + timedelta(days=equip_days)
            start_str = start_date.strftime("%m月%d號")
            end_str = end_date.strftime("%m月%d號")

            priority_badge = "✨" if is_priority else ""
            queue_badge = "📍" if queue_priority == 1 else ""
            embed.add_field(
                name=f"#{i} {priority_badge}{queue_badge} {username}",
                value=f"遊戲名稱: {game_name}\n開始日期: {start_str}\n收裝備天數: {equip_days} 天\n結束日期: {end_str}",
                inline=False
            )

            current_start = end_date + timedelta(days=1)

        embed.set_footer(text=f"測試公告 | 總共 {len(all_users)} 個報名用戶 | ✨ 優先級用戶 | 📍 優先隊列用戶")

        # 發送公告
        await channel.send(embed=embed, view=CancelSignupView())

        # 發送明日提醒（@第一個人）
        if all_users:
            first_user_id = all_users[0][5]  # 獲取第一個用戶的 ID
            first_user_name = all_users[0][0]  # 獲取第一個用戶的名稱
            mention = f"<@{first_user_id}>"
            reminder_msg = f"📢 測試提醒 - {mention} 你是名單第一位！\n\n明天就可以開始收取裝備，敬請期待！"
            await channel.send(reminder_msg)

        # 回應用戶
        await interaction.response.send_message(
            f"✅ 已發送測試公告！\n\n"
            f"- 名單已發送到 <#{ANNOUNCEMENT_CHANNEL_ID}>\n"
            f"- 已 @ {first_user_name}（第一位報名者）",
            ephemeral=True
        )

    except Exception as e:
        await interaction.response.send_message(
            f"[ERROR] 測試失敗: {str(e)}",
            ephemeral=True
        )

@bot.tree.command(name="查詢我的信息", description="查詢你自己填寫的信息")
async def query_my_info(interaction: Interaction):
    """查詢用戶自己的信息"""
    try:
        from datetime import timedelta

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT created_at, game_name, equip_days, max_fate_cost, is_priority, queue_priority FROM users WHERE user_id = ?',
                  (interaction.user.id,))
        result = c.fetchone()

        if not result:
            await interaction.response.send_message(
                "你還沒有填寫表單",
                ephemeral=True
            )
            conn.close()
            return

        created_at, game_name, equip_days, max_fate_cost, is_priority, queue_priority = result

        # 獲取排隊位置
        c.execute('''SELECT COUNT(*) FROM users
                     WHERE (is_priority > ? OR (is_priority = ? AND created_at < ?))''',
                  (is_priority, is_priority, created_at))
        position = c.fetchone()[0] + 1

        conn.close()

        # 檢查是否已過晚上22點（22點）
        current_hour = datetime.now(TZ_TAIPEI).hour
        is_after_10pm = current_hour >= 22

        embed = discord.Embed(
            title="你的表單信息",
            color=discord.Color.green(),
            timestamp=datetime.now(TZ_TAIPEI)
        )

        if is_priority:
            embed.add_field(name="身份", value="✨ 優先級用戶", inline=False)
        
        if queue_priority == 1:
            embed.add_field(name="隊列狀態", value="📍 優先隊列 (已插隊至第二順位)", inline=False)

        if is_after_10pm:
            # 晚上10點後顯示完整信息
            start_date, end_date = get_actual_dates(interaction.user.id)
            if start_date and end_date:
                # 確保start_date和end_date都有时区
                if start_date.tzinfo is None:
                    start_date = start_date.replace(tzinfo=TZ_TAIPEI)
                if end_date.tzinfo is None:
                    end_date = end_date.replace(tzinfo=TZ_TAIPEI)
                start_str = start_date.strftime("%m月%d號")
                end_str = end_date.strftime("%m月%d號")
                embed.add_field(name="排隊位置", value=f"第 {position} 位", inline=False)
                embed.add_field(name="遊戲名稱", value=game_name, inline=False)
                embed.add_field(name="開始日期", value=start_str, inline=False)
                embed.add_field(name="收裝備天數", value=f"{equip_days} 天", inline=False)
                embed.add_field(name="結束日期", value=end_str, inline=False)
                embed.add_field(name="最高天命花費", value=f"{max_fate_cost}", inline=False)
        else:
            # 10點前只顯示基本信息
            embed.add_field(name="遊戲名稱", value=game_name, inline=False)
            embed.add_field(name="收裝備天數", value=f"{equip_days} 天", inline=False)
            embed.add_field(name="最高天命花費", value=f"{max_fate_cost}", inline=False)
            embed.add_field(name="狀態", value="尚未公告名單\n\n收裝備排序名單將在晚上 22:00 公布(超過22點就是隔天公布) ", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(
            f"[ERROR] 查詢失敗: {str(e)}",
            ephemeral=True
        )

@bot.tree.command(name="創建抽獎", description="創建新的抽獎活動（僅限管理員）")
async def create_raffle(interaction: Interaction):
    """創建抽獎活動（需要特定身份組）"""
    # 檢查是否擁有指定身份組
    if not any(role.id == REQUIRED_ROLE_ID for role in interaction.user.roles):
        await interaction.response.send_message(
            "[ERROR] 此指令僅限擁有特定身分組的成員使用",
            ephemeral=True
        )
        return

    await interaction.response.send_modal(RaffleForm())

# 取消報名按鈕視圖
class CancelSignupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="❌ 取消我的報名", style=discord.ButtonStyle.red)
    async def cancel_signup(self, interaction: Interaction, button: discord.ui.Button):
        """取消用戶報名"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            
            # 檢查用戶是否存在
            c.execute('SELECT username, equip_days FROM users WHERE user_id = ?', 
                     (interaction.user.id,))
            user_result = c.fetchone()
            
            if not user_result:
                await interaction.followup.send(
                    "[ERROR] 找不到你的報名信息",
                    ephemeral=True
                )
                conn.close()
                return
            
            username, equip_days = user_result
            
            # 刪除用戶報名信息
            c.execute('DELETE FROM users WHERE user_id = ?', (interaction.user.id,))
            conn.commit()
            conn.close()
            
            # 發送確認訊息
            await interaction.followup.send(
                f"✅ 已取消你的報名！\n"
                f"用戶名: {username}\n"
                f"收裝備天數: {equip_days} 天\n\n"
                f"在你之後的報名者會自動替補往前！",
                ephemeral=True
            )
            
            print(f"[INFO] 用戶 {username} (ID: {interaction.user.id}) 已取消報名")
        except Exception as e:
            print(f"[ERROR] 取消報名出錯: {e}")
            await interaction.followup.send(
                f"[ERROR] 取消報名失敗: {str(e)}",
                ephemeral=True
            )

# 迷霧模式結束按鈕
class MistModeEndButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="結束迷霧模式", style=discord.ButtonStyle.red)
    async def end_mist_mode(self, interaction: Interaction, button: discord.ui.Button):
        """結束迷霧模式"""
        global mist_mode_enabled, mist_mode_channel_id
        
        # 檢查是否為管理員
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "[ERROR] 只有管理員可以結束迷霧模式",
                ephemeral=True
            )
            return
        
        mist_mode_enabled = False
        mist_mode_channel_id = None
        
        await interaction.response.send_message(
            "✅ 迷霧模式已結束！",
            ephemeral=True
        )
        print("[INFO] 迷霧模式已關閉")

@bot.tree.command(name="清除用戶數據", description="清除所有報名拍賣行的人員資料（管理員限定）")
async def clear_user_data(interaction: Interaction):
    """清除所有用戶的報名信息（管理員限定）"""
    try:
        # 檢查是否為管理員
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "[ERROR] 此指令僅限管理員使用",
                ephemeral=True
            )
            return

        # 先延遲回應，然後確認操作
        await interaction.response.defer(ephemeral=True)

        # 連接數據庫並清除所有用戶數據
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # 獲取現有用戶數量
        c.execute('SELECT COUNT(*) FROM users')
        user_count = c.fetchone()[0]

        # 清除所有用戶數據
        c.execute('DELETE FROM users')
        conn.commit()
        conn.close()

        # 發送確認訊息
        embed = discord.Embed(
            title="✅ 清除完成",
            description=f"已清除 {user_count} 個用戶的報名數據",
            color=discord.Color.green(),
            timestamp=datetime.now(TZ_TAIPEI)
        )
        embed.add_field(
            name="⚠️ 警告",
            value="此操作無法撤銷，所有用戶的報名信息已被永久刪除",
            inline=False
        )

        await interaction.followup.send(embed=embed, ephemeral=True)
        print(f"[INFO] 管理員 {interaction.user.name} 清除了所有用戶數據，共 {user_count} 個用戶")

    except Exception as e:
        print(f"[ERROR] 清除用戶數據失敗: {type(e).__name__}: {str(e)}")
        await interaction.followup.send(
            f"[ERROR] 清除失敗: {str(e)}",
            ephemeral=True
        )

@bot.tree.command(name="迷霧模式", description="開啟迷霧模式（管理員限定）")
async def mist_mode(interaction: Interaction):
    """開啟迷霧模式"""
    global mist_mode_enabled, mist_mode_channel_id
    
    # 檢查是否為管理員
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "[ERROR] 此指令僅限管理員使用",
            ephemeral=True
        )
        return
    
    mist_mode_enabled = True
    mist_mode_channel_id = interaction.channel_id
    
    # 發送開啟訊息和結束按鈕
    embed = discord.Embed(
        title="🌫️ 迷霧模式已開啟",
        description="開啟迷霧模式～所有訊息將在五秒內刪除！直到模式結束",
        color=discord.Color.purple(),
        timestamp=datetime.now(TZ_TAIPEI)
    )
    embed.add_field(
        name="⚙️ 說明",
        value="所有在此頻道發送的訊息將在5秒後自動刪除",
        inline=False
    )
    
    await interaction.response.send_message(
        embed=embed,
        view=MistModeEndButton()
    )
    
    print(f"[INFO] 迷霧模式已開啟，頻道 ID: {interaction.channel_id}")

@bot.event
async def on_message(message):
    """訊息事件處理"""
    # 忽略機器人自己的訊息
    if message.author.bot:
        return
    
    # 迷霧模式處理
    global mist_mode_enabled, mist_mode_channel_id
    
    if mist_mode_enabled and message.channel.id == mist_mode_channel_id:
        try:
            # 5秒後刪除訊息
            await message.delete(delay=5)
            print(f"[INFO] 迷霧模式：已排隊刪除訊息 from {message.author.name}")
        except discord.Forbidden:
            print(f"[ERROR] 迷霧模式：沒有權限刪除訊息")
        except Exception as e:
            print(f"[ERROR] 迷霧模式刪除訊息錯誤: {e}")

    # 繼續處理其他命令
    await bot.process_commands(message)

# 初始化數據庫
init_database()

# 運行機器人
import os
TOKEN = os.environ.get('DISCORD_TOKEN') or open('token.txt', 'r').read().strip()
bot.run(TOKEN)
