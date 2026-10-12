# RPM on RHEL9 Deployment

This document describes how the `mcp-server-pegelonline` RPM is built and how
to run it for developing purpose.

## Building the RPM

### With Docker

No RHEL host required. From the **repository root** (the build context must be
the repo root so the app sources are available):

1) Build image with the `pegelonline_mcp` package and all packaging files:
    ```bash
    docker build -f packaging/Dockerfile -t edis/mcp-rpm-build .
    ```
2) Run the container and mount a volume for build output.
    ```bash
    docker run -it -v "$PWD/dist:/app/packaging/RPMS" edis/mcp-rpm-build
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

The version comes from `pyproject.toml` (the spec has no fallback, so build via
`make`); bump the release without editing files: `make BUILD_NUMBER=2`.

The RPM bundles a self-contained, relocatable virtualenv (`uv venv --relocatable`) plus
the `pegelonline_mcp` package. Dependencies are installed reproducibly from `packaging/requirements.txt`
with `uv pip install --require-hashes`. Both ship precompiled bytecode, since the
service user cannot write `__pycache__` below `/opt`. The CycloneDX SBOM is generated
with the `cyclonedx-bom` version pinned in the `sbom` group of `uv.lock`. The build
needs network access to PyPI.

## What the RPM installs

| Path | Owner | Notes |
|------|-------|-------|
| `/opt/mcp-server-pegelonline/app/` | root | `pegelonline_mcp/` package (incl. `static/stations_map.html`), openapi json |
| `/opt/mcp-server-pegelonline/venv/` | root | bundled virtualenv (read-only at runtime) |
| `/usr/lib/systemd/system/mcp-server-pegelonline.service` | root | single-process uvicorn unit (`uvicorn pegelonline_mcp.asgi:app`, working directory `app/`), hardened (read-only system, no capabilities, private `/tmp` and devices, only IP and Unix sockets) |
| `/etc/mcp-server-pegelonline/` (dir) | `root:mcpsvc` (0750) | config dir |
| `/etc/mcp-server-pegelonline/tls/` (dir) | `root:mcpsvc` (0750) | not used by the shipped unit |
| `/etc/mcp-server-pegelonline/mcp-server.env` | `root:mcpsvc` (0640) | default env config, `%config(noreplace)`; read by the unit's `EnvironmentFile` |
| `/etc/mcp-server-pegelonline/log-config.yaml` | `root:mcpsvc` (0640) | uvicorn logging config, `%config(noreplace)`; passed via the unit's `--log-config` |

The service can read its configuration but not change it. Older packages let
`mcpsvc` own it; an upgrade hands config files still owned by `mcpsvc` to root
(`%post`).

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

The server runs stateless: it keeps no MCP session between requests, so several
instances behind a load balancer need no sticky sessions. `GET /mcp` (a stream for
server-initiated messages, which this server never sends) answers `405`.

**3. Override configuration (optional)**
Edit the env file, then restart:

```bash
sudo vi /etc/mcp-server-pegelonline/mcp-server.env    # upstream URLs, bind/port
sudo systemctl restart mcp-server-pegelonline
```

To change the log level or format, edit the uvicorn logging config (the unit passes
it via `--log-config`), then restart:

```bash
sudo vi /etc/mcp-server-pegelonline/log-config.yaml
sudo systemctl restart mcp-server-pegelonline
```

**4. Stop / uninstall:**

```bash
sudo systemctl disable --now mcp-server-pegelonline
sudo dnf remove -y mcp-server-pegelonline
```
