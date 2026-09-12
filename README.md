# autocat3_original

**autocat3** is a python-based application used for supporting [Project Gutenberg](gutenberg.org).

CherryPy is used as the web framework which is easy to develop.

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
sudo mkdir -p /var/lib/autocat/log
sudo mkdir -p /var/run/autocat
```

### 3. Clone the repository

```bash
sudo su - autocat
git clone https://github.com/gutenbergtools/autocat3.git
```

### 4. Install dependencies

pipenv reads the `Pipfile` and auto-detects Python 3.9 from pyenv. Setting `PIPENV_VENV_IN_PROJECT` puts the virtualenv in `.venv/` inside the project directory so the systemd service can find it.

```bash
cd /var/lib/autocat/autocat3
sudo -u autocat PIPENV_VENV_IN_PROJECT=1 pipenv install
```

Verify:

```bash
sudo -u autocat /var/lib/autocat/autocat3/.venv/bin/python --version
```

### 5. Configure

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

### 6. Install the systemd service

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