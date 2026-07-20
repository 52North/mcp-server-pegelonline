.PHONY:	rpm clean source requirements

NAME = mcp-server-pegelonline
VERSION ?= 0.1.0
BUILD_NUMBER ?= 1
SOURCE_NAME = $(NAME)-$(VERSION)
SOURCE = $(SOURCE_NAME).tar.gz
SPEC = $(NAME).spec
TOPDIR = /tmp/$(NAME)-rpm
PWD = $(shell pwd)
PROJECT_ROOT = $(PWD)/..

rpm: source
	@rpmbuild -v -bb \
			--define "version $(VERSION)" \
			--define "build_number $(BUILD_NUMBER)" \
			--define "source $(SOURCE)" \
			--define "source_name $(SOURCE_NAME)" \
			--define "_sourcedir $(PWD)" \
			--define "_rpmdir $(PWD)/RPMS" \
			--define "_topdir $(TOPDIR)" \
			$(SPEC)

clean:
	@rm -rf $(TOPDIR) RPMS
	@rm -f $(SOURCE)

source: $(SOURCE)

$(SOURCE): requirements.txt
	@tar czf $(SOURCE) -C $(PROJECT_ROOT) --transform "s,^,$(SOURCE_NAME)/," \
			server.py helpers.py main.py stations_map.html \
			openapi-pegelonline-dict-api.json \
			LICENSE README.md ROADMAP.md pyproject.toml uv.lock \
			packaging/requirements.txt \
			packaging/$(NAME).service \
			packaging/mcp-server.env

# Hashed dependency list, exported from uv.lock (needs uv). Generated on demand
# if missing; run `make requirements` to force a refresh after changing deps.
requirements.txt:
	@cd $(PROJECT_ROOT) && uv export --frozen --no-dev --no-emit-project \
			--format requirements-txt -o packaging/requirements.txt

requirements:
	@rm -f requirements.txt
	@$(MAKE) requirements.txt
