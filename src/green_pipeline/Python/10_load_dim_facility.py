from utils import clean_empty, get_connection, print_separator

TARGET_TABLE = "dim_facility"

# 這支程式負責用發電設備名稱、能源類型與地址判斷同一個發電設備，去重後寫入 dim_facility。
def build_facility_match_key(facility_name, energy_type_id, facility_address):
    """
    建立發電設備判斷鍵。
    """
    if facility_address is None:
        return f"{facility_name}|{energy_type_id}|NO_ADDRESS"
    return f"{facility_name}|{energy_type_id}|{facility_address}"

def load_dim_facility():
    """
    載入發電設備維度表。
    """
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT energy_type_id, energy_type_name FROM dim_energy_type")
        energy_type_map = {row[1]: row[0] for row in cursor.fetchall()}
        facility_map = {}
        source_queries = [
            "SELECT facility_name, energy_type, NULL AS facility_address, NULL AS installed_capacity_kw FROM trec_direct_transaction_clean",
            "SELECT facility_name, energy_type, NULL AS facility_address, NULL AS installed_capacity_kw FROM trec_self_generation_transaction_clean",
            "SELECT facility_name, energy_type, facility_address, installed_capacity_kw FROM trec_issued_certificate_clean",
        ]
        for query in source_queries:
            cursor.execute(query)
            for row in cursor.fetchall():
                facility_name = clean_empty(row[0])
                energy_type_name = clean_empty(row[1])
                facility_address = clean_empty(row[2])
                installed_capacity_kw = row[3]
                if facility_name is None or energy_type_name is None:
                    continue
                energy_type_id = energy_type_map.get(energy_type_name)
                if energy_type_id is None:
                    raise ValueError(f"找不到能源類型：{energy_type_name}")
                facility_match_key = build_facility_match_key(facility_name, energy_type_id, facility_address)
                key = (facility_match_key, facility_name, energy_type_id, facility_address)
                facility_map.setdefault(key, {"addresses": set(), "capacities": set()})
                if facility_address is not None:
                    facility_map[key]["addresses"].add(facility_address)
                if installed_capacity_kw is not None:
                    facility_map[key]["capacities"].add(installed_capacity_kw)
        rows = []
        for (facility_match_key, facility_name, energy_type_id, default_address), values in sorted(facility_map.items()):
            facility_address = sorted(values["addresses"])[0] if values["addresses"] else None
            installed_capacity_kw = sorted(values["capacities"])[0] if values["capacities"] else None
            if facility_address is None:
                facility_address = default_address
            rows.append((facility_match_key, facility_name, facility_address, installed_capacity_kw, energy_type_id))
        insert_sql = f"""
            INSERT IGNORE INTO {TARGET_TABLE} (
                facility_match_key,
                facility_name,
                facility_address,
                installed_capacity_kw,
                energy_type_id
            )
            VALUES (%s, %s, %s, %s, %s)
        """
        cursor.executemany(insert_sql, rows)
        conn.commit()
        print_separator()
        print(f"{TARGET_TABLE} 載入完成")
        print(f"來源去重發電設備數：{len(rows)}")
        print(f"新增筆數：{cursor.rowcount}")
    except Exception as error:
        if conn is not None:
            conn.rollback()
        print_separator()
        print(f"{TARGET_TABLE} 載入失敗")
        print(f"錯誤訊息：{error}")
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()
            print("MySQL 連線已關閉")
            print_separator()

if __name__ == "__main__":
    load_dim_facility()
