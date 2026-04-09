# Discord 拍賣行機器人

台灣時間排序機制的 Discord 自動化報名機器人。

## 功能

- **填寫報名表單**: 使用者可填寫遊戲名稱、收裝備天數(1-3天)、最高天命花費(最少50)
- **報名限制**: 每位使用者只能報名一次，須等待前一個報名結束才能重新報名
- **優先級系統**: 從 `id.xlsx` 讀取優先級使用者名單，優先級使用者排在前面
- **自動排序**: 根據提交順序和優先級自動計算開始和結束日期
- **定時提醒**: 自動發送多個定時提醒訊息（每週不同時間）
- **每日公告**: 晚上22:00自動公佈該日報名名單
- **查詢功能**: 支援查詢報名人數和個人報名信息
- **彩蛋功能**: 提到「牢大」會觸發特殊回應

## 部署指南

### 前置需求
- Python 3.8+
- Discord Bot Token（[申請方式](https://discord.com/developers/applications)）

### 本地運行

1. **安裝依賴**
   ```bash
   pip install -r requirements.txt
   ```

2. **設置 Token**
   在項目根目錄建立 `token.txt` 文件，內容為你的 Discord Bot Token

3. **運行機器人**
   ```bash
   python bot.py
   ```

### 在 Railway 上部署

1. **Fork 此倉庫**到你的 GitHub 帳號

2. **前往 [Railway](https://railway.app/)**
   - 選擇「Deploy from GitHub repo」
   - 授權並選擇此倉庫

3. **配置環境變量**
   - 在 Railway 中設置環境變量 `DISCORD_TOKEN`
   - 設置值為你的 Discord Bot Token

4. **自動部署**
   Railway 會自動運行並保持機器人在線

## 命令

- `/填寫拍賣行表單` - 打開報名表單（需要指定身份組）
- `/查詢報名人數` - 查詢所有使用者報名信息（管理員限定）
- `/查詢我的信息` - 查詢你自己填寫的信息

## 配置

在 `bot.py` 中編輯以下設置：
- `REQUIRED_ROLE_ID` - 填寫表單所需的身份組 ID
- `ANNOUNCEMENT_CHANNEL_ID` - 發送公告的頻道 ID
- `REMINDER_CHANNEL_ID` - 發送提醒的頻道 ID
- `PRIORITY_USERNAMES` - 從 `id.xlsx` 讀取的優先級使用者名單

## 資料庫

使用 SQLite 存儲使用者信息，包含以下字段：
- `user_id` - Discord 使用者 ID
- `username` - Discord 使用者名稱
- `game_name` - 遊戲名稱
- `equip_days` - 收裝備天數
- `max_fate_cost` - 最高天命花費
- `is_priority` - 是否為優先級使用者
- `created_at` - 報名時間

## 許可證

MIT License
