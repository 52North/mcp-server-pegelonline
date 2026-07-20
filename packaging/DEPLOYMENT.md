# RPM on RHEL9 Deployment

This document describes how the `mcp-server-pegelonline` RPM is built and how
to run it for developing purpose.

## Building the RPM

### With Docker

No RHEL host required. From the **repository root** (the build context must be
the repo root so the app sources are available):

1) Build image with all required app module and packaging files:
    ```bash
    docker build -f packaging/Dockerfile -t edis/mcp-rpm-build .
    ```
2) Run the container and mount a volume for build output.
    ```bash
    docker run -it -v "$PWD/dist:/app/packaging/RPMS" edis/mcp-rpm-builder
    ```
3) Inside the container run `make -C packaging rpm` to trigger the RPM package build

### On a RHEL9 host directly

With PyPI (or an internal mirror) reachable, and `uv` on `PATH` (the spec builds
the bundled venv with `uv venv --relocatable`):

```bash
sudo dnf install -y make rpm-build python3.12 python3.12-devel systemd-rpm-macros
# uv (if not already installed):
curl -LsSf https://astral.sh/uv/install.sh | sh
cd packaging
# builds RPM into packaging/RPMS/
make rpm
```

Override the version/release without editing files:
`make VERSION=0.2.0 BUILD_NUMBER=2`.

The RPM bundles a self-contained, relocatable virtualenv (`uv venv --relocatable`) plus
the app modules. Dependencies are installed reproducibly from `packaging/requirements.txt`
with `uv pip install --require-hashes`.

## What the RPM installs

| Path | Owner | Notes |
|------|-------|-------|
| `/opt/mcp-server-pegelonline/app/` | root | `server.py`, `helpers.py`, `main.py`, `stations_map.html`, openapi json |
| `/opt/mcp-server-pegelonline/venv/` | root | bundled virtualenv (read-only at runtime) |
| `/usr/lib/systemd/system/mcp-server-pegelonline.service` | root | single-process uvicorn unit |
| `/etc/mcp-server-pegelonline/` (dir) | `mcpsvc` | config dir |
| `/etc/mcp-server-pegelonline/mcp-server.env` | `mcpsvc` | default env config, `%config(noreplace)`; read by the unit's `EnvironmentFile` |

The RPM also creates the `mcpsvc` system user/group (`%pre`)
It does **not** start or enable the service on install (`%systemd_post` presets only).

## Manual install & run (without Puppet)

For a quick trial on a single RHEL9 host, without any configuration management.
The shipped unit is intentionally **minimal**: it serves plain **HTTP on port
8000** with no TLS, reading its configuration from the packaged
`/etc/mcp-server-pegelonline/mcp-server.env` (Puppet supplies the production unit).

**1. Install the RPM:** 
dnf resolves the `python3.12` dependency, creates the `mcpsvc` user and installs the disabled unit

```bash
sudo dnf install -y ./mcp-server-pegelonline-0.1.0-1.el9.x86_64.rpm
```

**2. Start server with the shipped unit:**

```bash
sudo systemctl enable --now mcp-server-pegelonline
curl -s http://localhost:8000/healthz          # -> ok
journalctl -u mcp-server-pegelonline -f        # follow logs
```

The MCP endpoint is then `http://localhost:8000/mcp`.

**3. Override configuration (optional)**
Edit the env file, then restart:

```bash
sudo vi /etc/mcp-server-pegelonline/mcp-server.env    # e.g. LOG_LEVEL=DEBUG
sudo systemctl restart mcp-server-pegelonline
```

**4. Stop / uninstall:**

```bash
sudo systemctl disable --now mcp-server-pegelonline
sudo dnf remove -y mcp-server-pegelonline
```
