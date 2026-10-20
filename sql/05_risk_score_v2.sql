-- 05_risk_score_v2.sql  (PostgreSQL, database fraud_project)
-- Tuning the risk score after the false-positive analysis (04_false_positives.sql).
-- Requires: fact_transaction_risk from 03_risk_scoring.sql (re-run this file every time you re-run 03).
-- Adds v2 columns next to the v1 ones in both fact_transaction_risk and fact_customer_risk.
-- Run the whole file at once; the last three queries show "before vs after".
--
-- What we learned in 04_false_positives.sql (threshold 60, plan weights = v1):
--   - fraud / chargeback history was on in 95.8% of false alarms but only in 61% of true alerts,
--     so +30 points was too much: a customer with one old chargeback buying electronics got an alert.
--   - new device was on in 86% of true alerts but only in 10% of false alarms, so +15 was too little.
--
--   Signal                         v1 (plan)   v2 (tuned)
--   amount > 3x customer avg          +20         +20
--   new device                        +15         +25   <- changed
--   new country                       +20         +20
--   5+ tx in 10 min                   +15         +15
--   risky merchant category           +10         +10
--   fraud / chargeback history        +30         +15   <- changed
--   night hour (0-4)                  +10         +10
--   Risk levels stay the same: 0-29 LOW, 30-59 MEDIUM, 60-79 HIGH, 80+ CRITICAL.
--
-- Limitation (worth writing in the README): the weights were chosen by looking at the same data
-- we evaluate on. In a real bank they would be checked on a later, unseen period before going live.
--
-- Differences vs T-SQL:
--   ADD COLUMN IF NOT EXISTS        not in T-SQL; there: IF COL_LENGTH('table', 'col') IS NULL ALTER TABLE ... ADD ...
--   ALTER TABLE ... ADD COLUMN a, ADD COLUMN b   T-SQL: ALTER TABLE ... ADD a ..., b ...  (no COLUMN keyword)


-- ============================================================
-- Part 1. v2 score for every transaction (new columns in fact_transaction_risk)
-- ============================================================
ALTER TABLE fact_transaction_risk
    ADD COLUMN IF NOT EXISTS risk_score_v2 INT,
    ADD COLUMN IF NOT EXISTS risk_level_v2 TEXT;

UPDATE fact_transaction_risk
SET risk_score_v2 =
      CASE WHEN COALESCE(s_amount_3x_avg, false) THEN 20 ELSE 0 END
    + CASE WHEN s_new_device                     THEN 25 ELSE 0 END
    + CASE WHEN s_new_country                    THEN 20 ELSE 0 END
    + CASE WHEN s_5_tx_in_10_min                 THEN 15 ELSE 0 END
    + CASE WHEN s_risky_category                 THEN 10 ELSE 0 END
    + CASE WHEN COALESCE(s_fraud_history, false) THEN 15 ELSE 0 END
    + CASE WHEN s_night_hour                     THEN 10 ELSE 0 END;

UPDATE fact_transaction_risk
SET risk_level_v2 = CASE WHEN risk_score_v2 >= 80 THEN 'CRITICAL'
                         WHEN risk_score_v2 >= 60 THEN 'HIGH'
                         WHEN risk_score_v2 >= 30 THEN 'MEDIUM'
                         ELSE 'LOW' END;


-- ============================================================
-- Part 2. Customer snapshot with the v2 score -> new columns in fact_customer_risk
-- risk_score / risk_level keep the v1 result from 03, risk_score_v2 / risk_level_v2 get v2
-- (the final model for Power BI). Same rule as in 03: highest transaction score
-- in the last 30 days of the period. No activity in 30 days = 0.
-- ============================================================
ALTER TABLE fact_customer_risk
    ADD COLUMN IF NOT EXISTS risk_score_v2 NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS risk_level_v2 VARCHAR(10);

