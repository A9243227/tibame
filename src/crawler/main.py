import os
import subprocess
import sys

def main():
    # 只有具備無頭模式與 GCS 上傳邏輯的爬蟲
    scripts = [
        "Applied_REC_cloudrun.py",
        # "cloud_run_auto_self_use.py",
        # "test.py"
    ]

    # Cloud Run Jobs 會自動傳入 CLOUD_RUN_TASK_INDEX 環境變數
    # 如果沒有傳入 (例如本機測試)，預設為 0
    task_index_str = os.environ.get("CLOUD_RUN_TASK_INDEX", "0")
    
    try:
        task_index = int(task_index_str)
    except ValueError:
        print(f"無效的 Task Index: {task_index_str}，預設使用 0")
        task_index = 0

    if task_index < len(scripts):
        script_to_run = scripts[task_index]
        print(f"Task Index {task_index}: 準備執行 {script_to_run}", flush=True)
        
        # 取得當前檔案所在目錄的絕對路徑
        current_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(current_dir, script_to_run)
        
        # 執行對應的腳本
        result = subprocess.run(["python", script_path])
        
        # 如果爬蟲發生錯誤，讓主程式也回傳非 0 狀態碼
        sys.exit(result.returncode)
    else:
        print(f"Task Index {task_index} 超出預設腳本範圍 (目前有 {len(scripts)} 支腳本)，忽略執行。", flush=True)
        sys.exit(0)

if __name__ == "__main__":
    main()
