# autocat3 image. Make a autocat3.conf with your DB settings, then build & run.
# DEV commands, Postgres on the same machine as podman:
#   Linux/WSL2   (pghost 127.0.0.1):              podman build -t autocat3 . && podman run --rm --network=host -v ./autocat3.conf:/etc/autocat3.conf:Z autocat3
#   Mac/Windows  (pghost host.containers.internal): podman build -t autocat3 . && podman run --rm -p 8000:8000 --add-host=host.containers.internal:host-gateway -v ./autocat3.conf:/etc/autocat3.conf:Z autocat3
FROM docker.io/rockylinux/rockylinux:9
RUN dnf -y install python3 python3-pip python3-devel gcc \
    libpq-devel libxml2-devel libxslt-devel libjpeg-turbo-devel zlib-devel \
    && dnf clean all
RUN pip3 install pipenv
WORKDIR /app
COPY Pipfile Pipfile.lock ./
RUN python3 -m venv /app/.venv \
    && PIPENV_VENV_IN_PROJECT=1 pipenv install
COPY . .
RUN useradd -r -m -d /var/lib/autocat autocat \
    && mkdir -p /var/lib/autocat/log /var/run/autocat \
    && chown -R autocat:autocat /var/lib/autocat /var/run/autocat
USER autocat
EXPOSE 8000
CMD ["/app/.venv/bin/python", "CherryPyApp.py"]
