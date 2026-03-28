-- =====================================================
-- Port Costs Table Migration Script
-- =====================================================
-- This script migrates data from uploader_port_operations_costs
-- to shipping_inputs_port_costs and creates the latest view
-- =====================================================

-- Step 1: Ensure shipping_inputs_port_costs table exists with correct schema
CREATE TABLE IF NOT EXISTS at_lng.shipping_inputs_port_costs (
    id SERIAL PRIMARY KEY,

    -- Location Identifiers
    region VARCHAR(100) NOT NULL,
    country VARCHAR(100) NOT NULL,
    port VARCHAR(200) NOT NULL,
    terminal VARCHAR(200),
    lng_terminal_facility_name VARCHAR(300),

    -- Port Costs by Vessel Type (in USD)
    vessel_type_145k_steam_usd DECIMAL(12,2),
    vessel_type_160k_tfde_usd DECIMAL(12,2),
    vessel_type_174k_megi_usd DECIMAL(12,2),
    vessel_type_qflex_usd DECIMAL(12,2),
    vessel_type_qmax_usd DECIMAL(12,2),

    -- Operation Details
    loading_discharge VARCHAR(50),
    remarks TEXT,

    -- Metadata
    upload_timestamp_utc TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'UTC'),
    uploaded_by VARCHAR(50)
);

-- Step 2: Add uploaded_by column if it doesn't exist (for old schema)
ALTER TABLE at_lng.shipping_inputs_port_costs
ADD COLUMN IF NOT EXISTS uploaded_by VARCHAR(50);

-- Step 3: Migrate data from old table to new table (if old table exists and has data)
DO $$
DECLARE
    old_table_exists INTEGER;
    rows_to_migrate INTEGER;
