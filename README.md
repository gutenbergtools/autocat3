# autocat3_original

**autocat3** is a Python/CherryPy application that serves dynamic content for [Project Gutenberg](https://www.gutenberg.org). 

CherryPy is used as the web framwork which is easy to develop.

It mainly implements the search functionality and rate limiter. Also return results pages based on templates.

## How it works.
The production version of autocat3 is on **app1**.  
This application in this repository is on **appdev1**.

Previously, the old version of autocat3 relies on dependencies installed directly on the system. To make it more flexible and easy to deploy, we tend to use virtual env rather than the previous method. To use virtual env, we use pipenv instead of using pip and virtual env separately. 

The virtual env directory is on the default directory while we run ```pipenv --three```. So it's not in this directory. (We strictly use python3 for this project because CherryPy will discard the python2 in the future.)

To start the service/application, we use **systemd** to do that. the ```autocat3.service``` file is written under ```/etc/systemd/system```directory. 

## How to Install

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

Until this is merged officially, the scripts live in [gutenbergtools/pgdb PR #15](https://github.com/gutenbergtools/pgdb/pull/15).
Clone the repo, check out that PR, and run the scripts against your `gutenberg`
database. pg_trgm is now managed by its own scripts, so they must be run in
order, and a few require the `postgres` superuser.

```bash
git clone https://github.com/gutenbergtools/pgdb.git
cd pgdb
git fetch origin pull/15/head:full-mv-patch
git checkout full-mv-patch
```

Run these in order:

```bash
# 1. Prep: drop objects depending on the old (unpackaged) pg_trgm — run as gutenberg
psql -U gutenberg -d gutenberg -f 15_prep_pg_trgm_install.sql

# 2. Drop leftover unpackaged pg_trgm artifacts — MUST run as the postgres superuser
psql -U postgres -d gutenberg -f 16_drop_pg_trgm_artifacts.sql

# 3. Install the pg_trgm extension and recreate its indexes — MUST run as postgres
psql -U postgres -d gutenberg -f 17_install_pg_trgm_extension.sql

# 4. Create the materialized view — run as the same user you will use for pguser
psql -U gutenberg -d gutenberg -f 18_materialized_view.sql
```

To avoid permission errors, create the materialized view (step 4) as the same
user you will be using for `pguser` in the next step.

### 6. Configure

Edit `/etc/autocat3.conf` (or `~/.autocat3` under the autocat user) to override defaults from `CherryPy.conf`. At minimum, set your database credentials and hosts:

```ini
[global]
pghost:     'localhost'
pgport:     5432
pgdatabase: 'gutenberg'
pguser:     'postgres'
```

The user must have sufficient permissions to access all public tables and refresh the materialized view.

To change when the materialized view refreshes (default 5 PM server time):

```ini
mv_refresh_hour: 17
```

Other information on configuring Autocat3 can be found in configuring.txt

### 7. Install the systemd service

The service runs the app using the venv's Python directly:

```bash
sudo cp /var/lib/autocat/autocat3/autocat3.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable autocat3.service
```

### 8. Start the service

```bash
sudo systemctl start autocat3.service
```

Check status:

```bash
sudo systemctl status autocat3.service
```

Logs are written to `/var/lib/autocat/log/error.log` and `/var/lib/autocat/log/access.log`.

Some common service commands are:

```bash
sudo systemctl start autocat3.service    # Start
sudo systemctl stop autocat3.service     # Stop
sudo systemctl restart autocat3.service  # Restart
sudo systemctl status autocat3.service   # Check status
sudo systemctl daemon-reload             # Reload after editing the unit file
```

Copyright 2009-2010 by Marcello Perathoner Copyright 2019-present by Project Gutenberg