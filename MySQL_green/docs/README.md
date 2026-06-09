# python程式碼說明：

## `01_import_trec_all_csv_v5.py`：
這個程式是將Chris利用爬蟲抓下來的『直轉供憑證成交紀錄原始資料』
匯入到MySQL裡面，部分程式碼中出現函式(function)會呼叫utils_v5
裡面的函式來應用。
### 細部解釋

#### 需要`utils_v5`使用function：
*這是在說要使用`utils_v5`裡面的哪些function*
```
from utils_v5 import (
    clean_date,
    clean_decimal,
    clean_empty,
    find_csv_file,
    get_connection,
    normalize_columns,
    read_csv_with_fallback,
)
```

#### 設定要到入資料庫的欄位名稱：
*因為爬蟲抓下來的欄位是中文我們要把中文欄位改成相應的英文欄位*
```
COLUMN_MAPPING = {
    "出售單位": "seller",
    "發電設備": "facility_name",
    "購買者": "buyer",
    "能源類型": "energy_type",
    "供電種類": "supply_type",
    "總移轉量(MWh)": "total_transfer_mwh",
    "成交日期": "transaction_date",
    "成交移轉量(MWh)": "transaction_transfer_mwh",
    "成交記錄原文": "transaction_detail_raw",
}
```

#### 本檔案最重要的主函式`import_trec_all_raw()`：
*一開始用使用utils_v5.py裡面的`find_csv_file()`函式找到資料檔*
*如果找不到的話會直接*
*print("找不到 trec_all_raw.csv，略過全部交易資料匯入。")*
*然後直接結束程式*

*若有成功讀到檔案再來會使用`utils_v5.py`裡面的兩個function*
*`read_csv_with_fallback()`和`ormalize_columns()`*

*因為大家使用的電腦系統都不一樣，所以抓下來的檔案編碼可能也會不一樣*
*因此就要使用`read_csv_with_fallback()`讓原程式嘗試用裡面有指定的編碼來讀取檔案避免產生亂碼*

*`ormalize_columns()`是要將csv檔中的中文欄位名稱轉換成英文*
*再來就是要用`pymysql`套件功能撰寫SQL語法新增轉好欄位名稱的檔案到MySQL裡面*
*其中`VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)`是要讓資料能夠按照順訊丟進去上面所設定的欄位裡*

*再來我們要用`clean_empty()`這個function把原始資料中有「空字串、NaN、NULL、None、-、— 統一轉成 None」*
*因為我們綠電個別移轉量和綠電總移轉量的格式上會有MySQL不支援的格式，所以我們要使用這個function`clean_decimal()`把float形式的資料統一格式和去空值*

*例：總轉移量1,234.56MWh中有使用『,』區分千位數好讓資料在閱讀時變得容易，但對電腦來說他會以為這是兩筆資料而報錯，所以我們需要把『,』處理掉*

*然後其中有時間的型態我們也要透過這個function`clean_date`來把格式處理好*

*上面的資料都處理完丟進我們所建立的list後，我們就要使用`get_connection`function跟MySQL進行連線，然後把資料倒進去資料庫中對應的Table*
```
def import_trec_all_raw():
    """
    讀取全部交易 CSV，完整保留 9 個原始欄位並寫入 MySQL。
    """
    file_path = find_csv_file(["trec_all_raw.csv", "trec_all.csv", "all_raw.csv"])

    if file_path is None:
        print("找不到 trec_all_raw.csv，略過全部交易資料匯入。")
        return

    df = read_csv_with_fallback(file_path)
    df = normalize_columns(df, COLUMN_MAPPING)

    insert_sql = """
        INSERT INTO trec_all_raw (
            seller,
            facility_name,
            buyer,
            energy_type,
            supply_type,
            total_transfer_mwh,
            transaction_date,
            transaction_transfer_mwh,
            transaction_detail_raw
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    rows = []

    for _, row in df.iterrows():
        rows.append((
            clean_empty(row.get("seller")),
            clean_empty(row.get("facility_name")),
            clean_empty(row.get("buyer")),
            clean_empty(row.get("energy_type")),
            clean_empty(row.get("supply_type")),
            clean_decimal(row.get("total_transfer_mwh")),
            clean_date(row.get("transaction_date")),
            clean_decimal(row.get("transaction_transfer_mwh")),
            clean_empty(row.get("transaction_detail_raw")),
        ))

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("TRUNCATE TABLE trec_all_raw")
        cursor.executemany(insert_sql, rows)
        conn.commit()
        print(f"trec_all_raw 匯入完成：{len(rows)} 筆，欄位數：9 欄")

    except Exception as exc:
        conn.rollback()
        print("trec_all_raw 匯入失敗")
        raise exc

    finally:
        cursor.close()
        conn.close()
```

