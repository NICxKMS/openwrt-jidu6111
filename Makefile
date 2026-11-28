.DEFAULT_GOAL := help
.NOTPARALLEL:

JOBS ?= 4
PROFILE := CONFIG_TARGET_qualcommbe_ipq95xx_DEVICE_jiorouter_ax6000-jidu6111=y
REFLASH_PROFILE := CONFIG_TARGET_DEVICE_qualcommbe_ipq95xx_DEVICE_jiorouter_ax6000-jidu6111=y
WCSS_PROFILE := CONFIG_TARGET_DEVICE_qualcommbe_ipq95xx_DEVICE_jiorouter_ax6000-jidu6111-wcss-off=y
export JIDU6111_RADIO := $(BUILD_RADIO)

.PHONY: help host-deps source feeds configure configure-gcc-kernel configure-clang-thinlto menuconfig save-config check download build build-gcc-kernel build-clang-thinlto package package-index cache-stats

# OpenWrt splits PATH on whitespace. Keep absolute entries it can pass intact.
feeds configure configure-gcc-kernel configure-clang-thinlto menuconfig save-config download build build-gcc-kernel build-clang-thinlto package package-index cache-stats build-firmware: export PATH := $(shell printf '%s' "$$PATH" | awk -v RS=: '/^\// && !/[[:space:]]/ { printf "%s%s", separator, $$0; separator = ":" }')

help:
	@printf '%s\n' \
	  'make host-deps    Install Ubuntu/Debian build dependencies' \
	  '                  Clang ThinLTO on Ubuntu 22.04 needs clang-15, llvm-15 and lld-15.' \
	  'make source       Prepare the pinned OpenWrt source checkout' \
	  'make feeds        Fetch and index the pinned package feeds' \
	  'make configure    Apply config/jidu6111.diffconfig' \
	  'make configure-clang-thinlto   Select both radio variants with Clang ThinLTO' \
	  'make configure-gcc-kernel      Select both radio variants with GCC' \
	  'make menuconfig   Edit packages and image options interactively' \
	  'make save-config  Save menuconfig changes to the workspace config' \
	  'make download     Prefetch sources for the selected packages' \
	  'make build        Build the JIDU6111 images and APKs (JOBS=4 by default)' \
	  'make build-clang-thinlto       Try first: Clang ThinLTO kernel and modules' \
	  'make build-gcc-kernel          Fallback: GCC kernel and modules, kernel LTO off' \
	  '                               Add BUILD_RADIO=dual-band or wcss-off for local single-radio builds.' \
	  'make package PACKAGE=<name>   Build a selected package and its dependencies' \
	  'make package-index           Refresh the signed APK indexes and combined repository' \
	  'make build-firmware          Build from an exact commit in a disposable workspace' \
	  'make test-release            Run firmware release and compatibility tests' \
	  'make release-beta            Stage a Beta draft and request publication' \
	  'make promote                 Stage the exact Beta artifacts and request Stable approval' \
	  'make verify-router           Read board, installed packages and trust fingerprints' \
	  'make cleanup                 Preview removal of abandoned owned builds' \
	  'make repo-status             Show the checkout and worktrees' \
	  'make cache-stats             Inspect existing interactive compiler caches' \
	  'make storage-report          Report build storage, with REMOTE=1 for GitHub' \
	  'make patch-report            Validate and list downstream patch provenance'

host-deps:
	sudo apt-get update
	sudo apt-get install build-essential clang flex bison bc bzip2 ccache cpio curl file \
	  gawk gettext git libelf-dev libncurses-dev libssl-dev lld llvm patch pkg-config \
	  python3-dev python3-pyelftools python3-setuptools rsync swig time unzip \
	  wget xz-utils zlib1g-dev zstd openssl squashfs-tools

source:
	bash scripts/bootstrap-source.sh

feeds:
	@set -eu; checkout=openwrt/feeds/nicx_monitor; \
	  pin=$$(awk '$$2 == "nicx_monitor" { sub(/^.*\^/, "", $$3); print $$3 }' sources/feeds.conf); \
	  if [ -e "$$checkout" ] || [ -L "$$checkout" ]; then \
	    if [ ! -d "$$checkout/.git" ] || [ "$$(git -C "$$checkout" rev-parse HEAD)" != "$$pin" ] || \
	       ! feed_status=$$(git -C "$$checkout" status --porcelain --untracked-files=all) || [ -n "$$feed_status" ]; then \
	      echo 'The Nicx Monitor feed differs from its pin or has local changes. Preserve local edits, move openwrt/feeds/nicx_monitor aside, then rerun make feeds.' >&2; exit 1; \
	    fi; \
	  fi
	cp sources/feeds.conf openwrt/feeds.conf
	cd openwrt && ./scripts/feeds update -a
	bash scripts/apply-feed-patches.sh
	cd openwrt && ./scripts/feeds install -a
	cd openwrt && ./scripts/feeds uninstall qt5base qt6base fwknop luci-app-fwknopd

