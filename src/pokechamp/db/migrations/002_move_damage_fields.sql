-- Move properties the damage calculator needs (phase 2). Defaults let the
-- migration run on an existing database; the next ingest fills real values.
ALTER TABLE moves
    ADD COLUMN multihit                smallint[],              -- {2} or {2,5}; NULL = single hit
    ADD COLUMN has_secondary           boolean NOT NULL DEFAULT false,  -- Sheer Force
    ADD COLUMN recoil                  boolean NOT NULL DEFAULT false,  -- Reckless
    ADD COLUMN has_crash_damage        boolean NOT NULL DEFAULT false,  -- Reckless
    ADD COLUMN override_offensive_stat text,                    -- Body Press: 'def'
    ADD COLUMN override_defensive_stat text,                    -- Psyshock: 'def'
    ADD COLUMN ignore_defensive        boolean NOT NULL DEFAULT false,  -- Sacred Sword
    ADD COLUMN will_crit               boolean NOT NULL DEFAULT false;  -- Wicked Blow
