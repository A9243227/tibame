import io
from google.cloud import bigquery

class BigQueryETLPipeline:
    import io
from google.cloud import bigquery

class BigQueryETLPipeline:
    def __init__(self, project_id: str = "trec-test-499607", dataset_id: str = "trec_test"):
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
        CREATE OR REPLACE TABLE {clean_table} AS
        SELECT
          ROW_NUMBER() OVER() AS self_clean_id, -- 1. 生成清洗層唯一的流水號
          {seller_sql},                          -- 2. 洗淨後的出售單位
          {facility_sql},                        -- 3. 洗淨後的發電設備名稱
          {buyer_sql},                           -- 4. 洗淨後的購買者
          {energy_sql},                          -- 5. 洗淨後的能源類型
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
        CREATE OR REPLACE TABLE {clean_table} AS
        SELECT
          ROW_NUMBER() OVER() AS direct_clean_id, -- 1. 生成清洗層唯一主鍵
          {seller_sql},                           -- 2. 洗淨後的出售單位
          {facility_sql},                         -- 3. 洗淨後的設備名稱
          {buyer_sql},                            -- 4. 洗淨後的購買者
          {energy_sql},                           -- 5. 洗淨後的能源類型
          {supply_sql},                           -- 6. 洗淨後的供電種類
          {total_mwh_sql},                        -- 7. 清除千分位後的總分配電量
          SAFE_CAST(transaction_date AS DATE) AS transaction_date, -- 8. 轉型交易日期為 DATE
          {tx_mwh_sql},                           -- 9. 清除千分位後的單筆交易電量
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
        CREATE OR REPLACE TABLE {clean_table} AS
        WITH cleaned_base AS (
          SELECT
            {unit_sql},
            {facility_sql},
            {energy_sql},
            {address_sql},
            -- 轉型裝置容量：先強制大寫、拔除 'KW' 單位、拿掉逗號，最後安全轉換為 DECIMAL
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
        CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset_id}.dim_company` AS
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
          ROW_NUMBER() OVER() AS company_id, -- 產生維度表唯一的代理鍵 (Surrogate Key) ID
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
        CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset_id}.dim_energy_type` AS
        -- 使用 UNION DISTINCT 整合兩張主題表的能源類型，消除重複值
        WITH all_energy AS (
          SELECT DISTINCT energy_type FROM `{self.project_id}.{self.dataset_id}.trec_issued_certificate_clean` WHERE energy_type IS NOT NULL
          UNION DISTINCT
          SELECT DISTINCT energy_type FROM `{self.project_id}.{self.dataset_id}.trec_direct_transaction_clean` WHERE energy_type IS NOT NULL
        )
        SELECT 
          ROW_NUMBER() OVER() AS energy_type_id, -- 產生能源維度唯一 ID
          energy_type,                          -- 能源類型名稱 (例如: 太陽能、風力)
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
        CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset_id}.dim_facility` AS
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
            -- 🌟 關鍵反聚合：將屬於同設備、但被拆開的複數共用單位，去重後重新用頓號「、」合併回一列
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
        CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset_id}.dim_supply_type` AS
        SELECT 
          ROW_NUMBER() OVER() AS supply_type_id, -- 產生供電種類唯一 ID
          supply_type AS supply_type_name,       -- 轉換欄位名稱使維度結構更語意化
          CURRENT_TIMESTAMP() AS created_at
        FROM (
          -- 提取子查詢中不重複且非空的供電種類 (如: 第一類再生能源發電設備直供)
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
        CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset_id}.fact_direct_transaction` AS
        SELECT
          t.direct_clean_id AS transaction_id, -- 1. 將 1NF 清洗層 ID 繼承並定義為交易事實主鍵
          dc1.company_id AS seller_company_id, -- 2. 出售單位的數字維度外鍵 ID
          dc2.company_id AS buyer_company_id,  -- 3. 購買單位的數字維度外鍵 ID
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
        CREATE OR REPLACE TABLE `{self.project_id}.{self.dataset_id}.fact_issued_certificate` AS
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