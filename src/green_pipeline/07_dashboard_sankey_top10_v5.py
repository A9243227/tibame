"""
07_dashboard_sankey_top10_v5.py

用途：
從 vw_sankey_data 讀取資料，產生 Top 10 Sankey 桑基圖。

輸出檔案：
output/sankey_top10_v5.html

若在 VS Code 或終端機執行 fig.show() 沒有反應，
請直接打開 HTML 檔案。
"""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from utils_v5 import BASE_DIR, get_connection


def load_sankey_data():
    """
    從 MySQL View 讀取 Sankey 所需資料。

    source：出售單位
    target：購買者
    value：移轉量(MWh)
    """
    conn = get_connection()

    sql = """
        SELECT source, target, value
        FROM vw_sankey_data
        WHERE source IS NOT NULL
          AND target IS NOT NULL
          AND value IS NOT NULL
        ORDER BY value DESC
        LIMIT 10
    """

    try:
        return pd.read_sql(sql, conn)
    finally:
        conn.close()


def build_sankey_chart(df):
    """
    建立 Sankey 圖。

    Plotly 的 Sankey 需要：
    1. labels：節點名稱
    2. source_index：來源節點索引
    3. target_index：目標節點索引
    4. value：流量數值
    """
    labels = list(pd.unique(df[["source", "target"]].values.ravel()))

    source_index = df["source"].apply(lambda name: labels.index(name))
    target_index = df["target"].apply(lambda name: labels.index(name))

    fig = go.Figure(data=[go.Sankey(
        node=dict(
            label=labels,
            pad=15,
            thickness=20,
        ),
        link=dict(
            source=source_index,
            target=target_index,
            value=df["value"],
        )
    )])

    fig.update_layout(
        title_text="Top 10 綠電交易 Sankey 圖",
        font_size=12,
    )

    return fig


def main():
    """
    主程式：
    1. 讀取 Sankey 資料
    2. 建立圖表
    3. 輸出 HTML
    """
    output_dir = BASE_DIR / "output"
    output_dir.mkdir(exist_ok=True)

    df = load_sankey_data()

    if df.empty:
        print("vw_sankey_data 沒有資料，請先確認 ETL 是否成功。")
        return

    fig = build_sankey_chart(df)

    output_file = output_dir / "sankey_top10_v5.html"
    fig.write_html(output_file)

    print(f"Sankey 圖已輸出：{output_file}")
    print("Mac 可使用以下指令打開：")
    print(f"open {output_file}")


if __name__ == "__main__":
    main()
