#!/usr/bin/env python3
"""Regenerate the repository inventory in `README.md` (the block between the two markers).

    python tools/readme_inventory.py

Standard library only and no database - it walks this repository and rewrites one block of the
README, which is why the README says "do not edit it by hand" above that block. Line counts are
**text** lines; dependencies and generated or minified files (`assets/tailwind.css`,
`assets/package-lock.json`) are deliberately not counted, because a single minified line says
nothing about anything.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
START = "<!-- inventory:start -->"
END = "<!-- inventory:end -->"

# path -> what it is, in the order the README lists them. Adding a file to the repository means
# adding a line here and re-running this script.
LAYOUT = [
    ("compose.yaml", "the stack: db, broker, dashboard + the optional ingest/seed profiles"),
    ("Dockerfile", "the image of the ingest service and the dashboard (one build, two commands)"),
    ("config.yml", "all settings (NFR-08), no machine-specific value in it"),
    ("requirements.txt", "runtime dependencies - what the image installs"),
    ("main.py", "the Plotly Dash dashboard (the only Python file in the root)"),
    ("components/ui.py", "reusable Tailwind layout components"),
    ("components/charts.py", "the Plotly charts: gravity, temperature, tilt, battery, interval, signal"),
    ("services/db.py", "tiny PostgreSQL helper"),
    ("services/mqtt_service.py", "MQTT -> PostgreSQL: assembles the 7 messages into one row"),
    ("assets/", "Dash-served: the compiled CSS, the javascript, the beer icon and cursors, fonts/"),
    ("sql/schema.sql", "schema, keys and views (incl. `mqtt_broker` for the FR-07 brokers)"),
    ("sql/migrations/", "view and constraint migrations for a database that already exists"),
    ("tools/", "self-tests, the seed loader, the spindel simulator and this generator"),
    ("seed/", "the four recorded batches (FR-21 exports) that `tools/seed.py` loads"),
    ("deploy/mosquitto.conf", "broker configuration (mounted into the broker container)"),
    ("deploy/backup.sh", "pg_dump with 14 days retention (NFR-04)"),
    ("deploy/systemd/", "boot step and nightly backup timer for the Raspberry Pi"),
]

COUNTED = {".py", ".js", ".pcss", ".css", ".sql", ".yml", ".yaml", ".sh", ".conf", ".html", ".json",
           ".md", ".txt", ".service", ".timer"}
SKIP_DIRS = {".git", ".vscode", "node_modules", "__pycache__", ".venv", "backups"}
SKIP_FILES = {"assets/tailwind.css", "assets/package-lock.json"}
NOTE = ("Line counts are text lines; dependencies and generated or minified files "
        "(`assets/tailwind.css`, `assets/package-lock.json`) are not counted.")


def lines(path):
    """Text lines of one file."""
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        return sum(1 for _ in fh)


def count(rel):
    """Text lines of a file, or of the counted files below a directory."""
    path = ROOT / rel
    if path.is_file():
        return lines(path)
    return sum(lines(f) for f in sorted(path.rglob("*"))
               if f.is_file() and f.suffix in COUNTED
               and not any(part in SKIP_DIRS for part in f.relative_to(ROOT).parts)
               and str(f.relative_to(ROOT)) not in SKIP_FILES)


def table():
    """The markdown table and its total."""
    rows = ["| path | lines | what it is |", "| --- | ---: | --- |"]
    total = 0
    for rel, what in LAYOUT:
        n = count(rel)
        total += n
        rows.append(f"| `{rel}` | {n} | {what} |")
    rows.append(f"| **total** | **{total}** | |")
    return "\n".join(rows), total


def main():
    body, total = table()
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    readme.write_text(f"{head}{START}\n\n{body}\n\n{NOTE}\n\n{END}{tail}", encoding="utf-8")
    print(f"README.md: inventory rewritten - {len(LAYOUT)} entries, {total} lines")


if __name__ == "__main__":
    main()