BEGIN
    -- Check if old table exists
    SELECT COUNT(*) INTO old_table_exists
    FROM information_schema.tables
    WHERE table_schema = 'at_lng' AND table_name = 'uploader_port_operations_costs';

    IF old_table_exists > 0 THEN
        RAISE NOTICE 'Old table uploader_port_operations_costs found. Starting migration...';

        -- Count rows that need migration
        EXECUTE '
            SELECT COUNT(*)
            FROM at_lng.uploader_port_operations_costs old
            WHERE NOT EXISTS (
                SELECT 1 FROM at_lng.shipping_inputs_port_costs new
                WHERE new.region = old.region
                  AND new.country = old.country
                  AND new.port = old.port
                  AND COALESCE(new.terminal, '''') = COALESCE(old.terminal, '''')
                  AND new.upload_timestamp_utc = old.upload_timestamp_utc
            )' INTO rows_to_migrate;

        RAISE NOTICE 'Found % rows to migrate', rows_to_migrate;

        IF rows_to_migrate > 0 THEN
            -- Migrate data
            INSERT INTO at_lng.shipping_inputs_port_costs
                (region, country, port, terminal, lng_terminal_facility_name,
                 vessel_type_145k_steam_usd, vessel_type_160k_tfde_usd,
                 vessel_type_174k_megi_usd, vessel_type_qflex_usd, vessel_type_qmax_usd,
                 loading_discharge, remarks, upload_timestamp_utc, uploaded_by)
            SELECT
                region, country, port, terminal, lng_terminal_facility_name,
                vessel_type_145k_steam_usd, vessel_type_160k_tfde_usd,
                vessel_type_174k_megi_usd, vessel_type_qflex_usd, vessel_type_qmax_usd,
                loading_discharge, remarks, upload_timestamp_utc,
                COALESCE(uploaded_by, 'system_migration')
            FROM at_lng.uploader_port_operations_costs old
            WHERE NOT EXISTS (
                SELECT 1 FROM at_lng.shipping_inputs_port_costs new
                WHERE new.region = old.region
                  AND new.country = old.country
                  AND new.port = old.port
                  AND COALESCE(new.terminal, '') = COALESCE(old.terminal, '')
                  AND new.upload_timestamp_utc = old.upload_timestamp_utc
            );

            RAISE NOTICE 'Successfully migrated % rows', rows_to_migrate;
        ELSE
            RAISE NOTICE 'No new rows to migrate (data already exists)';
        END IF;

        -- Drop old table
        DROP TABLE at_lng.uploader_port_operations_costs CASCADE;
        RAISE NOTICE 'Dropped old table uploader_port_operations_costs';
    ELSE
        RAISE NOTICE 'Old table uploader_port_operations_costs not found. No migration needed.';
    END IF;
END $$;

-- Step 4: Create indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_shipping_port_costs_country
ON at_lng.shipping_inputs_port_costs(country);

CREATE INDEX IF NOT EXISTS idx_shipping_port_costs_port
ON at_lng.shipping_inputs_port_costs(port);

CREATE INDEX IF NOT EXISTS idx_shipping_port_costs_region
ON at_lng.shipping_inputs_port_costs(region);

CREATE INDEX IF NOT EXISTS idx_shipping_port_costs_timestamp
ON at_lng.shipping_inputs_port_costs(upload_timestamp_utc DESC);

-- Composite index for view performance
CREATE INDEX IF NOT EXISTS idx_shipping_port_costs_latest
ON at_lng.shipping_inputs_port_costs(region, country, port, terminal, upload_timestamp_utc DESC);

-- Step 5: Create view for latest port costs
CREATE OR REPLACE VIEW at_lng.shipping_inputs_port_costs_latest AS
SELECT DISTINCT ON (region, country, port, COALESCE(terminal, ''))
    id,
    region,
    country,
    port,
    terminal,
    lng_terminal_facility_name,
    vessel_type_145k_steam_usd,
    vessel_type_160k_tfde_usd,
    vessel_type_174k_megi_usd,
    vessel_type_qflex_usd,
    vessel_type_qmax_usd,
    loading_discharge,
    remarks,
    upload_timestamp_utc,
    uploaded_by
FROM at_lng.shipping_inputs_port_costs
ORDER BY region, country, port, COALESCE(terminal, ''), upload_timestamp_utc DESC;

-- Step 6: Add comments
COMMENT ON TABLE at_lng.shipping_inputs_port_costs IS 'Port operations costs by vessel type for UFC calculations';
COMMENT ON VIEW at_lng.shipping_inputs_port_costs_latest IS 'Latest version of port costs per unique port/terminal';
COMMENT ON COLUMN at_lng.shipping_inputs_port_costs.vessel_type_145k_steam_usd IS 'Port cost for 145k cbm steam vessels (USD)';
COMMENT ON COLUMN at_lng.shipping_inputs_port_costs.vessel_type_160k_tfde_usd IS 'Port cost for 160k cbm TFDE vessels (USD)';
COMMENT ON COLUMN at_lng.shipping_inputs_port_costs.vessel_type_174k_megi_usd IS 'Port cost for 174k cbm MEGI vessels (USD)';
COMMENT ON COLUMN at_lng.shipping_inputs_port_costs.vessel_type_qflex_usd IS 'Port cost for Q-FLEX vessels (USD)';
COMMENT ON COLUMN at_lng.shipping_inputs_port_costs.vessel_type_qmax_usd IS 'Port cost for Q-MAX vessels (USD)';

-- Step 7: Verification queries
DO $$
DECLARE
    table_count INTEGER;
    view_count INTEGER;
    latest_count INTEGER;
BEGIN
    -- Verify new table exists
    SELECT COUNT(*) INTO table_count
    FROM information_schema.tables
    WHERE table_schema = 'at_lng' AND table_name = 'shipping_inputs_port_costs';

    -- Verify view exists
    SELECT COUNT(*) INTO view_count
    FROM information_schema.views
    WHERE table_schema = 'at_lng' AND table_name = 'shipping_inputs_port_costs_latest';

    -- Count rows in view
    EXECUTE 'SELECT COUNT(*) FROM at_lng.shipping_inputs_port_costs_latest' INTO latest_count;

    RAISE NOTICE '';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Migration Complete!';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Table shipping_inputs_port_costs: % (1 = exists)', table_count;
    RAISE NOTICE 'View shipping_inputs_port_costs_latest: % (1 = exists)', view_count;
    RAISE NOTICE 'Total ports in latest view: %', latest_count;
    RAISE NOTICE '========================================';
END $$;
