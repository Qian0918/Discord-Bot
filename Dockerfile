FROM python:3.11-slim

WORKDIR /app

# 安裝依賴
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 複製應用文件
COPY bot.py .

# 設置 UTF-8 編碼
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8

# 運行機器人
CMD ["python", "bot.py"]
