FROM rockylinux:9

LABEL maintainer="s.drost@52north.org"

# Build toolchain: make + rpmbuild + the systemd/redhat rpm macros, plus the
# Python interpreter the bundled virtualenv is built on.
RUN dnf -y update && \
    dnf -y install \
        make \
        rpm-build \
        rpmdevtools \
        rpmlint \
        systemd-rpm-macros \
        python3.12 \
        python3.12-devel \
        python3-pip && \
    dnf clean all

# uv builds the relocatable virtualenv in the spec's %install (pinned for
# reproducible builder images).
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /usr/local/bin/

WORKDIR /app

# Application sources live at the repo root - that is the layout the Makefile's
# PROJECT_ROOT (packaging/..) and the spec's %install expect. Build context must
# therefore be the repository root:
COPY server.py helpers.py main.py stations_map.html \
     openapi-pegelonline-dict-api.json \
     LICENSE README.md ROADMAP.md pyproject.toml uv.lock ./

# Packaging inputs (Makefile, spec, unit, env example, hashed requirements.txt).
COPY packaging/ ./packaging/

CMD ["/bin/bash"]
