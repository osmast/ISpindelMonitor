#!/usr/bin/env python3
"""Load the recorded fermentation exports in `seed/` into the database.

    <engine> compose --profile seed up -d --build              # one-shot, on a fresh volume
    <engine> compose exec -T dashboard python tools/seed.py    # on a running stack

The stack starts **empty**; this fills it with the four batches that were actually recorded during
the fermentation phase, so the dashboard has something real to show. It is **idempotent** - a
device, experiment or measurement that is already there is left alone - which means it is safe on a
database that already holds data, and safe to run twice.

Two quirks of the export are handled here and documented in `seed/README.md`: one transmission can
appear as two rows that share a timestamp (merged), and every batch ends with the reading taken while
the spindel was out of the fermenter (dropped - see `DEVICE_OUT_TILT`).
"""
import csv
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import services.db as db                                             # noqa: E402

DATA = ROOT / "seed"
# Above this tilt the spindel is out of the wort (it floats on its side in the fermenter). The
# polynomial then returns nonsense - ~27 °P - so those readings are not part of the fermentation.
DEVICE_OUT_TILT = 80
FIELDS = ("tilt_deg", "temperature_c", "gravity_plato", "battery_v", "interval_s", "rssi_dbm")


def stamp(value):
    """The export's `2026-10-29 17:54:24Z` -> a timestamp PostgreSQL reads as UTC."""
    return value.replace(" ", "T").replace("Z", "+00:00")


def rows_of(path):
    """One export -> (experiment, ispindel, measurements, skipped device-out rows).

    A measurement is `(recorded_at, tilt, temperature, gravity, battery, interval, rssi)`. Rows that
    share a timestamp are merged - the export has second precision, so a transmission stored as two
    partial rows ends up on the same second.
    """
    with path.open(newline="", encoding="utf-8") as fh:
        raw = list(csv.DictReader(fh))
    merged, order = {}, []
    for row in raw:
        if row["timestamp_utc"] not in merged:
            merged[row["timestamp_utc"]] = {}
            order.append(row["timestamp_utc"])
        for field in FIELDS:
            if row[field] and field not in merged[row["timestamp_utc"]]:
                merged[row["timestamp_utc"]][field] = row[field]
    measurements, skipped = [], 0
    for key in order:
        row = merged[key]
        if row.get("tilt_deg") and float(row["tilt_deg"]) > DEVICE_OUT_TILT:
            skipped += 1
            continue
        measurements.append((stamp(key),
                             *(float(row[f]) if row.get(f) else None for f in FIELDS)))
    return raw[0]["experiment"], raw[0]["ispindel"], measurements, skipped


def load(path):
    """Load one export. Returns (experiment, ispindel, measurements, skipped, added)."""
    experiment, ispindel, measurements, skipped = rows_of(path)
    count = """SELECT count(*) FROM measurement m JOIN experiment e ON e.id = m.experiment_id
               WHERE e.name = %s"""
    with psycopg.connect(db.CFG["database"]["dsn"], autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO device (mqtt_name, display_name) VALUES (%s, %s)
                       ON CONFLICT ((COALESCE(broker_id, 0)), mqtt_name) DO NOTHING""",
                    (ispindel, ispindel))
        # FR-04: the batch is over when the iSpindel stopped reporting - the same rule the dashboard
        # follows when a user ends an experiment.
        cur.execute("""INSERT INTO experiment (name, device_id, started_at, ended_at)
                       SELECT %s, id, %s, %s FROM device WHERE mqtt_name = %s
                       ON CONFLICT (name) DO NOTHING""",
                    (experiment, measurements[0][0], measurements[-1][0], ispindel))
        cur.execute(count, (experiment,))
        before = cur.fetchone()[0]
        # FR-11: one row per transmission - a timestamp that is already stored is not written again
        cur.executemany("""INSERT INTO measurement
                               (device_id, experiment_id, recorded_at, tilt_deg, temp_c,
                                gravity_plato, battery_v, interval_s, rssi_dbm)
                           SELECT d.id, e.id, %s, %s, %s, %s, %s, %s, %s
                           FROM device d, experiment e
                           WHERE d.mqtt_name = %s AND e.name = %s
                           ON CONFLICT (device_id, recorded_at) DO NOTHING""",
                        [(recorded, *values, ispindel, experiment)
                         for recorded, *values in measurements])
        cur.execute(count, (experiment,))
        added = cur.fetchone()[0] - before
    return experiment, ispindel, len(measurements), skipped, added


def main():
    files = sorted(DATA.glob("*.csv"))
    if not files:
        print(f"no exports in {DATA.relative_to(ROOT)}/ - nothing to load")
        return
    print(f"loading {len(files)} recorded batches from {DATA.relative_to(ROOT)}/")
    for path in files:
        experiment, ispindel, measurements, skipped, added = load(path)
        note = f"  ({skipped} device-out row(s) skipped)" if skipped else ""
        print(f"  {experiment:22} {ispindel:5} {added:4} new / {measurements:4} measurements{note}")
    print("done - reload the dashboard page")


if __name__ == "__main__":
    main()
