-- Structured game facts. Reached by tools via SQL, never by vector search.
--
-- Design notes:
-- * Every fact table has `regulation` in its primary key. We only *serve* the
--   live regulation, but during a switchover (M-C -> M-D) both can briefly
--   coexist, and stale rows are removed with one DELETE ... WHERE regulation.
-- * Provenance (source, license, version, retrieved_at) lives once per load in
--   ingestion_runs; every row points at its run. That keeps rows small and
--   guarantees all rows from one load share identical provenance.
-- * Showdown IDs ("garchompmegaz") are the keys; display names are separate.

CREATE TABLE ingestion_runs (
    id             bigserial PRIMARY KEY,
    source         text        NOT NULL,  -- key in pokechamp.sources.SOURCES
    source_url     text        NOT NULL,
    source_version text        NOT NULL,  -- e.g. Showdown commit SHA
    license        text        NOT NULL,
    regulation     text        NOT NULL,
    retrieved_at   timestamptz NOT NULL,  -- when the data was exported from the source
    loaded_at      timestamptz NOT NULL DEFAULT now(),
    row_counts     jsonb       NOT NULL DEFAULT '{}'
);

CREATE TABLE formats (
    regulation        text     NOT NULL,
    id                text     NOT NULL,
    name              text     NOT NULL,
    game_type         text     NOT NULL CHECK (game_type IN ('doubles', 'singles')),
    team_size         smallint NOT NULL,
    picked_team_size  smallint NOT NULL,
    level             smallint NOT NULL,
    sp_total          smallint NOT NULL,
    sp_max_per_stat   smallint NOT NULL,
    item_clause       boolean  NOT NULL,
    species_clause    boolean  NOT NULL,
    banned            text[]   NOT NULL,
    run_id            bigint   NOT NULL REFERENCES ingestion_runs (id),
    PRIMARY KEY (regulation, id),
    UNIQUE (regulation, game_type)
);

CREATE TABLE species (
    regulation     text         NOT NULL,
    id             text         NOT NULL,
    name           text         NOT NULL,
    num            integer      NOT NULL,
    base_species   text         NOT NULL,
    forme          text,
    types          text[]       NOT NULL CHECK (cardinality(types) BETWEEN 1 AND 2),
    hp             smallint     NOT NULL CHECK (hp  BETWEEN 1 AND 255),
    atk            smallint     NOT NULL CHECK (atk BETWEEN 1 AND 255),
    def            smallint     NOT NULL CHECK (def BETWEEN 1 AND 255),
    spa            smallint     NOT NULL CHECK (spa BETWEEN 1 AND 255),
    spd            smallint     NOT NULL CHECK (spd BETWEEN 1 AND 255),
    spe            smallint     NOT NULL CHECK (spe BETWEEN 1 AND 255),
    abilities      jsonb        NOT NULL,  -- {"0": "Blaze", "H": "Intimidate"}
    weightkg       numeric(6,1) NOT NULL,
    battle_only    boolean      NOT NULL,  -- Megas etc.: can't be written on a team
    required_item  text,
    is_mega        boolean      NOT NULL,
    legal          boolean      NOT NULL,
    illegal_reason text,
    run_id         bigint       NOT NULL REFERENCES ingestion_runs (id),
    PRIMARY KEY (regulation, id),
    -- A row can't be both legal and carry a ban reason, or be illegal without one.
    CHECK (legal = (illegal_reason IS NULL))
);
CREATE INDEX species_name_idx ON species (regulation, lower(name));

CREATE TABLE moves (
    regulation  text     NOT NULL,
    id          text     NOT NULL,
    name        text     NOT NULL,
    num         integer  NOT NULL,
    type        text     NOT NULL,
    category    text     NOT NULL CHECK (category IN ('Physical', 'Special', 'Status')),
    base_power  smallint NOT NULL CHECK (base_power >= 0),
    accuracy    smallint CHECK (accuracy BETWEEN 1 AND 100),  -- NULL = never misses
    pp          smallint NOT NULL CHECK (pp BETWEEN 1 AND 40),
    priority    smallint NOT NULL CHECK (priority BETWEEN -7 AND 5),
    target      text     NOT NULL,
    flags       text[]   NOT NULL,
    short_desc  text,
    legal       boolean  NOT NULL,
    run_id      bigint   NOT NULL REFERENCES ingestion_runs (id),
    PRIMARY KEY (regulation, id)
);

CREATE TABLE abilities (
    regulation text    NOT NULL,
    id         text    NOT NULL,
    name       text    NOT NULL,
    short_desc text,
    legal      boolean NOT NULL,
    run_id     bigint  NOT NULL REFERENCES ingestion_runs (id),
    PRIMARY KEY (regulation, id)
);

CREATE TABLE items (
    regulation text    NOT NULL,
    id         text    NOT NULL,
    name       text    NOT NULL,
    short_desc text,
    mega_stone jsonb,  -- {"Garchomp": "Garchomp-Mega-Z"}
    legal      boolean NOT NULL,
    run_id     bigint  NOT NULL REFERENCES ingestion_runs (id),
    PRIMARY KEY (regulation, id)
);

-- Which team-legal species can learn which legal moves (already validated by
-- Showdown's TeamValidator at export time).
CREATE TABLE learnsets (
    regulation text   NOT NULL,
    species_id text   NOT NULL,
    move_id    text   NOT NULL,
    run_id     bigint NOT NULL REFERENCES ingestion_runs (id),
    PRIMARY KEY (regulation, species_id, move_id),
    FOREIGN KEY (regulation, species_id) REFERENCES species (regulation, id),
    FOREIGN KEY (regulation, move_id)    REFERENCES moves (regulation, id)
);
CREATE INDEX learnsets_move_idx ON learnsets (regulation, move_id);

CREATE TABLE natures (
    regulation text   NOT NULL,
    name       text   NOT NULL,
    plus       text,  -- NULL for neutral natures
    minus      text,
    run_id     bigint NOT NULL REFERENCES ingestion_runs (id),
    PRIMARY KEY (regulation, name),
    CHECK ((plus IS NULL) = (minus IS NULL))
);

CREATE TABLE type_chart (
    regulation text         NOT NULL,
    attacking  text         NOT NULL,
    defending  text         NOT NULL,
    multiplier numeric(2,1) NOT NULL CHECK (multiplier IN (0, 0.5, 1, 2)),
    run_id     bigint       NOT NULL REFERENCES ingestion_runs (id),
    PRIMARY KEY (regulation, attacking, defending)
);
