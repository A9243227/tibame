import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { config } from "./config.js";

const pendingWrites = new Map();

function todayKey() {
  return new Date().toISOString().slice(0, 10);
}

function normalizeQuery(query = {}) {
  return Object.fromEntries(
    Object.entries(query)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, value]) => [key, Array.isArray(value) ? value.map(String).sort() : String(value)])
  );
}

function cacheFilePath(cacheName, query = {}) {
  const day = todayKey();
  const normalized = normalizeQuery(query);
  const hash = crypto.createHash("sha256").update(JSON.stringify(normalized)).digest("hex").slice(0, 16);

  return {
    day,
    filePath: path.join(config.dailyCacheDir, cacheName, `${day}-${hash}.json`)
  };
}

async function readCache(filePath) {
  try {
    const raw = await fs.readFile(filePath, "utf8");
    return JSON.parse(raw);
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}

async function removeOldCacheFiles(cacheName, currentDay) {
  const dir = path.join(config.dailyCacheDir, cacheName);

  try {
    const files = await fs.readdir(dir);
    await Promise.all(
      files
        .filter((file) => file.endsWith(".json") && !file.startsWith(`${currentDay}-`))
        .map((file) => fs.rm(path.join(dir, file), { force: true }))
    );
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
}

export async function getDailyCachedData(cacheName, query, fetchFreshData) {
  const { day, filePath } = cacheFilePath(cacheName, query);
  const cached = await readCache(filePath);

  if (cached) {
    return { data: cached.data, cacheStatus: "hit", cacheDate: cached.cacheDate };
  }

  if (pendingWrites.has(filePath)) {
    return pendingWrites.get(filePath);
  }

  const pending = (async () => {
    const data = await fetchFreshData();

    await fs.mkdir(path.dirname(filePath), { recursive: true });
    await fs.writeFile(
      filePath,
      JSON.stringify(
        {
          cacheDate: day,
          createdAt: new Date().toISOString(),
          data
        },
        null,
        2
      )
    );
    await removeOldCacheFiles(cacheName, day);

    return { data, cacheStatus: "miss", cacheDate: day };
  })();

  pendingWrites.set(filePath, pending);

  try {
    return await pending;
  } finally {
    pendingWrites.delete(filePath);
  }
}
