from fnmatch import fnmatch
from pathlib import Path
from google.cloud import storage

# 這支程式是 STAR0 的第 1 步。
# 目的：只檢查 GCS 上三個 CSV 來源是否存在。
# 不會建立 BigQuery table，也不會修改任何 GCS 檔案。

STAR0_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = STAR0_ROOT / ".env.gcp"

SOURCE_KEYS = [
    ("直轉供憑證成交", "GCS_DIRECT_TRANSACTION_URI"),
    ("自用發電設備憑證成交", "GCS_SELF_GENERATION_TRANSACTION_URI"),
    ("已發放憑證", "GCS_ISSUED_CERTIFICATE_URI"),
]

def print_separator():
    """
    印出分隔線，讓終端機輸出比較容易閱讀。
    """
    print("=" * 60)

def get_env_value(key):
    """
    從 BigQuery/STAR0/.env.gcp 讀取指定設定值。
    """
    if not ENV_PATH.exists():
        return None
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line == "" or line.startswith("#"):
            continue
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return None

def split_env_uris(value):
    """
    將設定值拆成多個 GCS URI。

    如果只有一個 URI，會回傳一個元素。
    如果用逗號分隔多個 URI，會回傳多個元素。
    """
    return [item.strip() for item in value.split(",") if item.strip()]

def parse_gcs_uri(uri):
    """
    將 gs://bucket/path/file.csv 拆成 bucket_name 與 object_name。

    回傳範例：
    bucket_name = tibame-bronze
    object_name = raw_data/certified_issued_data/file.csv
    """
    if not uri.startswith("gs://"):
        raise ValueError(f"GCS 路徑必須以 gs:// 開頭：{uri}")
    path = uri.replace("gs://", "", 1)
    parts = path.split("/", 1)
    if len(parts) != 2 or parts[0] == "" or parts[1] == "":
        raise ValueError(f"GCS 路徑格式不完整：{uri}")
    return parts[0], parts[1]

def get_prefix_before_wildcard(object_pattern):
    """
    取得 wildcard 前面的固定資料夾 prefix。

    例如：
    raw_data/certified_issued_data/trec_issued_certificate_*_raw.csv

    會得到：
    raw_data/certified_issued_data/
    """
    wildcard_index = object_pattern.find("*")
    fixed_part = object_pattern[:wildcard_index]
    if "/" not in fixed_part:
        return ""
    return fixed_part.rsplit("/", 1)[0] + "/"

def check_exact_file(storage_client, uri):
    """
    檢查沒有 wildcard 的單一 GCS 檔案是否存在。
    """
    bucket_name, object_name = parse_gcs_uri(uri)
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(object_name)
    if not blob.exists():
        return []
    return [uri]

def check_wildcard_files(storage_client, uri):
    """
    檢查含有 * wildcard 的 GCS 路徑可以匹配到哪些檔案。

    Google Cloud Storage 不是傳統資料夾系統，所以這裡的做法是：
    1. 先列出固定 prefix 底下的檔案
    2. 再用 fnmatch 比對完整 object name 是否符合 wildcard pattern
    """
    bucket_name, object_pattern = parse_gcs_uri(uri)
    prefix = get_prefix_before_wildcard(object_pattern)
    blobs = storage_client.list_blobs(bucket_name, prefix=prefix)
    matched_uris = []
    for blob in blobs:
        if fnmatch(blob.name, object_pattern):
            matched_uris.append(f"gs://{bucket_name}/{blob.name}")
    return sorted(matched_uris)

def check_source(storage_client, label, env_key):
    """
    檢查單一來源路徑。
    """
    uri_value = get_env_value(env_key)
    if not uri_value:
        raise RuntimeError(f"請先在 BigQuery/STAR0/.env.gcp 設定 {env_key}")
    source_uris = split_env_uris(uri_value)
    matched_uris = []
    for uri in source_uris:
        if "*" in uri:
            matched_uris.extend(check_wildcard_files(storage_client, uri))
        else:
            matched_uris.extend(check_exact_file(storage_client, uri))
    matched_uris = sorted(set(matched_uris))
    print_separator()
    print(f"來源：{label}")
    print(f"設定：{env_key}")
    print(f"路徑：{uri_value}")
    print(f"找到檔案數：{len(matched_uris)}")
    for matched_uri in matched_uris:
        print(f"- {matched_uri}")
    if not matched_uris:
        raise RuntimeError(f"{label} 找不到任何檔案，請確認 GCS 路徑是否正確")

def check_gcs_sources():
    """
    主流程：逐一檢查三個 GCS 來源。
    """
    project_id = get_env_value("GCP_PROJECT_ID")
    if not project_id:
        raise RuntimeError("請先在 BigQuery/STAR0/.env.gcp 設定 GCP_PROJECT_ID")
    storage_client = storage.Client(project=project_id)
    for label, env_key in SOURCE_KEYS:
        check_source(storage_client, label, env_key)
    print_separator()
    print("三個 GCS 來源都已確認可以找到檔案")
    print_separator()

if __name__ == "__main__":
    check_gcs_sources()
