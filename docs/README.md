# *python程式碼說明*：

## *01_import_trec_all_csv_v5.py*：
這個程式是將Chris利用爬蟲抓下來的『直轉供憑證成交紀錄原始資料』
匯入到MySQL裡面，部分程式碼中出現函式(function)會呼叫utils_v5
裡面的函式來應用。
### 細部解釋

#### *需要`utils_v5`使用function*：
這是在說要使用`utils_v5`裡面的哪些function
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

#### *設定要到入資料庫的欄位名稱*：
因為爬蟲抓下來的欄位是中文我們要把中文欄位改成相應的英文欄位

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

#### *本檔案最重要的主函式`import_trec_all_raw()`*：
一開始用使用`utils_v5.py`裡面的`find_csv_file()`函式找到資料檔
如果找不到的話會直接
`print("找不到 trec_all_raw.csv，略過全部交易資料匯入。")`
然後直接結束程式

若有成功讀到檔案再來會使用`utils_v5.py`裡面的兩個function
`read_csv_with_fallback()`和`ormalize_columns()`

因為大家使用的電腦系統都不一樣，所以抓下來的檔案編碼可能也會不一樣
因此就要使用`read_csv_with_fallback()`讓原程式嘗試用裡面有指定的編碼來讀取檔案避免產生亂碼

`ormalize_columns()`是要將csv檔中的中文欄位名稱轉換成英文
再來就是要用`pymysql`套件功能撰寫SQL語法新增轉好欄位名稱的檔案到MySQL裡面
其中`VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)`是要讓資料能夠按照順訊丟進去上面所設定的欄位裡

再來我們要用`clean_empty()`這個function把原始資料中有「空字串、NaN、NULL、None、-、— 統一轉成 None」
因為我們綠電個別移轉量和綠電總移轉量的格式上會有MySQL不支援的格式，所以我們要使用這個function`clean_decimal()`把float形式的資料統一格式和去空值

例：總轉移量1,234.56MWh中有使用『,』區分千位數好讓資料在閱讀時變得容易，但對電腦來說他會以為這是兩筆資料而報錯，所以我們需要把『,』處理掉

然後其中有時間的型態我們也要透過這個function`clean_date`來把格式處理好

上面的資料都處理完丟進我們所建立的list後，我們就要使用`get_connection`function跟MySQL進行連線，然後把資料倒進去資料庫中對應的Table
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

## *02_import_trec_direct_csv_v5.py*：
這個程式是將`Chris`利用爬蟲抓下來的
『自用發電設備憑證成交紀錄原始資料』匯入MySQL裡面
部分程式碼中出現函式(function)一樣會呼叫`utils_v5`裡面的函式來應用，程式的細部解說可以參考`01_import_trec_all_csv_v5.py`裡


## *03_import_trec_certificate_csv_v5.py*：
這個程式是將`Gary`利用爬蟲抓下來的『全部已發放持有憑證資料』
再利用`Nick`所撰寫的python程式匯入MySQL根據前面兩個程式進行微調修改後
在執行匯入到MySQL裡面，修改過後的部分程式碼中出現函式(function)一樣會呼叫`utils_v5`裡面的函式來應用。
程式的細部說明一樣可以參考`01_import_trec_all_csv_v5.py`

## *04_build_normalized_tables_v5.py*：
這隻程式主要的目的是利用python中安裝的`pymysql`套件將資料正規化後倒入我們使用`01_create_database_and_tables_v5.sql`所建立的資料表中
其中使用到`pymysql`但沒有在前面`import`的原因
是因為我們import了`utils_v5`的連線功能來自`pymysql`

## *05_create_views_v5.py*：
這個程式就比較簡單好懂就是用python去執行`pymysql`把MySQL的裡的View資料表透過`02_create_views_v5`建立起來


## *06_check_database_v5.py*：
這個檔案是在檢查我們所建立的每一個Table、View中
所擁有的資料筆數確定我們的資料有成功出現在每個資料表裡面

