"""Load the Showdown snapshot into Postgres, atomically and repeatably.

The whole load is one transaction:
  1. record an ingestion run (source, license, commit, retrieved_at),
  2. delete this regulation's existing rows,
  3. COPY the new rows in.
If anything fails, Postgres rolls back and the previous data stays intact.
Readers never see a half-loaded table. Running it twice gives the same result
(idempotent), which is what a scheduled monthly refresh needs.

Delete-and-reload beats row-by-row upserts here: the dataset is small (~20k
rows), and a Pokémon or move *removed* from the game disappears automatically,
where an upsert would leave it behind.

Usage: python -m pokechamp.ingest.load_showdown
"""

import psycopg
from psycopg.types.json import Jsonb

from pokechamp.db import connect
from pokechamp.ingest.snapshot import STAT_KEYS, Snapshot, load_snapshot

# Children before parents, so deletes don't trip foreign keys.
TABLES = ("learnsets", "species", "moves", "abilities", "items", "natures", "type_chart", "formats")


def _copy(cur: psycopg.Cursor, table: str, columns: tuple[str, ...], rows) -> int:
    count = 0
    with cur.copy(f"COPY {table} ({', '.join(columns)}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)
            count += 1
    return count


def load(conn: psycopg.Connection, snap: Snapshot) -> int:
    """Replace all rows for the snapshot's regulation. Returns the ingestion run id."""
    reg = snap.meta.regulation
    with conn.transaction(), conn.cursor() as cur:
        run_id = cur.execute(
            "INSERT INTO ingestion_runs"
            " (source, source_url, source_version, license, regulation, retrieved_at)"
            " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (
                snap.meta.source,
                snap.meta.source_url,
                snap.meta.showdown_commit,
                snap.meta.license,
                reg,
                snap.meta.exported_at,
            ),
        ).fetchone()[0]

        for table in TABLES:
            cur.execute(f"DELETE FROM {table} WHERE regulation = %s", (reg,))

        counts = {
            "formats": _copy(
                cur,
                "formats",
                (
                    "regulation",
                    "id",
                    "name",
                    "game_type",
                    "team_size",
                    "picked_team_size",
                    "level",
                    "sp_total",
                    "sp_max_per_stat",
                    "item_clause",
                    "species_clause",
                    "banned",
                    "run_id",
                ),
                (
                    (
                        reg,
                        f.id,
                        f.name,
                        f.game_type,
                        f.team_size,
                        f.picked_team_size,
                        f.level,
                        f.sp_total,
                        f.sp_max_per_stat,
                        f.item_clause,
                        f.species_clause,
                        f.banned,
                        run_id,
                    )
                    for f in snap.formats
                ),
            ),
            "species": _copy(
                cur,
                "species",
                (
                    "regulation",
                    "id",
                    "name",
                    "num",
                    "base_species",
                    "forme",
                    "types",
                    *STAT_KEYS,
                    "abilities",
                    "weightkg",
                    "battle_only",
                    "required_item",
                    "is_mega",
                    "legal",
                    "illegal_reason",
                    "run_id",
                ),
                (
                    (
                        reg,
                        s.id,
                        s.name,
                        s.num,
                        s.base_species,
                        s.forme,
                        s.types,
                        *(s.base_stats[k] for k in STAT_KEYS),
                        Jsonb(s.abilities),
                        s.weightkg,
                        s.battle_only,
                        s.required_item,
                        s.is_mega,
                        s.legal,
                        s.illegal_reason,
                        run_id,
                    )
                    for s in snap.species
                ),
            ),
            "moves": _copy(
                cur,
                "moves",
                (
                    "regulation",
                    "id",
                    "name",
                    "num",
                    "type",
                    "category",
                    "base_power",
                    "accuracy",
                    "pp",
                    "priority",
                    "target",
                    "flags",
                    "short_desc",
                    "legal",
                    "multihit",
                    "has_secondary",
                    "recoil",
                    "has_crash_damage",
                    "override_offensive_stat",
                    "override_defensive_stat",
                    "ignore_defensive",
                    "will_crit",
                    "run_id",
                ),
                (
                    (
                        reg,
                        m.id,
                        m.name,
                        m.num,
                        m.type,
                        m.category,
                        m.base_power,
                        m.accuracy,
                        m.pp,
                        m.priority,
                        m.target,
                        m.flags,
                        m.short_desc,
                        m.legal,
                        m.multihit,
                        m.has_secondary,
                        m.recoil,
                        m.has_crash_damage,
                        m.override_offensive_stat,
                        m.override_defensive_stat,
                        m.ignore_defensive,
                        m.will_crit,
                        run_id,
                    )
                    for m in snap.moves
                ),
            ),
            "abilities": _copy(
                cur,
                "abilities",
                ("regulation", "id", "name", "short_desc", "legal", "run_id"),
                ((reg, a.id, a.name, a.short_desc, a.legal, run_id) for a in snap.abilities),
            ),
            "items": _copy(
                cur,
                "items",
                ("regulation", "id", "name", "short_desc", "mega_stone", "legal", "run_id"),
                (
                    (
                        reg,
                        i.id,
                        i.name,
                        i.short_desc,
                        Jsonb(i.mega_stone) if i.mega_stone else None,
                        i.legal,
                        run_id,
                    )
                    for i in snap.items
                ),
            ),
            "learnsets": _copy(
                cur,
                "learnsets",
                ("regulation", "species_id", "move_id", "run_id"),
                (
                    (reg, species_id, move_id, run_id)
                    for species_id, move_ids in snap.learnsets.items()
                    for move_id in move_ids
                ),
            ),
            "natures": _copy(
                cur,
                "natures",
                ("regulation", "name", "plus", "minus", "run_id"),
                ((reg, n.name, n.plus, n.minus, run_id) for n in snap.natures),
            ),
            "type_chart": _copy(
                cur,
                "type_chart",
                ("regulation", "attacking", "defending", "multiplier", "run_id"),
                ((reg, t.attacking, t.defending, t.multiplier, run_id) for t in snap.type_chart),
            ),
        }
        cur.execute(
            "UPDATE ingestion_runs SET row_counts = %s WHERE id = %s", (Jsonb(counts), run_id)
        )
    return run_id


def main() -> None:
    snap = load_snapshot()
    with connect() as conn:
        run_id = load(conn, snap)
        counts = conn.execute(
            "SELECT row_counts FROM ingestion_runs WHERE id = %s", (run_id,)
        ).fetchone()[0]
    print(
        f"run {run_id}: loaded Reg {snap.meta.regulation} from showdown@"
        f"{snap.meta.showdown_commit[:10]} -> {counts}"
    )


if __name__ == "__main__":
    main()
