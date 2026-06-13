"""
05_create_views_v5.py

用途：
執行 02_create_views_v5.sql，建立 Tableau 使用的 View。
"""

from utils_v5 import SQL_DIR, execute_sql_file


def main():
    """
    主程式：建立所有分析 View。
    """
    execute_sql_file(SQL_DIR / "02_create_views_v5.sql", use_database=True)


if __name__ == "__main__":
    main()
