-- 02_sql_analysis/04_window_functions.sql  (PostgreSQL, database fraud_project)
-- Section 9 of the plan: window functions + risk signals (CASE), which in the next step will add up to the risk score.
-- Run each query separately (select it and run).
-- Differences vs T-SQL:
--   ROW_NUMBER, LAG, AVG/SUM/COUNT OVER (PARTITION BY ... ORDER BY ... ROWS ...)  work the same
--   RANGE BETWEEN INTERVAL '10 minutes' PRECEDING AND CURRENT ROW  - a window by TIME, not by number of rows.
--       SQL Server does not support it (RANGE there works only with UNBOUNDED/CURRENT ROW);
--       in T-SQL you would need a subquery or OUTER APPLY with a time condition.
--   tx_datetime - LAG(tx_datetime)  returns the INTERVAL type; EXTRACT(EPOCH FROM ...) converts it to seconds
--       (in T-SQL: DATEDIFF(second, LAG(tx_datetime) OVER (...), tx_datetime))


-- 1. ROW_NUMBER and LAG: one customer's history step by step
--    (replace customer_id with any customer; 8080 has fraud in their history)
SELECT
    t.customer_id,
    ROW_NUMBER() OVER w                                        AS tx_no,
    t.tx_datetime,
    t.country,
    LAG(t.country) OVER w                                      AS prev_country,
    t.tx_datetime - LAG(t.tx_datetime) OVER w                  AS time_since_prev,
    t.device_id,
    LAG(t.device_id) OVER w                                    AS prev_device,
    t.amount, t.currency, t.is_fraud
FROM fact_transaction t
WHERE t.customer_id = 8080
WINDOW w AS (PARTITION BY t.customer_id ORDER BY t.tx_datetime, t.transaction_id)   -- one window definition, used many times (T-SQL: SQL Server 2022+)
ORDER BY tx_no;


-- 2. Risk signals for every transaction (window functions + CASE)
--    and a check: what is the fraud rate when the signal is on, and when it is off?
WITH tx AS (
    SELECT
        t.transaction_id, t.customer_id, t.tx_datetime, t.country, t.device_id, t.is_fraud,
        m.merchant_category,
        t.amount * fx.eur_rate                                  AS amount_eur
    FROM fact_transaction t
    JOIN dim_merchant m USING (merchant_id)
    JOIN dim_fx_rate fx ON fx.rate_date = t.tx_datetime::date AND fx.currency = t.currency
),
features AS (
    SELECT
        tx.*,
        ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY tx_datetime, transaction_id)  AS tx_no,
        -- customer's historical average: only EARLIER transactions (excluding the current one, so we don't "peek" at the result)
        AVG(amount_eur) OVER (PARTITION BY customer_id ORDER BY tx_datetime, transaction_id
                              ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)             AS hist_avg_eur,
        -- velocity: how many transactions the customer made in the last 10 minutes (including the current one)
        COUNT(*) OVER (PARTITION BY customer_id ORDER BY tx_datetime
                       RANGE BETWEEN INTERVAL '10 minutes' PRECEDING AND CURRENT ROW)       AS tx_last_10_min,
        -- rolling volume: sum of the customer's amounts in the last 24 hours
        SUM(amount_eur) OVER (PARTITION BY customer_id ORDER BY tx_datetime
                              RANGE BETWEEN INTERVAL '24 hours' PRECEDING AND CURRENT ROW)  AS sum_24h_eur,
        -- when the customer first used this device, and when they made their first transaction at all
        MIN(tx_datetime) OVER (PARTITION BY customer_id, device_id)                         AS device_first_use,
        MIN(tx_datetime) OVER (PARTITION BY customer_id)                                    AS customer_first_tx,
        -- customer's first transaction in a given country
        ROW_NUMBER() OVER (PARTITION BY customer_id, country ORDER BY tx_datetime, transaction_id) AS tx_no_in_country
    FROM tx
),
signals AS (
    SELECT
        transaction_id, is_fraud,
        -- signals from section 10 of the plan (1 = on, 0 = off)
        CASE WHEN amount_eur > 3 * hist_avg_eur THEN 1 ELSE 0 END                             AS s_amount_3x_avg,
        -- new device = device first used within the last 24 h (and it is not the customer's first device)
        CASE WHEN device_first_use > customer_first_tx
              AND tx_datetime < device_first_use + INTERVAL '24 hours' THEN 1 ELSE 0 END      AS s_new_device,
        CASE WHEN tx_no > 1 AND tx_no_in_country = 1 THEN 1 ELSE 0 END                       AS s_new_country,
        CASE WHEN tx_last_10_min >= 5 THEN 1 ELSE 0 END                                      AS s_5_tx_in_10_min,
        CASE WHEN merchant_category IN ('crypto', 'gift_cards', 'electronics') THEN 1 ELSE 0 END AS s_risky_category,
        CASE WHEN EXTRACT(HOUR FROM tx_datetime) BETWEEN 0 AND 4 THEN 1 ELSE 0 END           AS s_night_hour
    FROM features
)
-- One row per signal: how many transactions have it, their fraud rate, and what share of all frauds it catches
SELECT signal,
       COUNT(*) FILTER (WHERE is_on = 1)                                             AS tx_with_signal,
       ROUND(100.0 * AVG(is_fraud::int) FILTER (WHERE is_on = 1), 2)                 AS fraud_rate_when_on_pct,
       ROUND(100.0 * AVG(is_fraud::int) FILTER (WHERE is_on = 0), 2)                 AS fraud_rate_when_off_pct,
       ROUND(100.0 * COUNT(*) FILTER (WHERE is_on = 1 AND is_fraud)
                   / COUNT(*) FILTER (WHERE is_fraud), 1)                            AS fraud_caught_pct
FROM signals
CROSS JOIN LATERAL (VALUES                      -- "unpivots" the signal columns into rows (T-SQL: CROSS APPLY (VALUES ...))
    ('amount > 3x customer avg', s_amount_3x_avg),
    ('new device',               s_new_device),
    ('new country',              s_new_country),
    ('5+ tx in 10 min',          s_5_tx_in_10_min),
    ('risky category',           s_risky_category),
    ('night hour (0-4)',         s_night_hour)
) AS v(signal, is_on)
GROUP BY signal
ORDER BY fraud_rate_when_on_pct DESC;