configure: source
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

configure-gcc-kernel configure-clang-thinlto: source
	@bash scripts/apply-feed-patches.sh
	@bash scripts/configure-reflash.sh $(patsubst configure-%,%,$@)

menuconfig: check
	$(MAKE) -C openwrt menuconfig

save-config: check
	@grep -Fqx '$(PROFILE)' openwrt/.config || { echo 'Run make configure before saving the standard profile. Edit config/jidu6111-reflash.diffconfig for reflash builds.' >&2; exit 1; }
	@cd openwrt && ./scripts/diffconfig.sh > ../config/jidu6111.diffconfig.new
	@test -s config/jidu6111.diffconfig.new
	@mv config/jidu6111.diffconfig.new config/jidu6111.diffconfig

check: source
	@bash scripts/apply-feed-patches.sh
	@grep -Eq '^KERNEL_PATCHVER[[:space:]]*:=[[:space:]]*6\.18$$' openwrt/target/linux/qualcommbe/Makefile || { echo 'Expected the qualcommbe Linux 6.18 target.' >&2; exit 1; }
	@grep -Fqx -e '$(PROFILE)' -e '$(REFLASH_PROFILE)' -e '$(WCSS_PROFILE)' openwrt/.config || { echo 'Run make configure to select JIDU6111.' >&2; exit 1; }

download: check
	$(MAKE) -C openwrt -j$(JOBS) download

build: check
	$(MAKE) -C openwrt -j$(JOBS)

build-gcc-kernel: configure-gcc-kernel
build-clang-thinlto: configure-clang-thinlto

build-gcc-kernel build-clang-thinlto:
	$(MAKE) -C openwrt -j$(JOBS)
	$(MAKE) -C openwrt package/index package/merge-index

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

.PHONY: build-firmware verify-router release-beta promote cleanup storage-report repo-status test-release patch-report

export JIDU_OP_COMMIT := $(COMMIT)
export JIDU_OP_TAG := $(TAG)
export JIDU_OP_OUTPUT := $(OUTPUT)
export JIDU_OP_SIGNING_KEY := $(SIGNING_KEY)
export JIDU_OP_BUILD_PROFILE := $(BUILD_PROFILE)
export JIDU_OP_ROUTER := $(ROUTER)
export JIDU_OP_BETA := $(BETA)
export JIDU_OP_EVIDENCE := $(EVIDENCE)
export JIDU_OP_NOTES := $(NOTES)

build-firmware:
	@set -eu; set --; if [ -n "$$JIDU_OP_BUILD_PROFILE" ]; then set -- --profile "$$JIDU_OP_BUILD_PROFILE"; fi; \
	  bash scripts/build-firmware.sh --commit "$$JIDU_OP_COMMIT" --output "$$JIDU_OP_OUTPUT" \
	    --signing-key "$$JIDU_OP_SIGNING_KEY" --jobs "$(JOBS)" "$$@"

verify-router:
	@ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 -- "root@$${JIDU_OP_ROUTER:-192.168.50.1}" \
	  'ubus call system board && apk --no-cache --repositories-file /dev/null query --from installed --fields name,version --format json kernel nicx-telemetry luci-app-nicx-telemetry && cat /etc/apk/arch && sha256sum /etc/apk/keys/*.pem'

release-beta:
	@bash scripts/release-operator.sh beta

promote:
	@bash scripts/release-operator.sh stable

cleanup:
	@python3 -B scripts/release_storage.py cleanup $(if $(filter 1,$(APPLY)),--apply)

storage-report:
	@python3 -B scripts/release_storage.py report $(if $(filter 1,$(REMOTE)),--remote)

repo-status:
	@git status --short --branch
	@git worktree list

patch-report:
	@python3 -B scripts/check_sources.py --report

test-release:
	@python3 -B -m unittest discover -s scripts/tests -v
