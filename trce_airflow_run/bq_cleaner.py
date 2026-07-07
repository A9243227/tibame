import io
from google.cloud import bigquery

class BigQueryETLPipeline:
    import io
from google.cloud import bigquery

class BigQueryETLPipeline:
    def __init__(self, project_id: str ="tibametopics", dataset_id: str = "trec_data"):
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.client = bigquery.Client(project=project_id) # 建立 BigQuery 連線用戶端

    def _execute_query(self, sql_query: str, task_name: str):
        """
        【核心私有方法】負責送出 SQL 指令至 BigQuery 並處理異常錯誤（內建 JobConfig 鎖定彰化機房）。
        
        Args:
          sql_query (str): 要執行的標準 SQL 語法串
          task_name (str): 任務名稱（主要用於 Log 日誌輸出與排錯辨識）
        """
        try:
            print(f"\n🚀 [{task_name}] 正在透過 SQL 執行 BigQuery 運算...")
            
            # 💡 強制使用 QueryJobConfig 鎖定台灣彰化機房，避免雲端多機房運算時產生 Location mismatch 錯誤
            job_config = bigquery.QueryJobConfig()
            
            # 非同步送出查詢 Job
            query_job = self.client.query(sql_query, job_config=job_config)
            query_job.result()  # 阻塞並等待 BigQuery 內部運算完全結束
            print(f"🎉 [{task_name}] 執行成功！")
            
        except Exception as e:
            # 輸出錯誤日誌，方便在 Airflow Task Log 中一目了然
            print(f"❌ [{task_name}] 執行失敗，錯誤訊息：\n{e}")
            raise e  # 必須主動拋出異常(raise)，Airflow 才能精準捕捉到 Task 失敗並觸發重試或警報

    def _gen_clean_str_field(self, field_name: str, header_name: str) -> str:
        """
        【SQL Helper】自動生成通用字串清洗的 CASE WHEN 語法。
         功能包括：清除換行、特殊符號、去前後空白、全形括號轉半形、將欄位標頭字串或 'None/NaN' 轉為標準 NULL。
        
        Args:
          field_name (str): 欄位名稱
          header_name (str): 該欄位在原始 CSV 檔案中的中文字頭（用於過濾重複的 Header）
        """
        return f"""
        CASE 
          -- 1. 判斷若欄位是空值、字串 nan/None 或是原始 CSV 的標頭字串，則統一轉為標準 SQL NULL
          WHEN TRIM({field_name}) IN ('', 'nan', 'NaN', 'None', '{header_name}') THEN NULL 
          -- 2. 清除字串前後空白 -> 使用正則表達式 REGEXP_REPLACE 拔除 \\n 與 \\r 換行符號 -> 統一將全形（）轉換為半形 ()
          ELSE REPLACE(REPLACE(TRIM(REGEXP_REPLACE(CAST({field_name} AS STRING), r'[\\n\\r]', '')), '（', '('), '）', ')')
        END AS {field_name}"""

    def _gen_clean_decimal_field(self, field_name: str) -> str:
        """
        【SQL Helper】自動生成數值欄位安全轉換語法。
         功能包括：轉字串防呆、移除千分位逗號（,）、使用 SAFE_CAST 轉型成 NUMERIC（失敗會自動回傳 NULL），最後以 COALESCE 將空值填補為 0.0。
        
        Args:
          field_name (str): 欲處理的數值欄位名稱
        """
        return f"COALESCE(SAFE_CAST(REPLACE(CAST({field_name} AS STRING), ',', '') AS NUMERIC), 0.0) AS {field_name}"

    # =========================================================================
    #  第一正規化 (1NF) - Clean 表建立階段
    # =========================================================================

    def clean_self_generation_transaction(self):
        """
        執行自發自用交易表（trec_self_generation_transaction）的 1NF 資料清洗。
        主要排除標頭檔並產出乾淨型態的 clean 表。
        """
        # 定義原始表與目標乾淨表的完整路徑
        raw_table = f"`{self.project_id}.{self.dataset_id}.trec_self_generation_transaction_raw`"
        clean_table = f"`{self.project_id}.{self.dataset_id}.trec_self_generation_transaction_clean`"
        
        # 呼叫 Helper 生成各個字串欄位的清洗 SQL 片段
        seller_sql = self._gen_clean_str_field('seller', '出售單位')
        facility_sql = self._gen_clean_str_field('facility_name', '發電設備')
        buyer_sql = self._gen_clean_str_field('buyer', '購買者')
        energy_sql = self._gen_clean_str_field('energy_type', '能源類型')

        sql_query = f"""
    CREATE OR REPLACE TABLE {clean_table} (
      self_clean_id INT64 OPTIONS(description='自用發電清理資料流水號'),
      seller STRING OPTIONS(description='出售單位'),
      facility_name STRING OPTIONS(description='發電設備名稱'),
      buyer STRING OPTIONS(description='購買者名稱'),
      energy_type STRING OPTIONS(description='能源類型'),
      transfer_mwh NUMERIC OPTIONS(description='轉移量(MWh)'),
      certificate_year INT64 OPTIONS(description='憑證發放年份'),
      transfer_date DATE OPTIONS(description='轉移日期'),
      created_at TIMESTAMP OPTIONS(description='資料建立時間')
    ) AS
    SELECT
      ROW_NUMBER() OVER() AS self_clean_id, -- 1. 生成清洗層唯一的流水號
      {seller_sql},                        -- 2. 洗淨後的出售單位
      {facility_sql},                      -- 3. 洗淨後的發電設備名稱
      {buyer_sql},                         -- 4. 洗淨後的購買者
      {energy_sql},                        -- 5. 洗淨後的能源類型
      COALESCE(SAFE_CAST(transfer_mwh AS NUMERIC), 0.0) AS transfer_mwh, -- 6. 轉型分配電量為數字，空值補 0
      SAFE_CAST(certificate_year AS INT64) AS certificate_year,          -- 7. 轉型憑證年份為整數
      SAFE_CAST(transfer_date AS DATE) AS transfer_date,                 -- 8. 轉型轉讓日期為標準 DATE 格式
      CURRENT_TIMESTAMP() AS created_at                                  -- 9. 紀錄清洗時間戳記
    FROM {raw_table}
    WHERE seller != '出售單位'; -- 過濾掉網頁爬蟲或多檔合併時重複夾帶的 CSV 標頭行
    """
        self._execute_query(sql_query, task_name="1NF_Self_Generation")

    def clean_direct_transaction(self):
        """
        執行直轉供交易表（trec_direct_transaction）的 1NF 資料清洗。
        包含處理字串去噪、千分位逗號移除、以及標準型態變更。
        """
        # 定義原始表與目標乾淨表的完整路徑
        raw_table = f"`{self.project_id}.{self.dataset_id}.trec_direct_transaction_raw`"
        clean_table = f"`{self.project_id}.{self.dataset_id}.trec_direct_transaction_clean`"
        
        # 呼叫 Helper 生成字串與數值欄位的清洗 SQL
        seller_sql = self._gen_clean_str_field('seller', '出售單位')
        facility_sql = self._gen_clean_str_field('facility_name', '發電設備')
        buyer_sql = self._gen_clean_str_field('buyer', '購買者')
        energy_sql = self._gen_clean_str_field('energy_type', '能源類型')
        supply_sql = self._gen_clean_str_field('supply_type', '供電種類')

        total_mwh_sql = self._gen_clean_decimal_field('total_transfer_mwh')
        tx_mwh_sql = self._gen_clean_decimal_field('transaction_transfer_mwh')

        sql_query = f"""
        CREATE OR REPLACE TABLE {clean_table} (
          direct_clean_id INT64 OPTIONS(description='直轉供清理資料流水號'),
          seller STRING OPTIONS(description='出售單位'),
          facility_name STRING OPTIONS(description='發電設備'),
          buyer STRING OPTIONS(description='購買者'),
          energy_type STRING OPTIONS(description='能源類型'),
          supply_type STRING OPTIONS(description='供電種類'),
          total_transfer_mwh NUMERIC OPTIONS(description='總轉移(MWh)'),
          transaction_date DATE OPTIONS(description='成交日期'),
          transaction_transfer_mwh NUMERIC OPTIONS(description='成交轉移量(MWh)'),
          created_at TIMESTAMP OPTIONS(description='資料建立時間')
          ) AS
          SELECT
          ROW_NUMBER() OVER() AS direct_clean_id, -- 1. 生成清洗層唯一主鍵
          {seller_sql},                           -- 2. 洗淨後的出售單位 (對應 seller)
          {facility_sql},                         -- 3. 洗淨後的設備名稱 (對應 facility_name)
          {buyer_sql},                            -- 4. 洗淨後的購買者 (對應 buyer)
          {energy_sql},                           -- 5. 洗淨後的能源類型 (對應 energy_type)
          {supply_sql},                           -- 6. 洗淨後的供電種類 (對應 supply_type)
          {total_mwh_sql},                        -- 7. 清除千分位後的總分配電量 (對應 total_transfer_mwh)
          SAFE_CAST(transaction_date AS DATE) AS transaction_date, -- 8. 轉型交易日期為 DATE
          {tx_mwh_sql},                           -- 9. 清除千分位後的單筆交易電量 (對應 transaction_transfer_mwh)
          CURRENT_TIMESTAMP() AS created_at       -- 10. 紀錄清洗時間戳記
          FROM {raw_table}
          WHERE seller != '出售單位'; -- 排除重複的 CSV 標頭行
          """
        self._execute_query(sql_query, task_name="1NF_Direct_Transaction")

    def clean_issued_certificate(self):
        """
        執行已核發憑證表（trec_issued_certificate）的 1NF 資料清洗與 UNNEST 共用單位炸開。
        包含：切割發電期間字串、將一欄多單位的「共用單位」欄位利用正則與 UNNEST 炸開成一對多獨立列。
        """
        # 定義原始表與目標乾淨表的完整路徑
        raw_table = f"`{self.project_id}.{self.dataset_id}.trec_issued_certificate_raw`"
        clean_table = f"`{self.project_id}.{self.dataset_id}.trec_issued_certificate_clean`"

        # 生成字串欄位基礎清洗語法
        unit_sql = self._gen_clean_str_field('unit_name', '出售單位')
        facility_sql = self._gen_clean_str_field('facility_name', '發電設備')
        energy_sql = self._gen_clean_str_field('energy_type', '能源類型')
        address_sql = self._gen_clean_str_field('facility_address', '發電設備地址')
        cert_num_sql = self._gen_clean_str_field('certificate_number', '證書編號')
        audit_sql = self._gen_clean_str_field('equipment_audit_report', '再生能源設備查核報告')
        verify_sql = self._gen_clean_str_field('power_generation_verification_report', '再生能源發電量查證報告')
        shared_comp_sql = self._gen_clean_str_field('shared_company', '發電設備共用單位')

        sql_query = f"""
        CREATE OR REPLACE TABLE {clean_table} (
        cert_clean_id INT64 OPTIONS(description='已發放憑證清理資料流水號'),
        unit_name STRING OPTIONS(description='單位名稱'),
        facility_name STRING OPTIONS(description='發電設備'),
        energy_type STRING OPTIONS(description='能源類型'),
        facility_address STRING OPTIONS(description='發電設備地址'),
        installed_capacity BIGNUMERIC OPTIONS(description='裝置總容量'),
        shared_company STRING OPTIONS(description='發電設備共用單位'),
        certificate_number STRING OPTIONS(description='證書編號'),
        trec_last_issue_date DATE OPTIONS(description='T-REC最後憑證發放日期'),
        generation_start_date DATE OPTIONS(description='發電期間開始日期'),
        generation_end_date DATE OPTIONS(description='發電期間結束日期'),
        equipment_audit_report STRING OPTIONS(description='再生能源設備查核報告'),
        power_generation_verification_report STRING OPTIONS(description='再生能源發電量查證報告'),
        transferred_mwh BIGNUMERIC OPTIONS(description='已移轉電量'),
        remaining_mwh BIGNUMERIC OPTIONS(description='剩餘量'),
        created_at TIMESTAMP OPTIONS(description='資料建立時間')
      ) AS
      WITH cleaned_base AS (
        SELECT
          {unit_sql},
          {facility_sql},
          {energy_sql},
          {address_sql},
          -- 轉型裝置容量：先強制大寫、拔除 'KW' 單位、拿掉逗號，最後安全轉換為 DECIMAL (BigQuery 的 DECIMAL 即 BIGNUMERIC/NUMERIC)
          SAFE_CAST(REPLACE(REGEXP_REPLACE(UPPER(installed_capacity), 'KW', ''), ',', '') AS DECIMAL) AS installed_capacity,
          -- 共用欄位清洗後，先起個暫時名稱準備待會切分
          {shared_comp_sql.replace('AS shared_company', 'AS raw_shared_company')},
          {cert_num_sql},
          SAFE_CAST(trec_last_issue_date AS DATE) AS trec_last_issue_date,
          -- 處理發電期間字串 (例如 "2025/01/01~2025/01/31")：利用 SPLIT 拆開並取陣列的前後段分別轉成 DATE
          SAFE_CAST(CASE WHEN INSTR(generation_period, '~') > 0 THEN TRIM(SPLIT(generation_period, '~')[OFFSET(0)]) ELSE TRIM(generation_period) END AS DATE) AS generation_start_date,
          SAFE_CAST(CASE WHEN INSTR(generation_period, '~') > 0 THEN TRIM(SPLIT(generation_period, '~')[OFFSET(1)]) ELSE TRIM(generation_period) END AS DATE) AS generation_end_date,
          {audit_sql},
          {verify_sql},
          -- 清除 MWH 單位、處理千分位、轉型為計量電量
          COALESCE(SAFE_CAST(REPLACE(REGEXP_REPLACE(UPPER(transferred_mwh), 'MWH', ''), ',', '') AS DECIMAL), 0.0) AS transferred_mwh,
          COALESCE(SAFE_CAST(REPLACE(REGEXP_REPLACE(UPPER(remaining_mwh), 'MWH', ''), ',', '') AS DECIMAL), 0.0) AS remaining_mwh
        FROM {raw_table}
        WHERE unit_name != '出售單位' -- 排除重複標頭
      )
      SELECT
        ROW_NUMBER() OVER() AS cert_clean_id, -- 生成 1NF 唯一主鍵
        b.unit_name,
        b.facility_name,
        b.energy_type,
        b.facility_address,
        b.installed_capacity,
        TRIM(single_comp) AS shared_company, -- 🌟 取得被 UNNEST 拆散開來的獨立共用公司名稱
        b.certificate_number,
        b.trec_last_issue_date,
        b.generation_start_date,
        b.generation_end_date,
        b.equipment_audit_report,
        b.power_generation_verification_report,
        b.transferred_mwh,
        b.remaining_mwh,
        CURRENT_TIMESTAMP() AS created_at
      FROM cleaned_base b
      -- 利用正則表達式把英文逗號(,)或中文頓號(、)統一換成管道符(|)，再 SPLIT 成陣列，並配合 LEFT JOIN UNNEST 炸開成多列
      LEFT JOIN UNNEST(
        IF(
          b.raw_shared_company IS NULL OR b.raw_shared_company = '',
          [CAST(NULL AS STRING)], -- 如果是空的，給予一個只有 NULL 的陣列，確保 LEFT JOIN 不會遺失原本的整列資料
          SPLIT(REGEXP_REPLACE(b.raw_shared_company, r'[,、]', '|'), '|')
        )
      ) AS single_comp ON TRUE;
              """
        self._execute_query(sql_query, task_name="1NF_Issued_Certificate")

    # =========================================================================
    #  第二正規化 (2NF) - 維度表建立階段 (Dimension Tables)
    # =========================================================================

    def build_dim_company(self):
        """
        執行第二正規化：整合憑證與直轉供表內所有曾出現過的公司單位，建置不重複的 dim_company 維度表。
        並運用高效率的 EXISTS 函數，為每家公司貼上是否為買方或賣方的 BOOLEAN (true/false) 標籤。
        """
        sql_query = f"""
        CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset_id}.dim_company` (
        company_id INT64 OPTIONS(description='公司流水號'),
        company_name STRING OPTIONS(description='公司名稱'),
        is_seller BOOL OPTIONS(description='是否為出售單位'),
        is_buyer BOOL OPTIONS(description='是否為購買者'),
        created_at TIMESTAMP OPTIONS(description='資料建立時間')
      ) AS
      -- 1. 使用 UNION DISTINCT 撈出三張表、所有角色中不重複的公司全集
      WITH all_companies AS (
        SELECT unit_name AS company_name FROM `{self.project_id}.{self.dataset_id}.trec_issued_certificate_clean` WHERE unit_name IS NOT NULL
        UNION DISTINCT
        SELECT shared_company AS company_name FROM `{self.project_id}.{self.dataset_id}.trec_issued_certificate_clean` WHERE shared_company IS NOT NULL
        UNION DISTINCT
        SELECT seller AS company_name FROM `{self.project_id}.{self.dataset_id}.trec_direct_transaction_clean` WHERE seller IS NOT NULL
        UNION DISTINCT
        SELECT buyer AS company_name FROM `{self.project_id}.{self.dataset_id}.trec_direct_transaction_clean` WHERE buyer IS NOT NULL
      )
      SELECT 
        ROW_NUMBER() OVER() AS company_id, -- 產生維度表唯一的代理鍵 ID
        c.company_name,
        -- 🌟 效能極佳的 EXISTS：判斷只要公司出現在任何一處的賣方或共用方，is_seller 即為 true
        EXISTS(
          SELECT 1 FROM `{self.project_id}.{self.dataset_id}.trec_issued_certificate_clean` WHERE unit_name = c.company_name
          UNION DISTINCT
          SELECT 1 FROM `{self.project_id}.{self.dataset_id}.trec_issued_certificate_clean` WHERE shared_company = c.company_name
          UNION DISTINCT
          SELECT 1 FROM `{self.project_id}.{self.dataset_id}.trec_direct_transaction_clean` WHERE seller = c.company_name
        ) AS is_seller,
        -- 判斷公司是否出現在直轉供的購買方，若是則 is_buyer 為 true
        EXISTS(
          SELECT 1 FROM `{self.project_id}.{self.dataset_id}.trec_direct_transaction_clean` WHERE buyer = c.company_name
        ) AS is_buyer,
        CURRENT_TIMESTAMP() AS created_at
        FROM all_companies c;
        """
        self._execute_query(sql_query, task_name="2NF_Build_Dim_Company")

    def build_dim_energy_type(self):
        """
        執行第二正規化：統整所有主題之不重複能源類型，建置 dim_energy_type 表並指派代碼。
        """
        sql_query = f"""
        CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset_id}.dim_energy_type` (
        energy_type_id INT64 OPTIONS(description='能源類型流水號'),
        energy_type STRING OPTIONS(description='能源類型'),
        created_at TIMESTAMP OPTIONS(description='資料建立時間')
        ) AS
        -- 使用 UNION DISTINCT 整合兩張主題表的能源類型，消除重複值
        WITH all_energy AS (
        SELECT DISTINCT energy_type FROM `{self.project_id}.{self.dataset_id}.trec_issued_certificate_clean` WHERE energy_type IS NOT NULL
        UNION DISTINCT
        SELECT DISTINCT energy_type FROM `{self.project_id}.{self.dataset_id}.trec_direct_transaction_clean` WHERE energy_type IS NOT NULL
        )
        SELECT 
        ROW_NUMBER() OVER() AS energy_type_id, -- 產生能源維度唯一 ID
        energy_type,                          -- 能源類型名稱
        CURRENT_TIMESTAMP() AS created_at
        FROM all_energy;
        """
        self._execute_query(sql_query, task_name="2NF_Build_Dim_Energy_Type")

    def build_dim_facility(self):
        """
        執行第二正規化：整合憑證與直轉供之所有發電設備資訊，建置以設備名稱為主鍵的 dim_facility 表。
        核心邏輯：在 1NF 階段被拆開的共用單位，在這裡透過 STRING_AGG(DISTINCT) 重新以頓號串回一個乾淨字串，
        既維持了設備唯一的粒度 (Granularity)，又妥善保留了共用單位的關聯關係。
        """
        sql_query = f"""
        CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset_id}.dim_facility` (
        facility_id INT64 OPTIONS(description='發電設備流水號'),
        facility_name STRING OPTIONS(description='發電設備'),
        shared_company STRING OPTIONS(description='發電設備共同單位'),
        facility_address STRING OPTIONS(description='發電設備地址'),
        installed_capacity_KW BIGNUMERIC OPTIONS(description='裝置容量(kW)'),
        created_at TIMESTAMP OPTIONS(description='資料建立時間')
      ) AS
      -- 1. 使用 UNION DISTINCT 撈出所有來源表中的不重複設備及其地址、容量屬性
      WITH all_facilities AS (
        SELECT DISTINCT 
          facility_name, 
          facility_address, 
          installed_capacity,
          shared_company -- 撈出炸開後的單一共用單位
        FROM `{self.project_id}.{self.dataset_id}.trec_issued_certificate_clean` 
        WHERE facility_name IS NOT NULL
        
        UNION DISTINCT
        
        SELECT DISTINCT 
          facility_name, 
          CAST(NULL AS STRING) AS facility_address, -- 直轉供無此欄位，補 NULL 進行聯集
          CAST(NULL AS NUMERIC) AS installed_capacity,
          CAST(NULL AS STRING) AS shared_company
        FROM `{self.project_id}.{self.dataset_id}.trec_direct_transaction_clean` 
        WHERE facility_name IS NOT NULL
         ),
         -- 2. 依據設備名稱分組聚合，使用 MAX 取得不為空值的屬性
        aggregated_facilities AS (
        SELECT 
        facility_name,
        MAX(facility_address) AS facility_address,
        MAX(installed_capacity) AS installed_capacity_KW,
        -- 關鍵反聚合：將屬於同設備、但被拆開的複數共用單位，去重後重新用頓號「、」合併回一列
        STRING_AGG(DISTINCT shared_company, '、') AS shared_company 
        FROM all_facilities
        GROUP BY facility_name
        )
        SELECT 
        ROW_NUMBER() OVER() AS facility_id, -- 生成設備維度唯一流水號 ID
        facility_name,                      -- 純粹發電設備名稱
        shared_company,                     -- 聚合完成的共用單位字串
        facility_address,                   -- 設備地址
        installed_capacity_KW,              -- 設備裝置總容量
        CURRENT_TIMESTAMP() AS created_at
        FROM aggregated_facilities;
        """
        self._execute_query(sql_query, task_name="2NF_Build_Dim_Facility")

    def build_dim_supply_type(self):
        """
        執行第二正規化：提取直轉供特有的不重複「供電種類」資訊，建置 dim_supply_type 表。
        """
        sql_query = f"""
        CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset_id}.dim_supply_type` (
        supply_type_id INT64 OPTIONS(description='供電種類流水號'),
        supply_type_name STRING OPTIONS(description='供電種類'),
        created_at TIMESTAMP OPTIONS(description='資料建立時間')
        ) AS
        SELECT 
        ROW_NUMBER() OVER() AS supply_type_id, -- 產生供電種類唯一 ID
        supply_type AS supply_type_name,       -- 轉換欄位名稱使維度結構更語意化
        CURRENT_TIMESTAMP() AS created_at
        FROM (
        -- 提取子查詢中不重複且非空的供電種類
        SELECT DISTINCT supply_type 
        FROM `{self.project_id}.{self.dataset_id}.trec_direct_transaction_clean` 
        WHERE supply_type IS NOT NULL
        );
        """
        self._execute_query(sql_query, task_name="2NF_Build_Dim_Supply_Type")

    # =========================================================================
    #  第二正規化 (2NF) - 事實表建立階段 (Fact Tables)
    # =========================================================================

    def build_fact_direct_transaction(self):
        """
        執行第二正規化：關聯 4 張 Dim 表，將直轉供 Clean 表的中文字串對應並替換成對應的維度 ID（外鍵）。
        最終建置出標準星狀模型的核心事實表：fact_direct_transaction。
        """
        sql_query = f"""
        CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset_id}.fact_direct_transaction` (
          transaction_id INT64 OPTIONS(description='交易流水號'),
          seller_company_name_id INT64 OPTIONS(description='出售單位流水號'),
          buyer_company_name_id INT64 OPTIONS(description='購買者流水號'),
          facility_id INT64 OPTIONS(description='發電設備流水號'),
          energy_type_id INT64 OPTIONS(description='能源類型流水號'),
          supply_type_id INT64 OPTIONS(description='供電種類流水號'),
          transaction_date DATE OPTIONS(description='成交日期）'),
          total_transfer_mwh BIGNUMERIC OPTIONS(description='總轉移量'),
          transaction_transfer_mwh BIGNUMERIC OPTIONS(description='成交轉移量'),
          created_at TIMESTAMP OPTIONS(description='資料建立時間')
        ) AS
        SELECT
          t.direct_clean_id AS transaction_id, -- 1. 將 1NF 清洗層 ID 繼承並定義為交易事實主鍵
          dc1.company_id AS seller_company_name_id, -- 2. 出售單位的數字維度外鍵 ID
          dc2.company_id AS buyer_company_name_id,  -- 3. 購買單位的數字維度外鍵 ID
          df.facility_id,                      -- 4. 發電設備外鍵 ID
          de.energy_type_id,                   -- 5. 能源類型外鍵 ID
          st.supply_type_id,                   -- 6. 供電種類外鍵 ID
          t.transaction_date,                  -- 7. 交易日期 (基礎事實)
          t.total_transfer_mwh,                -- 8. 總分配電量度量 (事實計量)
          t.transaction_transfer_mwh,          -- 9. 單筆交易轉供電量度量 (事實計量)
          CURRENT_TIMESTAMP() AS created_at
        FROM `{self.project_id}.{self.dataset_id}.trec_direct_transaction_clean` t
        -- LEFT JOIN 關聯各維度表：即使維度沒對上，也必須保留事實表的原始交易紀錄
        LEFT JOIN `{self.project_id}.{self.dataset_id}.dim_company` dc1 
          ON t.seller = dc1.company_name       -- 透過清洗後的 seller 名稱對齊出售公司 ID
        LEFT JOIN `{self.project_id}.{self.dataset_id}.dim_company` dc2 
          ON t.buyer = dc2.company_name        -- 透過清洗後的 buyer 名稱對齊購買公司 ID
        LEFT JOIN `{self.project_id}.{self.dataset_id}.dim_facility` df 
          ON t.facility_name = df.facility_name -- 透過設備名稱對齊設備 ID
        LEFT JOIN `{self.project_id}.{self.dataset_id}.dim_energy_type` de 
          ON t.energy_type = de.energy_type    -- 透過能源類型對齊能源 ID
        LEFT JOIN `{self.project_id}.{self.dataset_id}.dim_supply_type` st 
          ON t.supply_type = st.supply_type_name; -- 透過供電種類對齊種類 ID
        """
        self._execute_query(sql_query, task_name="2NF_Build_Fact_Direct_Transaction")

    def build_fact_issued_certificate(self):
        """
        執行第二正規化：關聯 Dim 表取得對應的外鍵 ID，建置國家憑證發放明細事實表：fact_issued_certificate。
        註：因 1NF 已將共用單位炸開，本事實表每列將精準紀錄「個別共用單位(shared_company_id)」與憑證的對應事實。
        """
        sql_query = f"""
        CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset_id}.fact_issued_certificate` (
        issued_certificate_id INT64 OPTIONS(description='已發放憑證流水號'),
        facility_id INT64 OPTIONS(description='發電設備流水號'),
        unit_company_id INT64 OPTIONS(description='單位流水號）'),
        shared_company_id INT64 OPTIONS(description='共用單位流水號'),
        certificate_number STRING OPTIONS(description='證書編號'),
        energy_type_id INT64 OPTIONS(description='能源類型流水號'),
        trec_last_issue_date DATE OPTIONS(description='T-REC最後憑證發放日期'),
        generation_start_date DATE OPTIONS(description='發電區間開始日期'),
        generation_end_date DATE OPTIONS(description='發電區間結束日期'),
        transferred_mwh BIGNUMERIC OPTIONS(description='已移轉量'),
        remaining_mwh BIGNUMERIC OPTIONS(description='剩餘量'),
        created_at TIMESTAMP OPTIONS(description='資料建立時間')
      ) AS
      SELECT
        c.cert_clean_id AS issued_certificate_id, -- 1. 繼承並定義憑證事實表主鍵
        df.facility_id,                           -- 2. 發電設備外鍵 ID
        dc1.company_id AS unit_company_id,        -- 3. 出售單位（持有人）公司 ID
        dc2.company_id AS shared_company_id,      -- 4. 拆解後的單一獨立共用單位公司 ID
        c.certificate_number,                     -- 5. 國家憑證證書編號文字
        de.energy_type_id,                        -- 6. 能源類型外鍵 ID
        c.trec_last_issue_date,                   -- 7. 最後發證日期 (日期事實)
        c.generation_start_date,                  -- 8. 發電區間開始日期
        c.generation_end_date,                    -- 9. 發電區間結束日期
        c.transferred_mwh,                        -- 10. 已移轉量度量 (MWh)
        c.remaining_mwh,                          -- 11. 剩餘量度量 (MWh)
        CURRENT_TIMESTAMP() AS created_at
      FROM `{self.project_id}.{self.dataset_id}.trec_issued_certificate_clean` c
      -- LEFT JOIN 各維度表換取外鍵數字 ID
      LEFT JOIN `{self.project_id}.{self.dataset_id}.dim_facility` df 
        ON c.facility_name = df.facility_name   -- 對齊發電設備
      LEFT JOIN `{self.project_id}.{self.dataset_id}.dim_company` dc1 
        ON c.unit_name = dc1.company_name        -- 對齊出售單位公司
      LEFT JOIN `{self.project_id}.{self.dataset_id}.dim_company` dc2 
        ON c.shared_company = dc2.company_name   -- 🌟 關鍵：將炸開後的單一共用公司名稱對齊維度 ID
      LEFT JOIN `{self.project_id}.{self.dataset_id}.dim_energy_type` de 
        ON c.energy_type = de.energy_type;       -- 對齊能源類型
        """
        self._execute_query(sql_query, task_name="2NF_Build_Fact_Issued_Certificate")

      # =========================================================================
    #  第四階段 (4Stage) - 儀表板觀景窗建立階段 (Dashboard Views)
    # =========================================================================

    def create_vw_transaction_detail(self):
        """
        建立核心 View：vw_transaction_detail
        將直轉供事實表與自用發電清洗表聯集，規格化為單一視圖。
        """
        view_path = f"`{self.project_id}.{self.dataset_id}.vw_transaction_detail`"
        
        sql_query = f"""
        CREATE OR REPLACE VIEW {view_path} (
          transaction_id OPTIONS(description = "交易資料流水號，直轉供使用 transaction_id，自用發電使用 self_clean_id"),
          seller_company_name OPTIONS(description = "出售單位名稱"),
          buyer_company_name OPTIONS(description = "購買者名稱"),
          facility_name OPTIONS(description = "發電設備或案場名稱"),
          energy_type_name OPTIONS(description = "能源類型名稱，例如太陽能、風力能、水力能"),
          supply_type_name OPTIONS(description = "供電種類名稱，無資料時顯示未分類；自用發電資料固定為自用發電"),
          transaction_source_type OPTIONS(description = "交易來源代碼，direct_transaction 為直轉供，self_generation_transaction 為自用發電"),
          transaction_source_name_zh OPTIONS(description = "交易來源中文名稱"),
          transaction_date OPTIONS(description = "交易日期或憑證移轉日期"),
          transaction_mwh OPTIONS(description = "本筆交易移轉量，單位 MWh"),
          total_transfer_mwh OPTIONS(description = "來源資料中的總移轉量，單位 MWh"),
          created_at OPTIONS(description = "資料建立時間")
        ) AS
        WITH direct_transactions AS (
          SELECT
            d.transaction_id AS transaction_id,
            seller.company_name AS seller_company_name,
            buyer.company_name AS buyer_company_name,
            f.facility_name AS facility_name,
            e.energy_type AS energy_type_name,
            COALESCE(s.supply_type_name, '未分類') AS supply_type_name,
            'direct_transaction' AS transaction_source_type,
            '直轉供憑證成交' AS transaction_source_name_zh,
            d.transaction_date AS transaction_date,
            CAST(d.transaction_transfer_mwh AS FLOAT64) AS transaction_mwh,
            CAST(d.total_transfer_mwh AS FLOAT64) AS total_transfer_mwh,
            d.created_at AS created_at
          FROM `{self.project_id}.{self.dataset_id}.fact_direct_transaction` d
          LEFT JOIN `{self.project_id}.{self.dataset_id}.dim_company` seller
            ON d.seller_company_name_id = seller.company_id
          LEFT JOIN `{self.project_id}.{self.dataset_id}.dim_company` buyer
            ON d.buyer_company_name_id = buyer.company_id
          LEFT JOIN `{self.project_id}.{self.dataset_id}.dim_facility` f
            ON d.facility_id = f.facility_id
          LEFT JOIN `{self.project_id}.{self.dataset_id}.dim_energy_type` e
            ON d.energy_type_id = e.energy_type_id
          LEFT JOIN `{self.project_id}.{self.dataset_id}.dim_supply_type` s
            ON d.supply_type_id = s.supply_type_id
        ),
        self_generation_transactions AS (
          SELECT
            self_clean_id AS transaction_id,
            seller AS seller_company_name,
            buyer AS buyer_company_name,
            facility_name,
            energy_type AS energy_type_name,
            '自用發電' AS supply_type_name,
            'self_generation_transaction' AS transaction_source_type,
            '自用發電設備憑證成交' AS transaction_source_name_zh,
            transfer_date AS transaction_date,
            CAST(transfer_mwh AS FLOAT64) AS transaction_mwh,
            CAST(transfer_mwh AS FLOAT64) AS total_transfer_mwh,
            created_at
          FROM `{self.project_id}.{self.dataset_id}.trec_self_generation_transaction_clean`
        )
        SELECT * FROM direct_transactions
        UNION ALL
        SELECT * FROM self_generation_transactions;
        """
        self._execute_query(sql_query, task_name="Create_Vw_Transaction_Detail")

    def create_vw_dashboard_yearly(self):
        """建立年度交易量摘要 View"""
        view_path = f"`{self.project_id}.{self.dataset_id}.vw_dashboard_yearly`"
        
        sql_query = f"""
        CREATE OR REPLACE VIEW {view_path} (
          transaction_year OPTIONS(description = "交易年度"),
          transaction_count OPTIONS(description = "年度交易筆數"),
          seller_company_count OPTIONS(description = "年度出售單位數"),
          buyer_company_count OPTIONS(description = "年度購買者數"),
          facility_count OPTIONS(description = "年度發電設備或案場數"),
          total_transaction_mwh OPTIONS(description = "年度總成交移轉量，單位 MWh")
        ) AS
        SELECT
          EXTRACT(YEAR FROM transaction_date) AS transaction_year,
          COUNT(*) AS transaction_count,
          COUNT(DISTINCT seller_company_name) AS seller_company_count,
          COUNT(DISTINCT buyer_company_name) AS buyer_company_count,
          COUNT(DISTINCT facility_name) AS facility_count,
          SUM(transaction_mwh) AS total_transaction_mwh
        FROM `{self.project_id}.{self.dataset_id}.vw_transaction_detail`
        GROUP BY 1;
        """
        self._execute_query(sql_query, task_name="Create_Vw_Dashboard_Yearly")

    def create_vw_dashboard_monthly(self):
        """建立月度趨勢 View"""
        view_path = f"`{self.project_id}.{self.dataset_id}.vw_dashboard_monthly`"
        sql_query = f"""
        CREATE OR REPLACE VIEW {view_path} (
          transaction_month OPTIONS(description = "交易月份，取該月第一天作為月份代表日期"),
          transaction_count OPTIONS(description = "月交易筆數"),
          total_transaction_mwh OPTIONS(description = "月總成交移轉量，單位 MWh"),
          direct_transaction_mwh OPTIONS(description = "月直轉供成交移轉量，單位 MWh"),
          self_generation_transaction_mwh OPTIONS(description = "月自用發電成交移轉量，單位 MWh")
        ) AS
        SELECT
          DATE_TRUNC(transaction_date, MONTH) AS transaction_month,
          COUNT(*) AS transaction_count,
          SUM(transaction_mwh) AS total_transaction_mwh,
          SUM(IF(transaction_source_type = 'direct_transaction', transaction_mwh, 0)) AS direct_transaction_mwh,
          SUM(IF(transaction_source_type = 'self_generation_transaction', transaction_mwh, 0)) AS self_generation_transaction_mwh
        FROM `{self.project_id}.{self.dataset_id}.vw_transaction_detail`
        GROUP BY transaction_month;
        """
        self._execute_query(sql_query, task_name="Create_Vw_Dashboard_Monthly")

    def create_vw_dashboard_daily(self):
        """建立日粒度趨勢 View"""
        view_path = f"`{self.project_id}.{self.dataset_id}.vw_dashboard_daily`"
        sql_query = f"""
        CREATE OR REPLACE VIEW {view_path} (
          transaction_day OPTIONS(description = "交易日期"),
          transaction_count OPTIONS(description = "日交易筆數"),
          total_transaction_mwh OPTIONS(description = "日總成交移轉量，單位 MWh"),
          direct_transaction_mwh OPTIONS(description = "日直轉供成交移轉量，單位 MWh"),
          self_generation_transaction_mwh OPTIONS(description = "日自用發電成交移轉量，單位 MWh")
        ) AS
        SELECT
          transaction_date AS transaction_day,
          COUNT(*) AS transaction_count,
          SUM(transaction_mwh) AS total_transaction_mwh,
          SUM(IF(transaction_source_type = 'direct_transaction', transaction_mwh, 0)) AS direct_transaction_mwh,
          SUM(IF(transaction_source_type = 'self_generation_transaction', transaction_mwh, 0)) AS self_generation_transaction_mwh
        FROM `{self.project_id}.{self.dataset_id}.vw_transaction_detail`
        GROUP BY transaction_day;
        """
        self._execute_query(sql_query, task_name="Create_Vw_Dashboard_Daily")

    def create_vw_dashboard_energy_type(self):
        """建立能源類型占比 View"""
        view_path = f"`{self.project_id}.{self.dataset_id}.vw_dashboard_energy_type`"
        sql_query = f"""
        CREATE OR REPLACE VIEW {view_path} (
          energy_type_name OPTIONS(description = "能源類型名稱"),
          transaction_count OPTIONS(description = "該能源類型交易筆數"),
          total_transaction_mwh OPTIONS(description = "該能源類型總成交移轉量，單位 MWh")
        ) AS
        SELECT
          COALESCE(energy_type_name, '未分類') AS energy_type_name,
          COUNT(*) AS transaction_count,
          SUM(transaction_mwh) AS total_transaction_mwh
        FROM `{self.project_id}.{self.dataset_id}.vw_transaction_detail`
        GROUP BY energy_type_name;
        """
        self._execute_query(sql_query, task_name="Create_Vw_Dashboard_Energy_Type")

    def create_vw_dashboard_source(self):
        """建立交易來源分析 View"""
        view_path = f"`{self.project_id}.{self.dataset_id}.vw_dashboard_source`"
        sql_query = f"""
        CREATE OR REPLACE VIEW {view_path} (
          transaction_source_type OPTIONS(description = "交易來源代碼"),
          transaction_source_name_zh OPTIONS(description = "交易來源中文名稱"),
          transaction_count OPTIONS(description = "該交易來源交易筆數"),
          total_transaction_mwh OPTIONS(description = "該交易來源總成交移轉量，單位 MWh")
        ) AS
        SELECT
          transaction_source_type,
          transaction_source_name_zh,
          COUNT(*) AS transaction_count,
          SUM(transaction_mwh) AS total_transaction_mwh
        FROM `{self.project_id}.{self.dataset_id}.vw_transaction_detail`
        GROUP BY transaction_source_type, transaction_source_name_zh;
        """
        self._execute_query(sql_query, task_name="Create_Vw_Dashboard_Source")

    def create_vw_dashboard_supply_type(self):
        """建立供電種類分析 View"""
        view_path = f"`{self.project_id}.{self.dataset_id}.vw_dashboard_supply_type`"
        sql_query = f"""
        CREATE OR REPLACE VIEW {view_path} (
          supply_type_name OPTIONS(description = "供電種類名稱"),
          transaction_count OPTIONS(description = "該供電種類交易筆數"),
          total_transaction_mwh OPTIONS(description = "該供電種類總成交移轉量，單位 MWh")
        ) AS
        SELECT
          COALESCE(supply_type_name, '未分類') AS supply_type_name,
          COUNT(*) AS transaction_count,
          SUM(transaction_mwh) AS total_transaction_mwh
        FROM `{self.project_id}.{self.dataset_id}.vw_transaction_detail`
        GROUP BY supply_type_name;
        """
        self._execute_query(sql_query, task_name="Create_Vw_Dashboard_Supply_Type")

    def create_vw_dashboard_seller(self):
        """建立出售單位 Top 排行 View"""
        view_path = f"`{self.project_id}.{self.dataset_id}.vw_dashboard_seller`"
        sql_query = f"""
        CREATE OR REPLACE VIEW {view_path} (
          seller_company_name OPTIONS(description = "出售單位名稱"),
          transaction_count OPTIONS(description = "該出售單位交易筆數"),
          buyer_company_count OPTIONS(description = "該出售單位對應的購買者數"),
          facility_count OPTIONS(description = "該出售單位對應的發電設備或案場數"),
          total_transaction_mwh OPTIONS(description = "該出售單位總成交移轉量，單位 MWh")
        ) AS
        SELECT
          COALESCE(seller_company_name, '未填寫出售單位') AS seller_company_name,
          COUNT(*) AS transaction_count,
          COUNT(DISTINCT buyer_company_name) AS buyer_company_count,
          COUNT(DISTINCT facility_name) AS facility_count,
          SUM(transaction_mwh) AS total_transaction_mwh
        FROM `{self.project_id}.{self.dataset_id}.vw_transaction_detail`
        GROUP BY seller_company_name;
        """
        self._execute_query(sql_query, task_name="Create_Vw_Dashboard_Seller")

    def create_vw_dashboard_buyer(self):
        """建立購買者 Top 排行 View"""
        view_path = f"`{self.project_id}.{self.dataset_id}.vw_dashboard_buyer`"
        sql_query = f"""
        CREATE OR REPLACE VIEW {view_path} (
          buyer_company_name OPTIONS(description = "購買者名稱"),
          transaction_count OPTIONS(description = "該購買者交易筆數"),
          seller_company_count OPTIONS(description = "該購買者對應的出售單位數"),
          facility_count OPTIONS(description = "該購買者對應的發電設備或案場數"),
          total_transaction_mwh OPTIONS(description = "該購買者總成交移轉量，單位 MWh")
        ) AS
        SELECT
          COALESCE(buyer_company_name, '未填寫購買者') AS buyer_company_name,
          COUNT(*) AS transaction_count,
          COUNT(DISTINCT seller_company_name) AS seller_company_count,
          COUNT(DISTINCT facility_name) AS facility_count,
          SUM(transaction_mwh) AS total_transaction_mwh
        FROM `{self.project_id}.{self.dataset_id}.vw_transaction_detail`
        GROUP BY buyer_company_name;
        """
        self._execute_query(sql_query, task_name="Create_Vw_Dashboard_Buyer")