# autocat3_original
## Introduction

**autocat3** is a python-based application used for supporting [Project Gutenberg](gutenberg.org).

CherryPy is used as the web framwork which is easy to develop.

It mainly implements the search functionality and rate limiter. Also return results pages based on templates. 

## How it works.
The production version of autocat3 is on **app1**.  
This application in this repository is on **appdev1**.

Previously, the old version of autocat3 relies on dependencies installed directly on the system. To make it more flexible and easy to deploy, we tend to use virtual env rather than the previous method. To use virtual env, we use pipenv instead of using pip and virtual env separately. 

The virtual env directory is on the default directory while we run ```pipenv --three```. So it's not in this directory. (We strictly use python3 for this project because CherryPy will discard the python2 in the future.)

To start the service/application, we use **systemd** to do that. the ```autocat3.service``` file is written under ```/etc/systemd/system```directory. 

*To start*:

1. make sure ```sudo systemctl daemon-reload``` every time we edit the systemd unit file
2. ```sudo systemctl start autocat3.service``` to start service
3. ```sudo systemctl stop autocat3.service``` to stop service
4. ```sudo systemctl status autocat3.service``` to check the running status of the service

## How to install
Currently, we use the following steps to deploy autocat3 on a different server.
1. **Create Virtual env**: ```pipenv --three``` to create a virtual env for current working directory(current project)
2. **Install packages/python modules**: ```pipenv install``` to install all the packages in the Pipfile. If there is a requirements.txt file output from ```pip freeze```, the command will automatically add the package names into Pipfile and install the packages and keep them in the Popfile for later use. 
3. **Lock the packages**: ```pipenv lock``` to be used to produce deterministic builds.
4. **Check the virtual env path**: ```pipenv --venv```
5. **Start virtual env**: ```pipenv shell```

Copyright 2009-2010 by Marcello Perathoner
Copyright 2019-present by Project Gutenberg

