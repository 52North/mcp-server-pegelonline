%global appname     mcp-server-pegelonline
%global appdir      /opt/%{appname}
%global svcuser     mcpsvc
%global svcgroup    mcpsvc
%global venvpy      %{_bindir}/python3.12

# The payload is a self-contained virtualenv of third-party wheels plus application modules.
%global __brp_python_bytecompile %{nil}
%undefine __brp_mangle_shebangs
%global debug_package %{nil}
%global __requires_exclude ^.*$
%global __provides_exclude ^.*$

# Overridable from the Makefile via `rpmbuild --define`; the version has no
# fallback, so pyproject.toml (read by the Makefile) stays its only source.
%{!?version:      %{error:version is not defined; build with `make rpm`}}
%{!?build_number: %global build_number 1}
%{!?source_name:  %global source_name %{appname}-%{version}}
%{!?source:       %global source %{source_name}.tar.gz}

Name:           mcp-server-pegelonline
Version:        %{version}
Release:        %{build_number}%{?dist}
Summary:        MCP server for the German Pegelonline Dict API (gauge stations)

License:        Apache-2.0
URL:            https://github.com/52North/mcp-server-pegelonline
Source0:        %{source}

BuildArch:      x86_64
BuildRequires:  python3.12
BuildRequires:  python3.12-devel
BuildRequires:  python3-pip
BuildRequires:  systemd-rpm-macros

# The bundled venv is built on, and runs against, the system python3.12.
Requires:       python3.12
Requires(pre):  shadow-utils
%{?systemd_requires}

%description
A Model Context Protocol (MCP) server that exposes tools to search for and query
water-level gauge stations in Germany via the Pegelonline Dict API. This package
ships the application together with a self-contained Python virtualenv.

A minimal systemd unit is installed and preset (not started) on install. It reads
its configuration from /etc/mcp-server-pegelonline/mcp-server.env.

The server speaks the Streamable HTTP transport at /mcp and exposes a health probe at /healthz.

%prep
%autosetup -n %{source_name}

%build
# Nothing to compile here; the venv is materialized in %%install because a
# virtualenv must be created at its final absolute path.

%install
# Bundled virtualenv, built at the final target path inside the buildroot
# uv creates a *relocatable* venv: its console scripts resolve the interpreter
# relative to their own location instead of a hardcoded absolute shebang, so the
# venv works once installed at %{appdir}/venv even though it is materialized under
# the buildroot.
uv venv --relocatable --python %{venvpy} %{buildroot}%{appdir}/venv
uv pip install --no-cache --require-hashes \
    --python %{buildroot}%{appdir}/venv/bin/python \
    -r packaging/requirements.txt

# CycloneDX SBOM, generated from the bundled venv so it reflects exactly what
# ships (with a full dependency graph). Shipped as %doc. The generator comes
# from the "sbom" group in uv.lock, so its version is pinned and hash-checked.
uv run --frozen --only-group sbom cyclonedx-py environment \
    %{buildroot}%{appdir}/venv/bin/python \
    --pyproject pyproject.toml --output-reproducible \
    --output-file %{appname}-bom.json

# Application files: the pegelonline_mcp package; the unit's WorkingDirectory
# puts it on uvicorn's import path.
install -d -m 0755 %{buildroot}%{appdir}/app
find pegelonline_mcp -type f ! -name '*.pyc' \
    -exec install -D -m 0644 {} %{buildroot}%{appdir}/app/{} \;
install -m 0644 openapi-pegelonline-dict-api.json %{buildroot}%{appdir}/app/

# Ship bytecode for the venv and the app: the service user cannot write
# __pycache__ under %{appdir}, so every start would compile in memory.
# -s/-p strip the buildroot from the paths recorded in the .pyc files; -f also
# rewrites the one the SBOM step left behind with the buildroot path in it.
python3.12 -m compileall -q -f -s %{buildroot} -p / %{buildroot}%{appdir}

# systemd unit
install -d -m 0755 %{buildroot}%{_unitdir}
install -m 0644 packaging/%{appname}.service \
    %{buildroot}%{_unitdir}/%{appname}.service

# default environment file
install -d -m 0750 %{buildroot}%{_sysconfdir}/%{appname}
install -d -m 0750 %{buildroot}%{_sysconfdir}/%{appname}/tls
install -m 0640 packaging/mcp-server.env \
    %{buildroot}%{_sysconfdir}/%{appname}/mcp-server.env

# uvicorn logging config
install -m 0640 packaging/log-config.yaml \
    %{buildroot}%{_sysconfdir}/%{appname}/log-config.yaml

%pre
getent group %{svcgroup} >/dev/null || groupadd -r %{svcgroup}
getent passwd %{svcuser} >/dev/null || \
    useradd -r -g %{svcgroup} -d %{appdir} -s /sbin/nologin \
        -c "Pegelonline MCP Server" %{svcuser}
exit 0

%post
%systemd_post %{appname}.service
# Older packages let the service user own its config. rpm keeps a locally
# modified config file on upgrade, owner included, so hand it to root here.
for f in %{_sysconfdir}/%{appname}/mcp-server.env \
         %{_sysconfdir}/%{appname}/log-config.yaml; do
    if [ "$(stat -c %U "$f" 2>/dev/null)" = %{svcuser} ]; then
        chown root "$f"
    fi
done

%preun
%systemd_preun %{appname}.service

%postun
%systemd_postun_with_restart %{appname}.service

%files
%license LICENSE
%doc README.md ROADMAP.md %{appname}-bom.json
%{_unitdir}/%{appname}.service
%{appdir}
%dir %attr(0750, root, %{svcgroup}) %{_sysconfdir}/%{appname}
%dir %attr(0750, root, %{svcgroup}) %{_sysconfdir}/%{appname}/tls
%config(noreplace) %attr(0640, root, %{svcgroup}) %{_sysconfdir}/%{appname}/mcp-server.env
%config(noreplace) %attr(0640, root, %{svcgroup}) %{_sysconfdir}/%{appname}/log-config.yaml
