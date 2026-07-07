# 1. 選擇基底環境：使用與目前環境專案要求的 Python 3.13 輕量版 (亦可視需求改為 3.10-slim)
FROM python:3.13-slim

# 2. 設定容器內的工作目錄
WORKDIR /app

# 3. 安裝系統必備套件與瀏覽器
# 這是最重要的步驟：安裝 Chromium 瀏覽器與對應的驅動程式 (Chromium Driver)
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# 4. 複製套件清單並安裝 Python 依賴
# 請確保你的專案根目錄有 requirements.txt (裡面要有 selenium 等套件)
COPY crawler.requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 新增：安裝 Playwright 瀏覽器及其系統依賴
RUN playwright install --with-deps chromium

# 5. 將你所有的程式碼複製到容器內
COPY . .

# 6. 設定 Python 路徑，讓任意層級的腳本都能找得到模組
ENV PYTHONPATH="/app/src:${PYTHONPATH}"

# 7. 設定啟動指令
# 不寫死單一腳本，讓 Airflow / Cloud Run 可以在建立 Job 時自由覆寫指令
CMD ["echo", "Please specify the crawler python script to run."]
