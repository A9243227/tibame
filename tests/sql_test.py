import pymysql
import pandas as pd
import uuid

# ==========================================
# 1. 讀取並清洗/重新命名 CSV 資料
# ==========================================

# 讀取指定路徑的 CSV 檔案，並設定編碼為 utf-8 以防中文亂碼
df = pd.read_csv(
    "test.csv",
    encoding="utf-8"
)

# 將原本 CSV 的中文欄位名稱（Headers）重新命名為對應的資料庫欄位名稱（英文）
df = df.rename(columns={
    '出售單位': 'seller',
    '發電設備': 'Facility',
    '能源類型': 'energy_type',
    '憑證發放年份': 'vintage_year',
    '已移轉量(MWh)': 'transferred',
    '剩餘量(MWh)': 'balance',
    '發電設備地址': 'Location',
    '裝置總容量': 'capacity',
    '發電設備共用單位': 'co_owner',
    '證書編號': 'Certificate_no',
    'T-REC最後憑證發放日期': 'TREC_Date',
    '發電區間': 'generation',
    '再生能源設備查核報告': 'inspection_report',
    '再生能源發電量查證報告': 'verification_report',
    '詳情_已移轉量': 'transferred_MWh',
    '詳情_剩餘量': 'Available_MWh'
})


# ==========================================
# 2. 設定資料庫連線
# ==========================================

# 建立 MySQL/MariaDB 資料庫連線
conn = pymysql.connect(
    host='localhost',          # 資料庫伺服器位址
    port=3306,                 # 預設 MySQL 通訊埠
    user='root',               # 資料庫帳號
    passwd='password',         # 資料庫密碼
    db='Companydata',          # 指定要使用的資料庫名稱
    charset='utf8mb4'          # 使用 utf8mb4 完整支援中文、特殊字元與地號符號
)

# 建立游標物件（Cursor），用來執行 SQL 指令
cursor = conn.cursor()


# ==========================================
# 3. 定義 SQL 新增（INSERT）指令
# ==========================================

# 採用預備語法（Prepared Statement），使用 %s 當作變數佔位符，防止 SQL 注入攻擊
sql = """
INSERT INTO CompanyAPI3 (
    id,
    seller,
    Facility,
    energy_type,
    vintage_year,
    transferred,
    balance,
    Location,
    capacity,
    co_owner,
    Certificate_no,
    TREC_Date,
    generation,
    inspection_report,
    verification_report,
    transferred_MWh,
    Available_MWh
)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
"""


# ==========================================
# 4. 迴圈讀取資料並逐行寫入資料庫
# ==========================================

# 使用 iterrows() 逐行遍歷 DataFrame 
# `_` 代表我們忽略 Pandas 自動產生的行索引（Index），只關注資料列本身（row）
for _, row in df.iterrows():
    
    # 執行 SQL 語法，依序填入與上面 SQL 欄位對應的變數值
    cursor.execute(sql, (
        # 產生唯一識別碼 UUID (版本4)，轉為 36 字元字串作為該筆資料的主鍵 (Primary Key)
        str(uuid.uuid4()),

        row['seller'],               # 出售單位
        row['Facility'],             # 發電設備名稱
        row['energy_type'],          # 能源類型 (如：風力能、太陽光電)
        row['vintage_year'],         # 憑證發放年份
        row['transferred'],          # 已移轉量 (MWh) - 數值型態
        row['balance'],              # 剩餘量 (MWh) - 數值型態
        row['Location'],             # 發電設備地址 (含詳細地號字串)
        row['capacity'],             # 裝置總容量 (帶有單位文字，如 kW)
        row['co_owner'],             # 發電設備共用單位
        row['Certificate_no'],       # 證書編號區間
        row['TREC_Date'],            # T-REC 最後憑證發放日期
        row['generation'],           # 發電區間 (日期區間字串)
        row['inspection_report'],    # 再生能源設備查核報告狀態 (如：認可)
        row['verification_report'],  # 再生能源發電量查證報告狀態 (如：認可)
        row['transferred_MWh'],      # 詳情_已移轉量 (含單位文字，如 MWh)
        row['Available_MWh']         # 詳情_剩餘量 (含單位文字，如 MWh)
    ))


# ==========================================
# 5. 提交變更並關閉連線
# ==========================================

# 必須手動提交（Commit），才會真正將剛剛 execute 的資料寫入、保存到資料庫中
conn.commit()

# 關閉游標，釋放資料庫記憶體資源
cursor.close() 

# 關閉與資料庫的連線
conn.close()

# 程式執行完成提示
print('上傳成功')