UPDATE fact_customer_risk r
SET risk_score_v2 = COALESCE(c.max_score, 0),
    risk_level_v2 = CASE WHEN COALESCE(c.max_score, 0) >= 80 THEN 'CRITICAL'
                         WHEN COALESCE(c.max_score, 0) >= 60 THEN 'HIGH'
                         WHEN COALESCE(c.max_score, 0) >= 30 THEN 'MEDIUM'
                         ELSE 'LOW' END
FROM (
    SELECT cu.customer_id, MAX(tr.risk_score_v2) AS max_score
    FROM dim_customer cu
    LEFT JOIN fact_transaction_risk tr
           ON tr.customer_id = cu.customer_id
          AND tr.tx_datetime >= TIMESTAMP '2026-07-01' - INTERVAL '30 days'
    GROUP BY cu.customer_id
) c
WHERE c.customer_id = r.customer_id;


-- ============================================================
-- Part 3. Before vs after
-- ============================================================
-- 3a. Threshold tuning: v1 (plan) vs v2 (tuned) side by side
WITH scores AS (
    SELECT v.version, v.score, r.is_fraud
    FROM fact_transaction_risk r
    CROSS JOIN LATERAL (VALUES ('v1 (plan)', r.risk_score),          -- one row per version (T-SQL: CROSS APPLY)
                               ('v2 (tuned)', r.risk_score_v2)) AS v(version, score)
),
matrix AS (
    SELECT
        th.threshold, s.version,
        COUNT(*) FILTER (WHERE s.score >= th.threshold)                     AS flagged,
        COUNT(*) FILTER (WHERE s.score >= th.threshold AND s.is_fraud)      AS tp,
        COUNT(*) FILTER (WHERE s.score >= th.threshold AND NOT s.is_fraud)  AS fp,
        COUNT(*) FILTER (WHERE s.score <  th.threshold AND s.is_fraud)      AS fn,
        COUNT(*) FILTER (WHERE s.score <  th.threshold AND NOT s.is_fraud)  AS tn
    FROM (VALUES (30), (50), (60), (70), (80)) AS th(threshold)
    CROSS JOIN scores s
    GROUP BY th.threshold, s.version
)
SELECT
    threshold,
    version,
    flagged,
    tp AS fraud_detected,
    fp AS false_alarms,
    ROUND(100.0 * tp / NULLIF(tp + fp, 0), 1)            AS precision_pct,
    ROUND(100.0 * tp / NULLIF(tp + fn, 0), 1)            AS recall_pct,
    ROUND(100.0 * fp / NULLIF(fp + tn, 0), 2)            AS false_positive_rate_pct
FROM matrix
ORDER BY threshold, version;

-- 3b. Transactions per risk level: v1 vs v2
SELECT
    v.version,
    v.risk_level,
    COUNT(*)                                            AS transactions,
    COUNT(*) FILTER (WHERE r.is_fraud)                  AS fraud_transactions,
    ROUND(100.0 * AVG(r.is_fraud::int), 2)              AS fraud_rate_pct
FROM fact_transaction_risk r
CROSS JOIN LATERAL (VALUES ('v1 (plan)', r.risk_level),
                           ('v2 (tuned)', r.risk_level_v2)) AS v(version, risk_level)
GROUP BY v.version, v.risk_level
ORDER BY v.version, MIN(CASE v.risk_level WHEN 'LOW' THEN 1 WHEN 'MEDIUM' THEN 2 WHEN 'HIGH' THEN 3 ELSE 4 END);

-- 3c. Customers per risk level: v1 vs v2 (snapshot on 2026-06-30)
SELECT
    v.version,
    v.risk_level,
    COUNT(*)                                            AS customers
FROM fact_customer_risk r
CROSS JOIN LATERAL (VALUES ('v1 (plan)', r.risk_level),
                           ('v2 (tuned)', r.risk_level_v2)) AS v(version, risk_level)
GROUP BY v.version, v.risk_level
ORDER BY v.version, MIN(CASE v.risk_level WHEN 'LOW' THEN 1 WHEN 'MEDIUM' THEN 2 WHEN 'HIGH' THEN 3 ELSE 4 END);
