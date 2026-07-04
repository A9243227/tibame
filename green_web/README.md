# green_demo_web

BigQuery T-REC certificate dashboard reference web project.

繁體中文說明請看 [README.zh-TW.md](README.zh-TW.md).

This sample provides:

- A small Express web server.
- A browser dashboard served from `public/`.
- BigQuery-backed API endpoints.
- Mock data mode for local preview before BigQuery is ready.
- Example BigQuery schema and seed SQL.

## Requirements

- Node.js 20+
- A Google Cloud project with BigQuery enabled
- Local Application Default Credentials or a service account key

## Quick Start

```bash
cd green_demo_web
npm install
cp .env.example .env
npm run dev
```

Open:

```text
http://localhost:3000
```

The app starts with `USE_MOCK_DATA=true`, so it works before BigQuery is configured.

If port `3000` is already in use:

```bash
PORT=41731 npm run dev
```

## BigQuery Setup

1. Create a dataset and table with the example SQL:

```bash
bq query --use_legacy_sql=false < bigquery/schema.sql
bq query --use_legacy_sql=false < bigquery/seed.sql
```

2. Edit `.env`:

```env
USE_MOCK_DATA=false
GOOGLE_CLOUD_PROJECT=tibametopics
BIGQUERY_LOCATION=asia-east1
BIGQUERY_DATASET=trec_data
BIGQUERY_TABLE=fact_issued_certificate
```

3. Authenticate locally:

```bash
gcloud auth application-default login
```

For production, use a service account with the minimum BigQuery permissions required to run read queries.

## Expected BigQuery Table

Default fact table:

```text
`${GOOGLE_CLOUD_PROJECT}.${BIGQUERY_DATASET}.${BIGQUERY_TABLE}`
```

The API also joins:

- `dim_facility`
- `dim_energy_type`
- `dim_company`

Columns:

| Column | Type | Description |
| --- | --- | --- |
| raw_id | INTEGER | Raw record ID |
| unit_name | STRING | Renewable energy unit name |
| facility_name | STRING | Facility name |
| energy_type | STRING | Energy type |
| facility_address | STRING | Facility address |
| installed_capacity | STRING | Installed capacity |
| shared_company | STRING | Shared or supplied company |
| certificate_number | STRING | Certificate number |
| trec_last_issue_date | STRING | Latest T-REC issue date |
| generation_period | STRING | Generation period |
| equipment_audit_report | STRING | Equipment audit report |
| power_generation_verification_report | STRING | Power generation verification report |
| transferred_mwh | STRING | Transferred MWh |
| remaining_mwh | STRING | Remaining MWh |
| created_at | TIMESTAMP | Record creation time |

## API

### `GET /api/summary`

Returns T-REC KPI cards and chart data.

Query parameters:

- `from`: start date based on `created_at`, default `2026-01-01`
- `to`: end date, default today
- `site`: optional `facility_name` filter

### `GET /api/sites`

Returns distinct facility names.

## Project Layout

```text
green_demo_web/
  bigquery/
    schema.sql
    seed.sql
  public/
    index.html
    styles.css
    app.js
  src/
    bigqueryClient.js
    config.js
    mockData.js
    queries.js
    server.js
```
