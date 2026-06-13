from utils import get_connection, print_separator

# 這支程式用來測試 Python 是否能透過 PyMySQL 成功連上 MySQL。
# 測試流程：
# 1. 呼叫 utils.py 裡的 get_connection()
# 2. 如果連線成功，就執行 SHOW TABLES; 檢查目前資料庫有哪些資料表
# 3. 測試結束後，關閉 cursor 與資料庫連線
def test_mysql_connection():
    """
    測試 MySQL 資料庫連線是否成功，並列出目前資料庫中的資料表。
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        print_separator()
        print("MySQL 連線成功")
        cursor.execute("SHOW TABLES;")
        tables = cursor.fetchall()
        print("目前資料庫中的資料表：")
        for table in tables:
            print(table[0])
        cursor.close()
        conn.close()
        print("MySQL 連線已關閉")
        print_separator()
    except Exception as error:
        print_separator()
        print("MySQL 連線失敗")
        print(f"錯誤訊息：{error}")
        print_separator()

if __name__ == "__main__":
    test_mysql_connection()
