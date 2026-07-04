import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { config } from "./config.js";
import { fetchDashboard } from "./dashboardQueries.js";
import { fetchSites, fetchSummary } from "./queries.js";
import { getMockSites, getMockSummary } from "./mockData.js";

const app = express();
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.join(__dirname, "..", "public");
const distDir = path.join(__dirname, "..", "dist");

app.use(express.static(distDir));
app.use(express.static(publicDir));

app.get("/api/health", (_req, res) => {
  res.json({
    ok: true,
    mode: config.useMockData ? "mock" : "bigquery"
  });
});

app.get("/api/sites", async (_req, res, next) => {
  try {
    const sites = config.useMockData ? getMockSites() : await fetchSites();
    res.json({ sites });
  } catch (error) {
    next(error);
  }
});

app.get("/api/summary", async (req, res, next) => {
  try {
    const today = new Date().toISOString().slice(0, 10);
    const filters = {
      from: String(req.query.from || "2026-01-01"),
      to: String(req.query.to || today),
      site: req.query.site ? String(req.query.site) : ""
    };

    const summary = config.useMockData
      ? getMockSummary(filters)
      : await fetchSummary(filters);

    res.json({
      filters,
      source: config.useMockData ? "mock" : "bigquery",
      ...summary
    });
  } catch (error) {
    next(error);
  }
});

app.get("/api/dashboard", async (req, res, next) => {
  try {
    const dashboard = await fetchDashboard(req.query);
    res.json(dashboard);
  } catch (error) {
    next(error);
  }
});

app.get("*", (req, res, next) => {
  if (req.path.startsWith("/api/")) {
    next();
    return;
  }

  res.sendFile(path.join(distDir, "index.html"), (error) => {
    if (error) next();
  });
});

app.use((error, _req, res, _next) => {
  console.error(error);
  res.status(500).json({
    error: "Request failed",
    message: error.message
  });
});

app.listen(config.port, () => {
  console.log(`green_demo_web running at http://localhost:${config.port}`);
  console.log(`Data source: ${config.useMockData ? "mock" : "bigquery"}`);
});
