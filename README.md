ISpindelMonitor
================

A fermentation monitor for a small brewery, running on a Raspberry Pi. An **iSpindel** floats in the
fermenter and publishes tilt, temperature, gravity and battery over **MQTT**; this stack stores every
transmission in **PostgreSQL** and serves a **Plotly Dash** dashboard in the local network - live and
historical curves, batch comparison, CSV export.

    iSpindel --MQTT--> mosquitto :1883 --subscribe--> ingest --INSERT--> PostgreSQL
    (one transmission =                                  |                (one row per
     7 MQTT messages)                                    |                 transmission)
                                                         |
                      browser <-- Dash/gunicorn :8080 <-- SELECT ----------+

Noteworthy:

* **Every setting lives in [`config.yml`](config.yml)** - broker address, port, database path,
  thresholds. Nothing is hard-coded, so a clone runs as it is (NFR-08).
* **`compose.yaml` is the whole deployment.** `db`, `broker` and `dashboard` start on a plain `up`;
  the `ingest` (records a real iSpindel) and `seed` (loads the recorded batches) services sit behind
  profiles.
* **Self-tested.** Three check scripts run inside the dashboard container; there is no Python on the
  host ([Tests](#tests)).
* **No authentication, by design.** The dashboard belongs in the local network and must not be
  published - no port forwarding, no tunnel ([FAQ](#faq)).

What runs
---------

| Service | Image | Reached at | What it is |
| --- | --- | --- | --- |
| `db` | `docker.io/library/postgres:16-alpine` | `127.0.0.1:5433` (loopback only) | storage; applies `sql/schema.sql` on the first start |
| `broker` | `docker.io/library/eclipse-mosquitto:2` | `<host>:1883` | receives the iSpindel (`deploy/mosquitto.conf`) |
| `ingest` | this repository (`Dockerfile`) | - | **`--profile ingest`**: assembles the 7 messages of one transmission into one row |
| `dashboard` | this repository (`Dockerfile`) | `<host>:8080` | Plotly Dash behind gunicorn |
| `seed` | this repository (`Dockerfile`) | - | **`--profile seed`**: one-shot, loads the four recorded batches from `seed/`, exits |

The images are **fully qualified** (`docker.io/library/...`), so Podman never has to guess a registry:
a bare `postgres:16-alpine` needs a short-name alias in the host's `/etc/containers/registries.conf`
and fails on a fresh Raspberry Pi. `ingest` and `dashboard` are the **same image** and differ only in
their `command`, which is why starting the ingest later needs no second build. All of them are
multi-arch: the same `compose.yaml` runs on x86-64 and on the Pi (arm64).

Install
-------

Fresh Raspberry Pi OS to a running dashboard (NFR-08). `<engine>` below is `podman` or `docker`.

1. Flash **Raspberry Pi OS Lite (64-bit)** with Raspberry Pi Imager; in its settings set the
   hostname, the user, the network and enable SSH.
2. `ssh <user>@<hostname>`
3. `sudo apt update && sudo apt full-upgrade -y && sudo apt install -y git podman podman-compose`
4. Clone it, start it, install the two systemd units (`/srv/ispindel` is the path they expect):

```bash
sudo mkdir -p /srv && sudo git clone https://github.com/osmast/ISpindelMonitor /srv/ispindel
cd /srv/ispindel && sudo podman compose up -d --build

sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now ispindel ispindel-backup.timer
```

The dashboard is then at `http://<hostname>:8080`; PostgreSQL creates the schema on the first start.
The first build takes a minute or two.

Anywhere else (`macOS`, Linux, Windows) the only prerequisite is a container engine with Compose:

| Machine | Install |
| --- | --- |
| Raspberry Pi / Debian / Ubuntu | `sudo apt install podman podman-compose` |
| macOS | `brew install podman && podman machine init && podman machine start` (or Docker Desktop) |
| Windows | `winget install Docker.DockerDesktop` (or Podman Desktop) with the **WSL 2** backend |
| check | `<engine> compose version` |

```bash
git clone https://github.com/osmast/ISpindelMonitor
cd ISpindelMonitor && podman compose up -d --build         # docker compose works the same
```

### Point an iSpindel at it

`up` starts the database, the broker and the dashboard - **not** the ingest, the container that turns
the iSpindel's seven messages into one row. Start it when a real iSpindel should be recorded:

```bash
<engine> compose --profile ingest up -d ingest      # `up -d ingest` alone works too
```

The profile has to be repeated for **every** command that addresses that service (`ps`, `logs`,
`restart`, `exec`, `down`) - without it the provider does not see the service at all
(`missing services [ingest]`). Then set the iSpindel's MQTT server to this machine's LAN address,
port `1883`:

| OS | The LAN address |
| --- | --- |
| macOS | `ipconfig getifaddr en0` |
| Linux / Raspberry Pi | `hostname -I` |
| Windows | `ipconfig` (IPv4 of the active adapter) |

Every transmission of that iSpindel is then stored and shown live. `--profile ingest run --rm ingest`
is the same container in the foreground (Ctrl-C stops it), and stopping the stack **with** the profile
stops the ingest too - a plain `<engine> compose down` leaves it running.

### Other iSpindels in use (FR-07)

Each participant runs **their own** broker, so one broker is rarely enough. The **MQTT brokers**
button at the bottom left of the *Devices* tab adds one (label, host, port, topic prefix, optional
user/password); the list shows for each what it delivered and what it does right now - *delivering*,
*connected, no data yet*, *silent since ...* or the connection error. A running ingest picks a new
broker up within `ingest.broker_refresh_seconds` (10 s), no restart.

* The broker of `config.yml` is the first row and is **not** editable there - it stays in the file
  (NFR-08). The added brokers are data (the `mqtt_broker` table).
* Two participants may give their iSpindel the same name: it is unique **per broker**, and the
  Devices tab names the **broker address** of every iSpindel (for the own broker: the LAN address an
  iSpindel has to publish to).
* An iSpindel should publish to **one** configured broker - one that publishes to two is recorded
  twice, because those are two independent sources.
* A broker that wants a login answers `Not authorized` and the row says so; a host that is down shows
  *not connected after 60 s - is the broker reachable?*. The state text is the tooltip, the chip
  shows the reason only.
* To test a broker by hand, from the Pi: the broker container brings the client tools along.

  ```bash
  podman exec ispindel_broker_1 mosquitto_sub -h <broker> -p 1883 -u '<user>' -P '<pass>' \
      -t 'ispindel/#' -v -W 15
  ```

### Seed it with the recorded batches

The dashboard starts **empty** on purpose - a fresh stack shows the "point an iSpindel at it" hint
instead of dummy data. To fill it with the four batches that were actually recorded during the
fermentation phase, start the stack with the `seed` profile - it adds a one-shot container that loads
[`seed/*.csv`](seed/) and exits:

```bash
<engine> compose --profile seed up -d --build
<engine> compose exec -T dashboard python tools/seed.py     # the same on a running stack
```

`tools/seed.py` is **idempotent**: what is already in the database is left alone, so running it twice
(and on a stack that already holds data) is safe. It drops the reading taken while a spindel was
lifted out of the fermenter and merges transmissions the export split into two rows - see
[`seed/README.md`](seed/README.md). To get back to an empty database, remove the volume:
`<engine> compose down -v`.

Configure
---------

All settings live in **[`config.yml`](config.yml)** - never in the code (NFR-08). It is committed and
carries no machine-specific value, so nothing has to be rewritten on another machine.

| Setting | Meaning |
| --- | --- |
| `database.dsn` | PostgreSQL connection string - the `db` service of the stack |
| `mqtt.host` / `mqtt.port` / `mqtt.client_id` / `mqtt.topic_prefix` | broker address (the `broker` service), unique client id, `ispindel` topic prefix |
| `ingest.burst_seconds` / `gravity_unit` / `log_messages` | burst fallback, device gravity unit (`P`/`SG`), verbose logging |
| `ingest.broker_refresh_seconds` | FR-07: how often the ingest re-reads the broker list (0 = only at startup) |
| `dashboard.refresh_ms` / `live_ms` | chart refresh (FR-14), countdown tick |
| `dashboard.battery_*_v` | battery gauge limits and the FR-19 warning threshold |
| `dashboard.expected_attenuation` / `target_temp_c` | FR-20 targets (final gravity, ABV estimate, temperature window per style) |
| `dashboard.timezone` | display time zone (NFR-09; stored in UTC) |

`compose.yaml` sets no setting of its own. The two host ports move without editing anything, and a
local **`.env`** makes that permanent (Compose reads it; `.gitignore` keeps it out of the repository):

```bash
ISPINDEL_HTTP_PORT=8090 ISPINDEL_PG_PORT=5434 podman compose up -d
ISPINDEL_HTTP_PORT=8081        # as a line in .env, e.g. because 8080 is taken on this machine
```

`ISPINDEL_CONFIG=/path/to/other.yml` points a component at a completely different file - that is how
to run the app **outside** the stack (a host-side `tools/` run, a second database).

Everyday commands
-----------------

| What | Command |
| --- | --- |
| start / update after a code change | `<engine> compose up -d --build` |
| stop (the `pgdata` volume - the data - survives) | `<engine> compose down` |
| follow the logs (Ctrl-C leaves them running) | `<engine> compose logs -f --tail 50` |
| what runs (the ingest appears only once started) | `<engine> compose ps` |
| start the ingest - records a real iSpindel | `<engine> compose --profile ingest up -d ingest` |
| stop the stack incl. the ingest | `<engine> compose --profile ingest down` |
| add / pause / delete another broker (FR-07) | the **MQTT brokers** button, *Devices* tab - no command |
| delete an iSpindel with its measurements and experiments (FR-12) | the **trash icon** of its row in *Devices* (asks first) |
| is the database ready? | `<engine> compose exec -T db pg_isready -U ispindel -d ispindel` |
| the three self-tests | `<engine> compose exec -T dashboard python tools/check_requirements.py` etc. |
| a psql prompt / a shell in the container | `<engine> compose exec db psql -U ispindel -d ispindel` |
| development (Dash hot reload, writes to the source tree) | `ISPINDEL_DASHBOARD_CMD="python main.py" <engine> compose up -d --build` |

Export file (CSV) - FR-21 / FR-22
---------------------------------

One row per measurement, comma-separated, header row, decimal point.

| Column | Meaning | Unit / format |
| --- | --- | --- |
| `experiment` | experiment name | text |
| `ispindel` | iSpindel name | text |
| `timestamp_utc` | time of the measurement | ISO 8601, UTC (`2026-10-29 17:54:24Z`) |
| `timestamp_local` | the same time in `Europe/Zurich` | `2026-10-29 18:54:24` |
| `tilt_deg` | tilt angle | ° |
| `temperature_c` | beer temperature | °C |
| `gravity_plato` | gravity | °P |
| `battery_v` | battery voltage | V |
| `interval_s` | transmission interval | s |
| `rssi_dbm` | Wi-Fi signal strength | dBm |

The **csv icon** of an experiment row (FR-21) writes that one experiment as `<experiment>.csv`;
**Export selected** (FR-22) writes every experiment in the chart over the selected time range into one
file (`experiments.csv`). Both use exactly the columns above. In Excel with Swiss settings, open via
**Data > From Text/CSV** with delimiter **comma** and decimal point.

Backup and restore
------------------

`deploy/backup.sh` writes a `pg_dump -Fc` into `deploy/backups/`, verifies it is not empty and keeps
14 days (NFR-04). On the Pi the `ispindel-backup.timer` runs it nightly at 03:30 into
`/var/backups/ispindel`:

```bash
bash deploy/backup.sh                                          # Linux, macOS, Raspberry Pi
```

```powershell
# `cmd /c` keeps the bytes intact (PowerShell's `>` would write UTF-16 and corrupt the dump)
cmd /c "mkdir deploy\backups 2>nul & docker compose exec -T db pg_dump -U ispindel -Fc -d ispindel > deploy\backups\ispindel.dump"
```

`pg_restore` reads the custom format back; `--clean --if-exists` drops the current objects first, so
the stack may keep running:

```bash
podman compose exec -T db pg_restore -U ispindel -d ispindel --clean --if-exists < deploy/backups/ispindel-<stamp>.dump
```

The `pgdata` volume keeps the measurements across `down`, a rebuild and a reboot (NFR-03).

### Coming from the old bare-metal installation

The first installation used apt `mosquitto`/`postgresql` and the units `ispindel-ingest` /
`ispindel-dashboard`, which hold `1883` and `8080` - the containers then die with
`bind: address already in use`. Stop and disable them once, then start the stack again:

```bash
sudo systemctl disable --now ispindel-ingest ispindel-dashboard mosquitto
cd /srv/ispindel && podman compose --profile ingest down && podman compose up -d --build
```

`postgresql.service` **stays** - it holds the fermentation data on `5432`, while the database of the
stack starts empty (`127.0.0.1:5433`). Copy the rows over (`--data-only`, the schema already exists):

```bash
PGPASSWORD=ispindel pg_dump -h 127.0.0.1 -p 5432 -U ispindel --data-only --inserts ispindel > /tmp/old-data.sql
podman compose exec -T db psql -U ispindel -d ispindel < /tmp/old-data.sql
```

Tests
-----

The checks run **inside the dashboard container** - same code, same config, the database of the stack
- so no local Python is needed:

```bash
<engine> compose exec -T dashboard python tools/check_requirements.py
<engine> compose exec -T dashboard python tools/ui_test.py
<engine> compose exec -T dashboard python tools/fr19_test.py
```

| Script | Checks |
| --- | --- |
| `tools/check_requirements.py` | the requirements that need no hardware, plus the pure functions (derived values, ranges, gaps, export) |
| `tools/ui_test.py` | the experiment dialog and the table row actions |
| `tools/fr19_test.py` | the status indication (healthy / stale / low battery) |

They create only `zz_*` rows and clean up after themselves. `tools/fake_spindel.py` speaks the
iSpindel protocol (7 MQTT topics) without hardware.

Development
-----------

```bash
cd assets && npm ci && npm run css        # Tailwind build -> assets/tailwind.css
python -m venv .venv && .venv/bin/pip install -r requirements.txt   # only to run tools/ on the host
```

The UI is styled with **Tailwind v4**: `assets/input.pcss` is the source, `assets/tailwind.css` the
committed build artefact served statically. **A class added to the Python code does nothing until
`cd assets && npm run css` is run** - and every class string has to be written out in full inside a
`className`/`extra` argument, because Tailwind compiles from the raw file text.

Troubleshooting
---------------

| Symptom | Check |
| --- | --- |
| dashboard not reachable | `<engine> compose ps`, then `<engine> compose logs dashboard` |
| no rows in the dashboard | is the ingest running? `<engine> compose --profile ingest up -d ingest` |
| a broker stays at *no data yet* | nothing was stored from it yet; the ingest must run (it closes its listeners otherwise), then read the row - *Not authorized* means the broker wants a user/password |
| `missing services [ingest]` / `no such service: ingest` | the ingest sits behind a profile: give **that** command the profile too |
| no measurements arrive | `<engine> compose --profile ingest logs ingest`, `<engine> compose logs broker` |
| ingest stores nothing | `<engine> compose exec -T db pg_isready -U ispindel -d ispindel` |
| stale UI after a class change | `cd assets && npm run css`, then `<engine> compose up -d --build` (the CSS is baked into the image) |
| changed `compose.yaml`, weird behaviour | `<engine> compose down && <engine> compose up -d` (a changed port or volume needs a recreate) |
| `bind: address already in use` for `1883`/`8080` | something else listens there - an old bare-metal installation or a second stack; the dashboard port alone moves with `ISPINDEL_HTTP_PORT` |
| `short-name "postgres:16-alpine" did not resolve to an alias` (Podman) | the clone predates the fully qualified image names - `git pull` |
| `crun: executable file '${ISPINDEL_DASHBOARD_CMD:-gunicorn' not found in $PATH` (Podman) | podman-compose cannot expand `${VAR:-default}` inside `command:` - `git pull`, then `<engine> compose up -d` |
| "no container with ID or name" (Podman) | never remove containers by hand - always `compose down` |

FAQ
---

#### Why containers on a Raspberry Pi?

One `compose.yaml` runs the same system on the Pi, a laptop and a CI box, with no host-side Python,
PostgreSQL or mosquitto to install and no version drift between the three of them. The Pi only needs
a container engine; the whole stack is three containers plus an optional fourth (NFR-01).

#### Why PostgreSQL and not SQLite or InfluxDB?

The data is relational by nature - devices, experiments, measurements - and the interesting
constraints are relational too: `experiment.name` is unique (FR-02), and an `EXCLUDE USING gist`
constraint guarantees that one iSpindel can never be in two experiments at once (FR-03/FR-09).
`timestamptz` stores UTC and the dashboard converts for display (NFR-09). SQLite would work for one
Pi but loses that; InfluxDB optimises for volume we do not have. The concept document justifies the
rest.

#### Where does the data live, and what happens on a reboot?

In the named volume `pgdata` (NFR-04). `compose down` and a rebuild keep it. `deploy/backup.sh`
dumps it nightly on the Pi (NFR-04), and `ispindel.service` brings the stack - including the ingest -
back up after a power failure (NFR-03) and waits for `time-sync.target`, because the Pi has no
real-time clock and every stored time comes from its clock.

#### Why is the dashboard not password-protected?

The specification puts authentication out of scope and requires the dashboard to stay in the local
network (`http://hostname:port`, NFR-02). It is served on all interfaces because that is what the LAN
needs - so **do not** forward the port or put a tunnel in front of it. The database binds to
`127.0.0.1` only.

#### Why is the ingest behind a profile instead of starting with everything else?

Two of the three containers are useful without any hardware: the dashboard shows history, and the
`seed` profile fills it with the recorded batches. Only a real iSpindel needs the ingest, so `up` without
a profile stays light. The cost is that the profile has to be repeated on commands for that service
([Troubleshooting](#troubleshooting)) - and that `ispindel.service` passes it explicitly, so the Pi
records again after a power cut.

#### The iSpindel reports ~27 °P and the chart jumps at the end. Is that a bug?

No - that is the device being lifted out of the fermenter: on its side the tilt goes to ~90° and the
polynomial returns nonsense. The stack stores it faithfully (`gravity_raw` and the unit are kept next
to the converted value, FR-08), and the dashboard breaks the line wherever a device was silent for
more than three transmission intervals, the same rule FR-19 uses to call a device stale - so a
multi-day hole does not read as a smooth fermentation.

#### What do the numbers on a batch card mean?

They are derived from the experiment's original gravity and the newest measurement (FR-20): target
final gravity from `dashboard.expected_attenuation`, the gravity rate over the last 24 h, apparent
attenuation and ABV, plus the temperature deviation from the style's window in
`dashboard.target_temp_c`. The formulas are written out in the concept document; a missing input shows
`-` rather than a guess.

#### Why is `assets/tailwind.css` committed?

The image is built from an explicit `COPY` allowlist, so the browser-served CSS has to exist in the
repository. `assets/input.pcss` is the source and `npm run css` the build step
([Development](#development)) - the same shape stb uses for its generated `README.md`.

#### Why do you list lines of code, when that is a terrible metric?

To give an idea of where the weight of the repository sits - the same courtesy as the stb README, and
with the same caveat: it says nothing about quality, only about how much there is.

#### Why is the pointer a glass of beer?

Because it is a brewery dashboard and nothing in the specification forbids it. It is one static CSS
cursor image guarded by `pointer: fine` (NFR-06); a touch device keeps its normal pointer. Decoration
names no requirement id in the code.

Repository
----------

<!-- The table below is generated by `python tools/readme_inventory.py` - do not edit it by hand. -->

<!-- inventory:start -->

| path | lines | what it is |
| --- | ---: | --- |
| `compose.yaml` | 146 | the stack: db, broker, dashboard + the optional ingest/seed profiles |
| `Dockerfile` | 34 | the image of the ingest service and the dashboard (one build, two commands) |
| `config.yml` | 43 | all settings (NFR-08), no machine-specific value in it |
| `requirements.txt` | 13 | runtime dependencies - what the image installs |
| `main.py` | 2208 | the Plotly Dash dashboard (the only Python file in the root) |
| `components/ui.py` | 172 | reusable Tailwind layout components |
| `components/charts.py` | 163 | the Plotly charts: gravity, temperature, tilt, battery, interval, signal |
| `services/db.py` | 45 | tiny PostgreSQL helper |
| `services/mqtt_service.py` | 428 | MQTT -> PostgreSQL: assembles the 7 messages into one row |
| `assets/` | 929 | Dash-served: the compiled CSS, the javascript, the beer icon and cursors, fonts/ |
| `sql/schema.sql` | 133 | schema, keys and views (incl. `mqtt_broker` for the FR-07 brokers) |
| `sql/migrations/` | 102 | view and constraint migrations for a database that already exists |
| `tools/` | 1898 | self-tests, the seed loader, the spindel simulator and this generator |
| `seed/` | 26 | the four recorded batches (FR-21 exports) that `tools/seed.py` loads |
| `deploy/mosquitto.conf` | 9 | broker configuration (mounted into the broker container) |
| `deploy/backup.sh` | 39 | pg_dump with 14 days retention (NFR-04) |
| `deploy/systemd/` | 51 | boot step and nightly backup timer for the Raspberry Pi |
| **total** | **6439** | |

Line counts are text lines; dependencies and generated or minified files (`assets/tailwind.css`, `assets/package-lock.json`) are not counted.

<!-- inventory:end -->

The two PDFs in the root are documents rather than code: `Project_Guidlines.pdf` is the assignment
specification and `D1_Concept_iSpindel_Steiner_Haedener.pdf` is the submitted concept (D1).

Licence
-------

**Attribution-NonCommercial** - see [`LICENSE`](LICENSE). Use it, modify it and share it free of
charge as a private person or in teaching and research at a public university, as long as you give
credit:

```text
Fermentation Monitoring System (iSpindel)
Oskar Steiner, Anja Hädener - ZHAW Digital Food Processing HS26
https://github.com/osmast/ISpindelMonitor
```

and add that reference - with the version you used - to anything you publish with it. Commercial use
needs a paid licence from the authors. This is deliberately **not** an open source licence.

Third-party material keeps its own licence: the IBM XGA-AI fonts are **CC BY-SA 4.0** by VileR
(`assets/fonts/LICENSE-oldschool-pc-font-pack.txt` - that one *does* require attribution), and the
measurements in [`seed/`](seed/) were recorded by several participants of the module.

The beer tab icon (`assets/favicon-beer.svg`), the beer-glass cursor (`assets/cursor-beer.svg` +
`.png`) and the bubble trail (`assets/bubbles.js` + the plain-CSS part of `assets/input.pcss`) are
made for this project and are covered by the licence above.

The comments in the code name the requirement they implement (`FR-01` ... `FR-22`, `NFR-01` ...
`NFR-09`), which come from the assignment specification; the code is the traceability.
