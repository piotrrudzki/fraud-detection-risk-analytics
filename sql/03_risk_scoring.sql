-- 03_risk_scoring.sql  (PostgreSQL, database fraud_project)
-- Section 10 of the plan: transparent, rule-based risk score.
-- This is NOT a production model: points and thresholds are demo assumptions from the plan.
--
--   Signal                                   Points   Business reason
--   amount > 3x customer's historical avg     +20     unusual spending for this customer
--   new device (first 24 h of a new device)   +15     account takeover often starts on a new phone
--   new country (first tx in this country)    +20     sudden location change
--   5+ transactions in 10 minutes             +15     card testing / draining the account fast
--   risky merchant category                   +10     crypto, gift cards, electronics are easy to cash out
--   fraud / chargeback history                +30     customer with a risky past
--   night hour (00:00-04:59)                  +10     activity when the customer is usually asleep
--
--   risk_level: 0-29 LOW, 30-59 MEDIUM, 60-79 HIGH, 80+ CRITICAL
--
-- The script creates fact_transaction_risk (one row per transaction: signals, score, level)
-- and then fills risk_score / risk_level in fact_customer_risk.
-- Run the whole file at once (it takes a few seconds).
-- Differences vs T-SQL:
--   CREATE TABLE ... AS SELECT          instead of  SELECT ... INTO new_table
--   DROP TABLE IF EXISTS                 works the same (SQL Server 2016+)
--   UPDATE ... FROM ... WHERE            T-SQL also has UPDATE ... FROM, but with a JOIN inside FROM
--   RANGE BETWEEN INTERVAL ... PRECEDING not available in T-SQL (see 04_window_functions.sql)


-- ============================================================
-- Part 1. Score for every transaction -> table fact_transaction_risk
-- ============================================================
DROP TABLE IF EXISTS fact_transaction_risk;

CREATE TABLE fact_transaction_risk AS
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
    -- the same window functions as in 02_sql_analysis/04_window_functions.sql
    SELECT
        tx.*,
        ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY tx_datetime, transaction_id)  AS tx_no,
        AVG(amount_eur) OVER (PARTITION BY customer_id ORDER BY tx_datetime, transaction_id
                              ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)             AS hist_avg_eur,
        COUNT(*) OVER (PARTITION BY customer_id ORDER BY tx_datetime
                       RANGE BETWEEN INTERVAL '10 minutes' PRECEDING AND CURRENT ROW)       AS tx_last_10_min,
        MIN(tx_datetime) OVER (PARTITION BY customer_id, device_id)                         AS device_first_use,
        MIN(tx_datetime) OVER (PARTITION BY customer_id)                                    AS customer_first_tx,
        ROW_NUMBER() OVER (PARTITION BY customer_id, country ORDER BY tx_datetime, transaction_id) AS tx_no_in_country
    FROM tx
),
signals AS (
    SELECT
        f.transaction_id, f.customer_id, f.tx_datetime, f.amount_eur, f.is_fraud,
        (f.amount_eur > 3 * f.hist_avg_eur)                                     AS s_amount_3x_avg,
        (f.device_first_use > f.customer_first_tx
         AND f.tx_datetime < f.device_first_use + INTERVAL '24 hours')          AS s_new_device,
        (f.tx_no > 1 AND f.tx_no_in_country = 1)                                AS s_new_country,
        (f.tx_last_10_min >= 5)                                                 AS s_5_tx_in_10_min,
        (f.merchant_category IN ('crypto', 'gift_cards', 'electronics'))        AS s_risky_category,
        (r.previous_fraud OR r.chargebacks > 0)                                 AS s_fraud_history,
        (EXTRACT(HOUR FROM f.tx_datetime) BETWEEN 0 AND 4)                      AS s_night_hour
    FROM features f
    LEFT JOIN fact_customer_risk r USING (customer_id)
),
scored AS (
    SELECT
        s.*,
        -- COALESCE: a signal that cannot be calculated (e.g. no history for the 1st transaction) = 0 points
          CASE WHEN COALESCE(s_amount_3x_avg,  false) THEN 20 ELSE 0 END
        + CASE WHEN s_new_device                      THEN 15 ELSE 0 END
        + CASE WHEN s_new_country                     THEN 20 ELSE 0 END
        + CASE WHEN s_5_tx_in_10_min                  THEN 15 ELSE 0 END
        + CASE WHEN s_risky_category                  THEN 10 ELSE 0 END
        + CASE WHEN COALESCE(s_fraud_history,  false) THEN 30 ELSE 0 END
        + CASE WHEN s_night_hour                      THEN 10 ELSE 0 END             AS risk_score
    FROM signals s
)
SELECT
    *,
    CASE WHEN risk_score >= 80 THEN 'CRITICAL'
         WHEN risk_score >= 60 THEN 'HIGH'
         WHEN risk_score >= 30 THEN 'MEDIUM'
         ELSE 'LOW' END                                                         AS risk_level
FROM scored;

ALTER TABLE fact_transaction_risk ADD PRIMARY KEY (transaction_id);


-- ============================================================
-- Part 2. Customer snapshot -> risk_score / risk_level in fact_customer_risk
-- Customer score = the highest transaction score in the last 30 days of the period
-- (what an analyst would look at "today", on 2026-06-30). No activity in 30 days = 0.
-- ============================================================
UPDATE fact_customer_risk r
SET risk_score = COALESCE(c.max_score, 0),
    risk_level = CASE WHEN COALESCE(c.max_score, 0) >= 80 THEN 'CRITICAL'
                      WHEN COALESCE(c.max_score, 0) >= 60 THEN 'HIGH'
                      WHEN COALESCE(c.max_score, 0) >= 30 THEN 'MEDIUM'
                      ELSE 'LOW' END
FROM (
    SELECT cu.customer_id, MAX(tr.risk_score) AS max_score
    FROM dim_customer cu
    LEFT JOIN fact_transaction_risk tr
           ON tr.customer_id = cu.customer_id
          AND tr.tx_datetime >= TIMESTAMP '2026-07-01' - INTERVAL '30 days'
    GROUP BY cu.customer_id
) c
WHERE c.customer_id = r.customer_id;


-- ============================================================
-- Part 3. Checks
-- ============================================================
-- 3a. Transactions per risk level and how many of them are really fraud
SELECT
    risk_level,
    COUNT(*)                                            AS transactions,
    COUNT(*) FILTER (WHERE is_fraud)                    AS fraud_transactions,
    ROUND(100.0 * AVG(is_fraud::int), 2)                AS fraud_rate_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE is_fraud)
                / SUM(COUNT(*) FILTER (WHERE is_fraud)) OVER (), 1) AS share_of_all_fraud_pct
FROM fact_transaction_risk
GROUP BY risk_level
ORDER BY MIN(risk_score);

-- 3b. Customers per risk level (snapshot on 2026-06-30)
SELECT
    risk_level,
    COUNT(*)                                            AS customers,
    ROUND(AVG(risk_score), 1)                           AS avg_score
FROM fact_customer_risk
GROUP BY risk_level
ORDER BY MIN(risk_score);
