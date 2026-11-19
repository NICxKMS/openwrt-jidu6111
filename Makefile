.DEFAULT_GOAL := help
.NOTPARALLEL:

JOBS ?= 4
PROFILE := CONFIG_TARGET_qualcommbe_ipq95xx_DEVICE_jiorouter_ax6000-jidu6111=y

.PHONY: help host-deps source feeds configure menuconfig save-config check download build package package-index cache-stats

# OpenWrt splits PATH on whitespace. Keep absolute entries it can pass intact.
feeds configure menuconfig save-config download build package package-index cache-stats: export PATH := $(shell printf '%s' "$$PATH" | awk -v RS=: '/^\// && !/[[:space:]]/ { printf "%s%s", separator, $$0; separator = ":" }')

help:
	@printf '%s\n' \
	  'make host-deps    Install Ubuntu/Debian build dependencies' \
	  'make source       Prepare the pinned OpenWrt source checkout' \
	  'make feeds        Fetch and index the pinned package feeds' \
	  'make configure    Apply config/jidu6111.diffconfig' \
	  'make menuconfig   Edit packages and image options interactively' \
	  'make save-config  Save menuconfig changes to the workspace config' \
	  'make download     Prefetch sources for the selected packages' \
	  'make build        Build the JIDU6111 images and APKs (JOBS=4 by default)' \
	  'make package PACKAGE=<name>   Build a selected package and its dependencies' \
	  'make package-index           Refresh the signed APK indexes and combined repository' \
	  'make cache-stats             Show compiler cache usage and hit rate'

host-deps:
	sudo apt-get update
	sudo apt-get install build-essential clang flex bison bc bzip2 ccache cpio curl file \
	  gawk gettext git libelf-dev libncurses-dev libssl-dev patch pkg-config \
	  python3-dev python3-pyelftools python3-setuptools rsync swig time unzip \
	  wget xz-utils zlib1g-dev zstd

source:
	bash scripts/bootstrap-source.sh

feeds:
	cd openwrt && ./scripts/feeds update -a && ./scripts/feeds install -a

configure:
	$(MAKE) -C openwrt scripts/config/conf prepare-tmpinfo
	@set -eu; cd openwrt; \
	  next=$$(mktemp .config.jidu6111.XXXXXX); \
	  trap 'rm -f "$$next" "$$next.old"' EXIT; \
	  ./scripts/config/conf --defconfig=../config/jidu6111.diffconfig -w "$$next" Config.in; \
	  grep -Fqx '$(PROFILE)' "$$next" || { echo 'The JIDU6111 profile did not resolve.' >&2; exit 1; }; \
	  while IFS= read -r setting; do \
	    grep -Fqx "$$setting" "$$next" || { echo "Could not select $$setting. Check feeds and dependencies." >&2; exit 1; }; \
	  done < <(grep -E '^CONFIG_PACKAGE_.+=[ym]$$' ../config/jidu6111.diffconfig); \
	  if [ -f .config ]; then cp -p .config .config.old; fi; \
	  mv "$$next" .config
configure: SHELL := /bin/bash

menuconfig: check
	$(MAKE) -C openwrt menuconfig

save-config: check
	@cd openwrt && ./scripts/diffconfig.sh > ../config/jidu6111.diffconfig.new
	@test -s config/jidu6111.diffconfig.new
	@mv config/jidu6111.diffconfig.new config/jidu6111.diffconfig

check:
	@grep -Eq '^KERNEL_PATCHVER[[:space:]]*:=[[:space:]]*6\.18$$' openwrt/target/linux/qualcommbe/Makefile || { echo 'Expected the qualcommbe Linux 6.18 target.' >&2; exit 1; }
	@grep -Fqx '$(PROFILE)' openwrt/.config || { echo 'Run make configure to select JIDU6111.' >&2; exit 1; }

download: check
	$(MAKE) -C openwrt -j$(JOBS) download

build: check
	$(MAKE) -C openwrt -j$(JOBS)

package: export OPENWRT_PACKAGE_NAME = $(PACKAGE)
package: check
	@set -eu; \
	  name=$${OPENWRT_PACKAGE_NAME}; \
	  if [ -z "$$name" ]; then printf '%s\n' 'Usage: make package PACKAGE=<name>' >&2; exit 2; fi; \
	  if ! grep -Fqx -e "CONFIG_PACKAGE_$$name=m" -e "CONFIG_PACKAGE_$$name=y" openwrt/.config; then \
	    printf 'Select %s in make menuconfig before building it.\n' "$$name" >&2; exit 2; \
	  fi; \
	  recipe=$$(awk -v name="$$name" '$$1 == "Source-Makefile:" { recipe = $$2 } $$1 == "Package:" && $$2 == name { print recipe }' openwrt/tmp/.packageinfo | sort -u); \
	  if [ -z "$$recipe" ] || [ ! -f "openwrt/$$recipe" ]; then \
	    printf 'No unique recipe for %s. Refresh the package metadata with make menuconfig.\n' "$$name" >&2; exit 2; \
	  fi; \
	  $(MAKE) -C openwrt -j$(JOBS) "$${recipe%/Makefile}/compile"

package-index: check
	$(MAKE) -C openwrt package/index package/merge-index

cache-stats:
	CCACHE_DIR="$(CURDIR)/openwrt/.ccache" ccache --show-stats
