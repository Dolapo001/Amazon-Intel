-- ClickHouse DDL for BSR time-series storage
-- Run once during initial setup: clickhouse-client < clickhouse_schema.sql

CREATE DATABASE IF NOT EXISTS amazon_intel;

USE amazon_intel;

-- ── BSR time-series ──────────────────────────────────────────────────────────
-- High-resolution ingestion from Keepa (one row per data point ~hourly cadence)
-- MergeTree partitioned by month for efficient range scans.

CREATE TABLE IF NOT EXISTS bsr_timeseries
(
    asin        String,
    timestamp   DateTime,
    bsr_rank    UInt32,
    price       Nullable(UInt32),   -- cents
    rating      Nullable(Float32),  -- ×10 in Keepa → divide on insert
    review_count Nullable(UInt32),
    ingested_at DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (asin, timestamp)
TTL timestamp + INTERVAL 3 YEAR
SETTINGS index_granularity = 8192;

-- ── Materialised view: daily roll-ups (for fast YoY queries) ─────────────────
CREATE MATERIALIZED VIEW IF NOT EXISTS bsr_daily_mv
ENGINE = AggregatingMergeTree()
PARTITION BY toYYYYMM(day)
ORDER BY (asin, day)
AS SELECT
    asin,
    toDate(timestamp)          AS day,
    minState(bsr_rank)         AS min_bsr_state,
    maxState(bsr_rank)         AS max_bsr_state,
    avgState(bsr_rank)         AS avg_bsr_state,
    avgState(price)            AS avg_price_state
FROM bsr_timeseries
GROUP BY asin, day;

-- Query example: average daily BSR for an ASIN over last 365 days
-- SELECT
--     day,
--     avgMerge(avg_bsr_state) AS avg_bsr
-- FROM bsr_daily_mv
-- WHERE asin = 'B09XYZ1234'
--   AND day >= today() - INTERVAL 365 DAY
-- GROUP BY day
-- ORDER BY day;
