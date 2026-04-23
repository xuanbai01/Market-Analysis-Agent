-- Create symbols table
CREATE TABLE IF NOT EXISTS symbols (
  symbol VARCHAR(16) PRIMARY KEY,
  name   VARCHAR(128)
);

-- Create news_items table (for later news endpoints)
CREATE TABLE IF NOT EXISTS news_items (
  id     VARCHAR(64) PRIMARY KEY,
  ts     TIMESTAMPTZ DEFAULT now(),
  title  VARCHAR(512) NOT NULL,
  url    VARCHAR(1024) NOT NULL,
  source VARCHAR(64) NOT NULL
);

-- Seed a couple of symbols so /v1/symbols returns data
INSERT INTO symbols(symbol, name)
VALUES ('NVDA', 'NVIDIA Corp'),
       ('SPY', 'SPDR S&P 500 ETF')
ON CONFLICT (symbol) DO NOTHING;
