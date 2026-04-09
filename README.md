# autocat3

**autocat3** is a Python/CherryPy application that serves dynamic content for [Project Gutenberg](https://www.gutenberg.org). It handles search, catalog browsing, and OPDS feed generation.

This fork adds a materialized-view-based search engine (`mv_search/`) and an OPDS 2.0 JSON feed server (`OPDS2.py`).

---

## What's New

### Materialized View (`mv_books_dc`)

The OPDS feed need all of a book's metadata at once: title, authors, subjects, bookshelves, formats, etc. Fetching this across the many-to-many tables adds up in time. The materialized view `mv_books_dc` pre-computes all those joins into a single cached table so queries return in under 0.5s most times.

**You must create this view before running the updated autocat.** The SQL is here:

https://github.com/zachjesus/pg-db-mv/blob/main/15_materialized_view.sql

### Search Engine (`mv_search/`)

The `mv_search/` directory contains a new search module that queries `mv_books_dc` directly. It supports full-text search (GIN/tsvector), fuzzy search (GiST/trigram), filtering, sorting, and pagination. Results can be output in PG or OPDS 2.0 format via crosswalk transforms.

### OPDS 2.0 Feed (`OPDS2.py`)

A full OPDS 2.0 JSON feed mounted at `/opds`. Supports search, faceted browsing by bookshelf/subject/LoCC classification, audiobook metadata with Readium profile, and pagination.

### Automatic View Refresh (`Timer.py`)

The materialized view refreshes automatically on startup and once daily at a configurable hour (default 5 PM, set via `mv_refresh_hour` in config). An advisory lock prevents concurrent refreshes when multiple instances share the same database behind a load balancer.

---

## Setup

### Prerequisites

- PostgreSQL with the `gutenberg` database already populated
- Root or sudo access

### 1. Install pyenv, pipenv, and the required Python version

Install [pyenv](https://github.com/pyenv/pyenv#installation) (see [build prerequisites](https://github.com/pyenv/pyenv/wiki#suggested-build-environment) if needed) so that pipenv can install the required Python version. Then install pipenv:

```bash
pip install pipenv
```

### 2. Create the autocat user and directories

```bash
sudo useradd -r -m -d /var/lib/autocat -s /bin/bash autocat
sudo mkdir -p /var/lib/autocat/autocat3
sudo mkdir -p /var/lib/autocat/log
sudo mkdir -p /var/run/autocat
sudo chown -R autocat:autocat /var/lib/autocat
sudo chown -R autocat:autocat /var/run/autocat
```

### 3. Clone the repository

```bash
git clone https://github.com/zachjesus/autocat3.git /tmp/autocat3
sudo cp -r /tmp/autocat3/* /var/lib/autocat/autocat3/
sudo chown -R autocat:autocat /var/lib/autocat
```

### 4. Install dependencies

pipenv reads the `Pipfile` and auto-detects Python 3.6 from pyenv. Setting `PIPENV_VENV_IN_PROJECT` puts the virtualenv in `.venv/` inside the project directory so the systemd service can find it.

```bash
cd /var/lib/autocat/autocat3
sudo -u autocat PIPENV_VENV_IN_PROJECT=1 pipenv install
```

Verify:

```bash
sudo -u autocat /var/lib/autocat/autocat3/.venv/bin/python --version
```

### 5. Create the materialized view

Download and run the SQL script against your `gutenberg` database:

```bash
curl -L -O https://raw.githubusercontent.com/zachjesus/pg-db-mv/main/15_materialized_view.sql
sudo -u postgres psql -d gutenberg -f 15_materialized_view.sql
```

### 6. Grant database permissions (only if not using `postgres` user)

The default config (`CherryPy.conf`) connects as `pguser: 'postgres'`, which already has full privileges. If you change `pguser` to a different database user, that user needs refresh permissions:

```sql
-- Run as postgres, replacing 'myuser' with your pguser:
GRANT USAGE ON SCHEMA public TO myuser;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO myuser;
GRANT EXECUTE ON FUNCTION refresh_mv_books_dc() TO myuser;
ALTER MATERIALIZED VIEW mv_books_dc OWNER TO myuser;
```

### 7. Configure

Edit `/etc/autocat3.conf` (or `~/.autocat3` under the autocat user) to override defaults from `CherryPy.conf`. At minimum, set your database credentials and hosts:

```ini
pghost:     'localhost'
pgport:     5432
pgdatabase: 'gutenberg'
pguser:     'postgres'
```

To change when the materialized view refreshes (default 5 PM server time):

```ini
mv_refresh_hour: 17
```

### 8. Install the systemd service

The service runs the app using the venv's Python directly:

```bash
sudo cp /var/lib/autocat/autocat3/autocat3.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable autocat3.service
```

### 9. Start the service

```bash
sudo systemctl start autocat3.service
```

Check status:

```bash
sudo systemctl status autocat3.service
```

Logs are written to `/var/lib/autocat/log/error.log` and `/var/lib/autocat/log/access.log`.

---

## Service Management

```bash
sudo systemctl start autocat3.service    # Start
sudo systemctl stop autocat3.service     # Stop
sudo systemctl restart autocat3.service  # Restart
sudo systemctl status autocat3.service   # Check status
sudo systemctl daemon-reload             # Reload after editing the unit file
```

---

## Original autocat3

Copyright 2009-2010 by Marcello Perathoner. Fork maintained by Zachary Rosario.
