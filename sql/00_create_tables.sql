-- 00_create_tables.sql  (PostgreSQL, database fraud_project)
-- Star schema from the project plan (section 4), PostgreSQL version.
-- Run on the fraud_project database. Order matters: dimensions first, then facts (foreign keys).
-- IDs are not auto-generated (no IDENTITY), because they come from the data generated in Python.

-- Customers
CREATE TABLE dim_customer (
    customer_id      INT PRIMARY KEY,
    country          CHAR(2)      NOT NULL,          -- ISO country code, e.g. 'PL'
    age              SMALLINT     CHECK (age BETWEEN 18 AND 100),
    signup_date      DATE         NOT NULL,
    plan             VARCHAR(20),                    -- e.g. standard / plus / premium / metal
    account_age_days INT
);

-- Merchants (shops, services)
CREATE TABLE dim_merchant (
    merchant_id            INT PRIMARY KEY,
    merchant_category      VARCHAR(50) NOT NULL,     -- e.g. online_shopping, travel, crypto
    country                CHAR(2),
    merchant_risk_category VARCHAR(10)               -- low / medium / high
);

-- Customer devices
CREATE TABLE dim_device (
    device_id      INT PRIMARY KEY,
    customer_id    INT NOT NULL REFERENCES dim_customer (customer_id),
    device_country CHAR(2),
    first_seen     TIMESTAMP,
    last_seen      TIMESTAMP
);

-- Exchange rates for converting amounts to EUR
CREATE TABLE dim_fx_rate (
    rate_date DATE,
    currency  CHAR(3),
    eur_rate  NUMERIC(12,6) NOT NULL,
    PRIMARY KEY (rate_date, currency)
);

-- Transactions (fact table)
CREATE TABLE fact_transaction (
    transaction_id BIGINT PRIMARY KEY,
    customer_id    INT           NOT NULL REFERENCES dim_customer (customer_id),
    tx_datetime    TIMESTAMP     NOT NULL,
    amount         NUMERIC(12,2) NOT NULL,
    currency       CHAR(3)       NOT NULL,
    merchant_id    INT           REFERENCES dim_merchant (merchant_id),
    device_id      INT           REFERENCES dim_device (device_id),
    country        CHAR(2),
    is_fraud       BOOLEAN       NOT NULL DEFAULT false   -- T-SQL: BIT NOT NULL DEFAULT 0
);

-- Customer risk: previous_fraud and chargebacks will come from the data,
-- risk_score and risk_level will be calculated later in the scoring step.
CREATE TABLE fact_customer_risk (
    customer_id    INT PRIMARY KEY REFERENCES dim_customer (customer_id),
    previous_fraud BOOLEAN DEFAULT false,
    chargebacks    INT     DEFAULT 0,
    risk_score     NUMERIC(5,2),
    risk_level     VARCHAR(10)
);

-- Check: list of created tables
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