## `02_import_trec_direct_csv_v5.py`：
*這個程式是將`Chris`利用爬蟲抓下來的*
*『自用發電設備憑證成交紀錄原始資料』匯入MySQL裡面*
*部分程式碼中出現函式(function)一樣會呼叫utils_v5裡面的函式來應用，程式的細部解說可以參考`01_import_trec_all_csv_v5.py`裡*


## `03_import_trec_certificate_csv_v5.py`：
*這個程式是將`Gary`利用爬蟲抓下來的『全部已發放持有憑證資料』*
*再利用`Nick`所撰寫的python程式匯入MySQL根據前面兩個程式進行微調修改後*
*在執行匯入到MySQL裡面，修改過後的部分程式碼中出現函式(function)一樣會呼叫`utils_v5`裡面的函式來應用。*
*程式的細部說明一樣可以參考`01_import_trec_all_csv_v5.py`*

## `04_build_normalized_tables_v5.py`：
*這隻程式主要的目的是利用python中安裝的`pymysql`套件將資料正規化後倒入我們使用`01_create_database_and_tables_v5.sql`所建立的資料表中*
*其中使用到`pymysql`但沒有在前面import的原因*
*是因為我們import了`utils_v5`的連線功能來自`pymysql`*

## `05_create_views_v5.py`：
*這個程式就比較簡單好懂就是用python去執行`pymysql`把MySQL的裡的View資料表透過`02_create_views_v5`建立起來*


## `06_check_database_v5.py`：
*這個檔案是在檢查我們所建立的每一個Table、View中*
*所擁有的資料筆數確定我們的資料有成功出現在每個資料表裡面*

## `07_dashboard_sankey_top10_v5.py`：
*這個程式就是我們要使用的商業邏輯了*
*在專題當中我們要產出的功能有三*
*而這隻程式能根據我們建立資料庫裡面的資料t產出Sankey圖表*
*其中`vw_sankey_data`裡有的資料欄位名稱分別為*
*『出售公司、購買公司、以及兩間公司之間的綠電交易總量』*

## `08_check_raw_columns_v5.py`：
*這隻程式的產生是因為當初透過`Gary`和`Chris`使用爬蟲所抓去下來的CSV測試資料檔案名稱常常會有些許的不同容易跑錯匯入程式碼導致資料庫出現空值，後來發現三份資料的欄位數量是不一樣的，所以可以透過這隻程式知道每次測試資料的欄位數量，來決定開始用哪個匯入程式碼執行*

## `99_run_all_v5.py`：
*這個程式的原理很簡單就是把它執行後他就會按照排定的順序依序執行整Python程式檔，當執行完畢時會在`print`出(全部流程執行完成)*

## `utils_v5.py`:
*裡面包含多個前面程式碼所需要一直重複使用的function*

### 先說明import內容中我們沒有見過的套件
*其中有一個套件`dotenv` 他是用來讀去`.env`檔中的設定值的*
*考量到之後可能會丟到雲端*
*所以下面介紹『原本得做法』以及『使用`dotenv`套件的做法』*

#### 平常寫法
*下面是我們在本地端執行時會直接寫*
```
conn = pymysql.connect
(
    host="localhost", 
    user="root",
    password="12345678"
)
```
#### 使用`dotenv`的寫法
*使用`dotenv`時我慢會直接讀取專案資料夾裡的`.env`檔案*
*而這裡直接把它寫成一個function，因為之後我們會平凡得連接到資料庫，到時候只要import`utils_v5`檔就能直接使用了*
```
def load_db_config():
    """
    讀取 .env 檔中的 MySQL 連線設定。
    """
    load_dotenv(BASE_DIR / ".env")

    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASSWORD", "password"),
        "database": os.getenv("DB_NAME", "專案資料夾名稱"),
        "charset": "utf8mb4",
        "autocommit": False,
    }
```

# MySQL程式碼說明