import { BigQuery } from "@google-cloud/bigquery";
import { config } from "./config.js";

export const bigquery = new BigQuery({
  projectId: config.googleCloudProject || undefined,
  location: config.bigQueryLocation
});

export async function runQuery(query, params = {}) {
  const [job] = await bigquery.createQueryJob({
    query,
    params,
    location: config.bigQueryLocation
  });

  const [rows] = await job.getQueryResults();
  return rows;
}