## *07_dashboard_sankey_top10_v5.py*：
這個程式就是我們要使用的商業邏輯了
在專題當中我們要產出的功能有三
而這隻程式能根據我們建立資料庫裡面的View資料表產出Sankey圖表
其中`vw_sankey_data`裡有的資料欄位名稱分別為
『出售公司、購買公司、以及兩間公司之間的綠電交易總量』

## *08_check_raw_columns_v5.py*：
這隻程式的產生是因為當初透過`Gary`和`Chris`使用爬蟲所抓去下來的CSV測試，資料檔案名稱常常會有些許的不同容易跑錯匯入程式碼導致資料庫出現空值，後來發現三份資料的欄位數量是不一樣的，所以可以透過這隻程式知道每次測試資料的欄位數量，來決定開始用哪個匯入程式碼執行。

## *99_run_all_v5.py*：
這個程式的原理很簡單就是把它執行後他就會按照排定的順序依序執行整Python程式檔，當執行完畢時會在`print`出(全部流程執行完成)

## *utils_v5.py*:
裡面包含多個前面程式碼所需要一直重複使用的`function`

### *說明`import`內容中我們沒有見過的套件*
其中有一個套件`dotenv` 他是用來讀去`.env`檔中的設定值的
考量到之後可能會丟到雲端
所以下面介紹『原本得做法』以及『使用`dotenv`套件的做法』

#### *平常寫法*：
下面是我們在本地端執行時會直接寫
```
conn = pymysql.connect
(
    host="localhost", 
    user="root",
    password="12345678"
)
```
#### *使用`dotenv`的寫法*：
使用`dotenv`時我慢會直接讀取專案資料夾裡的`.env`檔案
而這裡直接把它寫成一個`function`，因為之後我們會平凡得連接到資料庫，到時候只要import`utils_v5`檔就能直接使用了
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

# *MySQL程式碼說明*

## *01_create_database_and_tables_v5.sql*：
這個SQL程式碼是建立三個存放爬蟲程式所抓下來的原始資料，每個英文欄位的說明以及對應到的中文欄位名都可以在另外一個說明檔
`data_dictionary_v5.md`裡面找到這邊就不多做說。


### *trec_all_raw*：
這個資料表示存放直轉供憑證成交紀錄的表格
`PK`的部分是設定資料庫自動產生的流水號
若有需要的話之後也可以使用`UUID`來當作`PK`

### *trec_direct_supply_raw*：
這個資料表是存放自用發電設備憑證成交紀錄的表格
`PK`的部分一樣是流水號
(接下來的PK只要是流水號都不在多加說明)

### *trec_certificate_raw*：
這個資料表是憑證持有與發放的表格
原本是由組員*NICK*所製作原始程式碼如下
```
CREATE TABLE `CompanyAPI7` (
  `id` char(36) NOT NULL COMMENT '流水號',
  `seller` varchar(100) DEFAULT NULL COMMENT '出售單位',
  `Facility` varchar(100) DEFAULT NULL COMMENT '發電設備',
  `energy_type` varchar(50) DEFAULT NULL COMMENT '能源類型',
  `vintage_year` varchar(10) DEFAULT NULL COMMENT '憑證發放年份',
  `transferred` decimal(12,3) DEFAULT NULL COMMENT '已移轉量(MWh)',
  `balance` decimal(12,3) DEFAULT NULL COMMENT '剩餘量(MWh)',
  `Location` text COMMENT '發電設備地址',
  `capacity` varchar(20) DEFAULT NULL COMMENT '裝置總容量',
  `co_owner` varchar(100) DEFAULT NULL COMMENT '發電設備共用單位',
  `Certificate_no` varchar(100) DEFAULT NULL COMMENT '證書編號',
  `TREC_Date` date DEFAULT NULL COMMENT 'T-REC最後憑證發放日期',
  `generation` varchar(30) DEFAULT NULL COMMENT '發電區間',
  `inspection_report` varchar(3) DEFAULT NULL COMMENT '再生能源設備查核報告',
  `verification_report` varchar(3) DEFAULT NULL COMMENT '再生能源發電量查證報告',
  `transferred_MWh` varchar(30) DEFAULT NULL COMMENT '詳情_已移轉量',
  `Available_MWh` varchar(30) DEFAULT NULL COMMENT '詳情_剩餘量'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```
