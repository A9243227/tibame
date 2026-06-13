import pandas as pd
import uuid
import pymysql
import os
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

# =========================
# 讀取 CSV 檔案
# =========================
# encoding="utf-8" 表示使用 UTF-8 編碼讀取
csv_path = os.path.join("data", "trec_direct_supply_mysql.csv")
# 若檔案不存在請自行確認路徑
df = pd.read_csv(
    csv_path,
    encoding="utf-8"
)

# =========================
# 建立 MySQL 連線
# =========================
conn = pymysql.connect(
    host=os.getenv("DB_HOST", "localhost"),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASSWORD", "your_password"),
    database=os.getenv("DB_NAME", "Tibame_G1"),
    charset="utf8mb4"
)

# 建立 Cursor 物件
cursor = conn.cursor()

# =========================
# SQL 新增語法
# =========================
sql = """
INSERT INTO direct_supply (
    id,
    seller,
    power_facility,
    buyer,
    energy_type,
    supply_type,
    total_transfer_mwh,
    transaction_date,
    transaction_transfer_mwh,
    transaction_record
)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
"""

# =========================
# 將 CSV 資料逐筆寫入 MySQL
# =========================
for _, row in df.iterrows():

    # 去除數字中的千分位逗號
    # 例如：
    # 11,764.257 → 11764.257
    total_transfer_mwh = str(
        row["total_transfer_mwh"]
    ).replace(",", "")

    transaction_transfer_mwh = str(
        row["transaction_transfer_mwh"]
    ).replace(",", "")

    # 執行 INSERT
    cursor.execute(sql, (
        # 產生 UUID 作為主鍵
        str(uuid.uuid4()),

        # 出售單位
        row["seller"],

        # 發電設備
        row["power_facility"],

        # 購買者
        row["buyer"],

        # 能源類型
        row["energy_type"],

        # 供電種類
        row["supply_type"],

        # 總移轉量(MWh)
        total_transfer_mwh,

        # 成交日期
        row["transaction_date"],

        # 成交移轉量(MWh)
        transaction_transfer_mwh,

        # 成交記錄原文
        row["transaction_record"]
    ))

# =========================
# 儲存變更到資料庫
# =========================
conn.commit()

# ==========================
# 關閉 Cursor 與連線
# =========================
cursor.close()
conn.close()

print("匯入完成")