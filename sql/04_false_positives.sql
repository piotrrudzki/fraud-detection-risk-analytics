-- 04_false_positives.sql  (PostgreSQL, database fraud_project)
-- Sections 12-13 of the plan: confusion matrix, precision / recall / false-positive rate, threshold tuning.
-- Requires: table fact_transaction_risk (run 03_risk_scoring.sql first).
-- Run each query separately (select it and run).
--
--   flagged  = the system raises an alert: risk_score >= threshold
--   TP = flagged and fraud        FP = flagged but OK (false alarm)
--   FN = not flagged but fraud    TN = not flagged and OK
--   precision = TP / (TP + FP)    how many alerts are real fraud
--   recall    = TP / (TP + FN)    how much of all fraud we catch
--   FPR       = FP / (FP + TN)    how many good transactions we bother
--
-- Differences vs T-SQL:
--   COUNT(*) FILTER (WHERE ...)                  instead of  SUM(CASE WHEN ... THEN 1 ELSE 0 END)
--   (VALUES (30), (50), (70)) AS th(threshold)   works in T-SQL too, as a derived table
--   NULLIF(x, 0)                                 the same in T-SQL (avoids division by zero)


-- 1. Confusion matrix for one threshold: alert from HIGH upward (risk_score >= 60)
SELECT
    CASE WHEN risk_score >= 60 THEN 'System: fraud' ELSE 'System: OK' END   AS system_decision,
    COUNT(*) FILTER (WHERE is_fraud)                                        AS reality_fraud,
    COUNT(*) FILTER (WHERE NOT is_fraud)                                    AS reality_ok
FROM fact_transaction_risk
GROUP BY 1
ORDER BY 1 DESC;


-- 2. Threshold tuning: the same metrics for several thresholds side by side
WITH thresholds AS (
    SELECT threshold FROM (VALUES (30), (50), (60), (70), (80)) AS th(threshold)
),
matrix AS (
    SELECT
        th.threshold,
        COUNT(*) FILTER (WHERE r.risk_score >= th.threshold)                        AS flagged,
        COUNT(*) FILTER (WHERE r.risk_score >= th.threshold AND r.is_fraud)         AS tp,
        COUNT(*) FILTER (WHERE r.risk_score >= th.threshold AND NOT r.is_fraud)     AS fp,
        COUNT(*) FILTER (WHERE r.risk_score <  th.threshold AND r.is_fraud)         AS fn,
        COUNT(*) FILTER (WHERE r.risk_score <  th.threshold AND NOT r.is_fraud)     AS tn
    FROM thresholds th
    CROSS JOIN fact_transaction_risk r                   -- every transaction checked against every threshold
    GROUP BY th.threshold
)
SELECT
    threshold,
    flagged,
    tp AS fraud_detected,
    fp AS false_alarms,
    fn AS fraud_missed,
    ROUND(100.0 * tp / NULLIF(tp + fp, 0), 1)            AS precision_pct,
    ROUND(100.0 * tp / NULLIF(tp + fn, 0), 1)            AS recall_pct,
    ROUND(100.0 * fp / NULLIF(fp + tn, 0), 2)            AS false_positive_rate_pct,
    ROUND(1.0 * fp / NULLIF(tp, 0), 1)                   AS false_alarms_per_fraud
FROM matrix
ORDER BY threshold;


-- 3. Which rules generate the most false positives? (threshold 60)
--    For every signal: how often it is on in false alarms vs in correctly caught fraud
WITH alerts AS (
    SELECT *
    FROM fact_transaction_risk
    WHERE risk_score >= 60
)
SELECT
    v.signal,
    COUNT(*) FILTER (WHERE v.is_on AND NOT a.is_fraud)                          AS in_false_alarms,
    ROUND(100.0 * COUNT(*) FILTER (WHERE v.is_on AND NOT a.is_fraud)
                / NULLIF(COUNT(*) FILTER (WHERE NOT a.is_fraud), 0), 1)        AS pct_of_false_alarms,
    COUNT(*) FILTER (WHERE v.is_on AND a.is_fraud)                              AS in_true_alerts,
    ROUND(100.0 * COUNT(*) FILTER (WHERE v.is_on AND a.is_fraud)
                / NULLIF(COUNT(*) FILTER (WHERE a.is_fraud), 0), 1)            AS pct_of_true_alerts
FROM alerts a
CROSS JOIN LATERAL (VALUES                      -- signal columns -> rows (T-SQL: CROSS APPLY (VALUES ...))
    ('amount > 3x customer avg', COALESCE(a.s_amount_3x_avg, false)),
    ('new device',               a.s_new_device),
    ('new country',              a.s_new_country),
    ('5+ tx in 10 min',          a.s_5_tx_in_10_min),
    ('risky category',           a.s_risky_category),
    ('fraud / chargeback history', COALESCE(a.s_fraud_history, false)),
    ('night hour (0-4)',         a.s_night_hour)
) AS v(signal, is_on)
GROUP BY v.signal
ORDER BY in_false_alarms DESC;


-- 4. The most common signal combinations behind false alarms (threshold 60)
SELECT
    CONCAT_WS(' + ',                               -- skips NULLs, the same in T-SQL (SQL Server 2017+)
        CASE WHEN s_amount_3x_avg   THEN 'amount 3x' END,
        CASE WHEN s_new_device      THEN 'new device' END,
        CASE WHEN s_new_country     THEN 'new country' END,
        CASE WHEN s_5_tx_in_10_min  THEN '5+ tx/10min' END,
        CASE WHEN s_risky_category  THEN 'risky category' END,
        CASE WHEN s_fraud_history   THEN 'history' END,
        CASE WHEN s_night_hour      THEN 'night' END)                  AS signals,
    COUNT(*)                                                           AS alerts,
    COUNT(*) FILTER (WHERE NOT is_fraud)                               AS false_alarms,
    ROUND(100.0 * AVG(is_fraud::int), 1)                               AS fraud_rate_pct
FROM fact_transaction_risk
WHERE risk_score >= 60
GROUP BY 1
ORDER BY false_alarms DESC
LIMIT 10;
