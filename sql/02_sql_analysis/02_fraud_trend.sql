-- 02_sql_analysis/02_fraud_trend.sql  (PostgreSQL, database fraud_project)
-- Section 8 of the plan: fraud trend over time (month, week, day) and time of day.
-- Run each query separately (select it and run).
-- Differences vs T-SQL:
--   DATE_TRUNC('month', ts)        instead of  DATEFROMPARTS(YEAR(ts), MONTH(ts), 1)  or  DATETRUNC(month, ts) (SQL Server 2022)
--   EXTRACT(HOUR FROM ts)          instead of  DATEPART(hour, ts)
--   AVG(...) OVER (... ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)  works the same as in T-SQL


-- 1. Monthly trend: transactions, frauds, fraud rate and loss in EUR
SELECT
    DATE_TRUNC('month', t.tx_datetime)::date            AS month,
    COUNT(*)                                            AS transactions,
    COUNT(*) FILTER (WHERE t.is_fraud)                  AS fraud_transactions,
    ROUND(100.0 * AVG(t.is_fraud::int), 2)              AS fraud_rate_pct,
    ROUND(SUM(t.amount * fx.eur_rate) FILTER (WHERE t.is_fraud), 0) AS fraud_loss_eur
FROM fact_transaction t
JOIN dim_fx_rate fx ON fx.rate_date = t.tx_datetime::date AND fx.currency = t.currency
GROUP BY 1
ORDER BY 1;


-- 2. Weekly trend (week starts on Monday)
SELECT
    DATE_TRUNC('week', t.tx_datetime)::date             AS week_start,
    COUNT(*)                                            AS transactions,
    COUNT(*) FILTER (WHERE t.is_fraud)                  AS fraud_transactions,
    ROUND(100.0 * AVG(t.is_fraud::int), 2)              AS fraud_rate_pct
FROM fact_transaction t
GROUP BY 1
ORDER BY 1;


-- 3. Daily trend + 7-day moving average (smooths out daily spikes)
WITH daily AS (
    SELECT
        t.tx_datetime::date                             AS day,
        COUNT(*)                                        AS transactions,
        COUNT(*) FILTER (WHERE t.is_fraud)              AS fraud_transactions
    FROM fact_transaction t
    GROUP BY 1
)
SELECT
    day,
    transactions,
    fraud_transactions,
    ROUND(100.0 * fraud_transactions / transactions, 2) AS fraud_rate_pct,
    ROUND(AVG(fraud_transactions) OVER (ORDER BY day
          ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 1) AS fraud_7day_avg
FROM daily
ORDER BY day;


-- 4. Time of day: at what hour is fraud most frequent?
SELECT
    EXTRACT(HOUR FROM t.tx_datetime)::int               AS hour,
    COUNT(*)                                            AS transactions,
    COUNT(*) FILTER (WHERE t.is_fraud)                  AS fraud_transactions,
    ROUND(100.0 * AVG(t.is_fraud::int), 2)              AS fraud_rate_pct
FROM fact_transaction t
GROUP BY 1
ORDER BY 1;
