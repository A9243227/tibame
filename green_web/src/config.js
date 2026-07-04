import dotenv from "dotenv";

dotenv.config();

export const config = {
  port: Number(process.env.PORT || 3000),
  useMockData: String(process.env.USE_MOCK_DATA || "true").toLowerCase() === "true",
  googleCloudProject: process.env.GOOGLE_CLOUD_PROJECT || "",
  bigQueryLocation: process.env.BIGQUERY_LOCATION || "US",
  bigQueryDataset: process.env.BIGQUERY_DATASET || "trec_data",
  bigQueryTable: process.env.BIGQUERY_TABLE || "fact_issued_certificate"
};

export function getTableName() {
  const { googleCloudProject, bigQueryDataset, bigQueryTable } = config;

  if (!googleCloudProject) {
    throw new Error("GOOGLE_CLOUD_PROJECT is required when USE_MOCK_DATA=false.");
  }

  return `\`${googleCloudProject}.${bigQueryDataset}.${bigQueryTable}\``;
}

export function getDatasetTableName(tableName) {
  const { googleCloudProject, bigQueryDataset } = config;

  if (!googleCloudProject) {
    throw new Error("GOOGLE_CLOUD_PROJECT is required when USE_MOCK_DATA=false.");
  }

  return `\`${googleCloudProject}.${bigQueryDataset}.${tableName}\``;
}
