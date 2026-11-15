# Seed data

Four batches that were actually recorded on the Raspberry Pi during the fermentation phase and
exported from the dashboard as CSV (FR-21). `python tools/seed.py` loads them into the database -
the stack starts **empty** on purpose, and this is what makes the dashboard show something real.

| file | experiment | iSpindel | rows in the file |
| --- | --- | --- | ---: |
| `coco_jambo.csv` | CoCo Jambo | MTB7 | 671 |
| `honig_bier.csv` | Honig Bier | MTB3 | 476 |
| `lemon_pale_lager.csv` | Lemon Pale Lager | MTB1 | 679 |
| `mango_maracuya.csv` | Mango Maracuya Dream | MTB9 | 203 |

These are the **raw** exports, quirks and all:

* The timestamp column has **second** precision, and a transmission that the ingest stored as two
  partial rows (one with the tilt, one with temperature/gravity/battery) therefore shares one
  timestamp. `tools/seed.py` merges such pairs back into a single measurement.
* Every batch ends with the reading taken while the spindel was **lifted out of the fermenter**
  (tilt ~90°, "gravity" ~27 °P, which the calibration polynomial cannot do anything sensible with).
  The loader drops those rows, so the stored batch ends where the fermentation did - Mango Maracuya
  Dream on 31.10. 19:27 UTC, not on the 5th of November when the spindel was taken out.

The loaded counts are therefore a little lower than the table above (671 -> 670, 476 -> 475,
679 -> 672, 203 -> 202), and the experiment's `ended_at` is its last real measurement - the same rule
`end_experiment` follows when a batch is ended from the dashboard.