因為是測試所以資料表取名的部分一開始比較隨意
後面就再重新命名以憑證的英文(Certificate)為基礎

### *company_alias*：
(這個表格之後會刪掉)
他原本的作用是為了確定出售綠電的眾多公司中有沒有子公司，之後會考慮把它刪除

### *company*：
這是把所有不管是出售、購買、還有持有憑證三個原始資料裡面的每一間公司
都會透過正規化處理 新增到這個資料表裡面
那因為PK已經被設定為流水號的部分了
若我想要在讓公司名稱一定要是唯一值得話，我就必須設定 *`UK`約束它*
所以在程式碼裡面會看到
`UNIQUE KEY uk_company_name (company_name)`
這段程式碼

### *facility*：
這個資料表就是存放三個原始資料表所正規化出來的發電設備名稱
(可能是公司名稱、地號、學校、各種住宅名稱)
這裡一樣有設定UK讓發電設備具有唯一性
(後面若出現需要設置`UK`的部分，沒有特別原因不會再多做說明)

### *energy_type*：
這個表示存放綠電來源是屬於哪一種能源
例如：太陽能、風能.....等等
雖然此表所擁有的資料數量不多，但以防後面再進行商業邏輯的時候需要此表所以還是把它建置起來

### *supply_type*：
因為在綠電交易網上我們有看到轉供和直供，因此也建立一個供電類型的表格
來放之後出現各種類型的供電方式

### *transaction_fact*：
接下來這個表就是比較重要的表格了，因為我們所要探討的就是所有綠電交易的各種數值統整，以利後面的商業邏輯分析。
transaction_fact 為綠電交易事實表（Fact Table），透過外鍵（Foreign Key）分別連結 company、facility、energy_type 與 supply_type 等資料表（Dimension Table）。

此設計可確保：

* 維持資料一致性（Data Integrity）
* 避免重複儲存相同資料
* 降低資料更新成本
* 提升查詢效率
* 符合資料倉儲 Star Schema 設計原則
*下方的程式碼就是用來跟程式說各項欄位所對應到其他資料表(FK)的欄位*
```
    CONSTRAINT fk_tf_seller_company FOREIGN KEY (seller_company_id) REFERENCES company(company_id),
    CONSTRAINT fk_tf_buyer_company FOREIGN KEY (buyer_company_id) REFERENCES company(company_id),
    CONSTRAINT fk_tf_facility FOREIGN KEY (facility_id) REFERENCES facility(facility_id),
    CONSTRAINT fk_tf_energy_type FOREIGN KEY (energy_type_id) REFERENCES energy_type(energy_type_id),
    CONSTRAINT fk_tf_supply_type FOREIGN KEY (supply_type_id) REFERENCES supply_type(supply_type_id)
```

### *certificate_fact*：
這個表跟上面的*transaction_fact*表格其實就是同樣的概念，就不多做解釋

## *02_create_views_v5.sql*：
這裡所建置的表格就是之後要進行商業邏輯所需要的虛擬資料表
目前我們唯一有用到的只有`vw_sankey_data`這個表格，之後若有需要可以再依需求建立新的View資料表或是現有的資料表
然後每一個表上面都有加上註解說明View表示要幹嘛用的！！！
*(當然也有不知道建出來要幹嘛的存在請自己仔細閱讀註解)*
*～啾咪~＾.<*