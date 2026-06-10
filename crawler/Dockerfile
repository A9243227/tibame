# 使用輕量級的 Python 3.10
FROM python:3.10-slim

# 安裝系統層級的 Chrome 瀏覽器與驅動程式
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 複製並安裝 Python 套件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製你的爬蟲主程式
COPY Applied_REC_cloudrun.py .

# 執行指令
CMD ["python", "Applied_REC_cloudrun.py"]