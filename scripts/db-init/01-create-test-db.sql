-- Runs once, when the Postgres volume is first created
-- (docker-entrypoint-initdb.d). The app uses `marketdb` (POSTGRES_DB);
-- the test suite drops and recreates tables in this separate database,
-- so it must never point at marketdb.
CREATE DATABASE test_db;
