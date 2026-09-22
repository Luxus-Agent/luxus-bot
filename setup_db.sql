-- Run this as the postgres superuser if you need to recreate the DB from scratch.
-- Option A: pgAdmin → Query Tool → paste and run
-- Option B: psql -U postgres -f setup_db.sql

-- 1. Create the application user
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'luxus') THEN
    CREATE USER luxus WITH PASSWORD 'dhanush';
  END IF;
END
$$;

-- 2. Create the database
-- CREATE DATABASE luxus OWNER luxus;

-- 3. Grant privileges
GRANT ALL PRIVILEGES ON DATABASE luxus TO luxus;

\c luxus
GRANT ALL ON SCHEMA public TO luxus;
GRANT ALL ON ALL TABLES IN SCHEMA public TO luxus;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO luxus;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO luxus;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO luxus;
