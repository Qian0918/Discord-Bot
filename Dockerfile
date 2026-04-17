FROM python:3.11-slim

WORKDIR /app

# 安裝依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用文件
COPY bot.py .
COPY token.txt .
COPY groq_key.txt .

# 運行機器人
CMD ["python", "bot.py"]
