# OpenWrt for the JioRouter AX6000 JIDU6111

This workspace builds the community `qualcommbe/ipq95xx` profile for the JIDU6111 on Linux **6.18.65**. The editable OpenWrt checkout is `openwrt/`. The base image includes LuCI with HTTPS, routing, DHCP, DNS, firewall, Ethernet and USB controller drivers, and both ath11k radios with their firmware and JIDU board data.

## Install build tools and build

Run these in your Ubuntu or Debian terminal as your normal user. `make host-deps` uses `sudo` to install the system packages. `make source` applies the tracked patches and board data to the pinned OpenWrt checkout. You can reuse a checkout prepared with the same wrapper revision. When updating the wrapper, save any local changes and move the previous generated `openwrt/` checkout aside before running `make source` so the current overlays and feed pins are applied.

```sh
make host-deps
make source
make feeds
make configure
make build JOBS=4
```

The first build downloads sources and compiles the cross-toolchain. You can run `make download JOBS=4` to fetch sources before compiling. The [feed pins](sources/feeds.conf) are copied into the OpenWrt checkout during setup. If a build fails, rerun it with `make build JOBS=1 V=s` to see the failing command.

The workspace `make` commands pass only absolute, whitespace-free `PATH` entries to OpenWrt. If you run native OpenWrt commands on WSL and see `find: The relative path ... is included in the PATH`, prefix the command with `PATH=/usr/local/bin:/usr/bin:/bin`.

### Choose a reflash build

Try **Clang ThinLTO** first. Choose **GCC fallback** if you run into problems with the Clang build or need to build without LLVM. Both profiles include the same driver fixes, memory tuning, monitoring and GCC LTO for eligible packages. The choice changes how the kernel and its modules are built.

```sh
make host-deps
make source
make feeds
make build-clang-thinlto JOBS=8
```

| Which to choose | Build command | Kernel and modules | Output root |
| --- | --- | --- | --- |
| **Try first** | `make build-clang-thinlto JOBS=8` | Clang with ThinLTO | `openwrt/bin-clang-thinlto/` |
| **GCC fallback** | `make build-gcc-kernel JOBS=8` | GCC with kernel LTO off | `openwrt/bin-gcc-kernel/` |

Each profile builds both radio variants, for **four sysupgrade images** across the two profiles. Pick the radio variant within your chosen profile.

| Radio choice | Sysupgrade filename ending |
| --- | --- |
| **Dual-band** for 2.4 GHz and 5 GHz | `jidu6111-squashfs-sysupgrade.bin` |
| **5 GHz only** to free the 43 MiB WCSS reservation | `jidu6111-wcss-off-squashfs-sysupgrade.bin` |

The two profiles use the same filenames and JIDU6111 device ID. Each image must use the signed APK feed from its own build profile. In each output root, `targets/qualcommbe/ipq95xx/` holds the images, manifests and `sha256sums`, while `repository/` holds the signed APK feed. From the image directory, run `sha256sum -c sha256sums` before uploading.

Edit `config/jidu6111-reflash.diffconfig` to persist package changes for both reflash profiles. `make save-config` saves changes from the standard profile.

Clang ThinLTO requires LLVM 15 or newer and was tested with LLVM 21. On Ubuntu 22.04, install `clang-15`, `llvm-15`, and `lld-15` from the Ubuntu package repositories, then run `make build-clang-thinlto KERNEL_LLVM=-15`. With a versioned LLVM toolchain, pass `KERNEL_LLVM=-21` or an absolute tool directory ending in `/`. Both profiles use smaller ath11k RX buffers and include AdGuard Home, Nicx Router Monitor, vnStat, nlbwmon, collectd and zram.

#### CPU and memory monitoring

- The Memory page compares RAM declared by the device tree with Linux-managed RAM and shows named firmware reservations separately. Within Linux-managed RAM it shows anonymous pages, shared memory and tmpfs, file cache, slab, page tables, stacks, and the signed difference between the measured categories and total. It also shows slab backing pages, kernel allocation sites when profiling is enabled, page-zone watermarks and free-block sizes, process PSS and swap, zram, socket memory and pressure stalls.
- The CPU page shows aggregate and per-core time by state, including hardware and software IRQ time, the busiest tasks, scheduling and interrupt counters, CPU frequency where supported, and temperatures. Existing WAN and USB WAN collection, Wi-Fi, storage, connectivity and service health continue alongside it.
- Both reflash kernels enable IRQ-time accounting, SLUB counters and pressure stalls. Linux and device firmware expose different views of RAM and some counters overlap. The dashboard shows the difference explicitly. Allocation-site profiling is optional. To enable it, add `CONFIG_KERNEL_MEM_ALLOC_PROFILING=y` and `CONFIG_KERNEL_MEM_ALLOC_PROFILING_ENABLED_BY_DEFAULT=y` to `config/jidu6111-reflash.diffconfig` before building. Its router memory and throughput costs still need measurement.

The firmware installs the agent version pinned in the [package feed list](sources/feeds.conf). The [dashboard update](https://github.com/NICxKMS/openwrt-jidu6111/pull/7) uses the same enrollment and telemetry schema. Existing local monitoring databases remain part of the backup procedure below.

**Migration from the old names.** `make build-optimized` and `openwrt/bin-optimized/` became `make build-gcc-kernel` and `openwrt/bin-gcc-kernel/`. `make build-thinlto` and `openwrt/bin-thinlto/` became `make build-clang-thinlto` and `openwrt/bin-clang-thinlto/`. For configuration only, use `make configure-gcc-kernel` or `make configure-clang-thinlto`.

1. Connect by Ethernet. Save the current sysupgrade image, matching APKs, configuration backup and package list. Confirm the backup contains the telemetry keep files under `/etc/nicx-telemetry/` and `/etc/config/nicx-telemetry`. Keep that archive private.
2. Back up the actual vnStat, nlbwmon and RRD database directories separately. Resolve their configured paths first, since a configuration backup can omit those directories. Back up existing AdGuard Home configuration and data if present.
3. Confirm the board ID is `jiorouter,ax6000-jidu6111`. Verify the selected image checksum, upload the image and run `sysupgrade -T` on it. Flash only after the router accepts the image. Keep settings when flashing. Follow the migration guidance below for an older board ID.
4. After reboot, verify Ethernet, WAN and USB WAN, DNS, 5 GHz and fresh telemetry under the same enrolled device. Verify 2.4 GHz on the dual-band image. For the WCSS-off image, check that the radio is absent and compare `MemTotal` under comparable boot conditions.
5. Set up AdGuard Home on an alternate DNS port and test it before changing dnsmasq forwarding. Keep dnsmasq serving DHCP and local names. During cutover, point dnsmasq at AdGuard Home and give AdGuard Home independent upstream resolvers. Start with one filter list and leave DNS query logging off if you only need traffic totals. Disable the old DNS blocker after the new DNS path works. Verify webapp WAN and USB history against the local collectors before retiring any overlapping service.

The standard `make build` writes firmware images, the build manifest, and checksums to `openwrt/bin/targets/qualcommbe/ipq95xx/`. Target APKs are under that target directory and feed APKs are in `openwrt/bin/packages/`.

Downloads are reused from `openwrt/dl/`. The JIDU6111 profile enables compiler caching in `openwrt/.ccache/` and per-component logs in `openwrt/logs/`. `make cache-stats` reports compiler cache hits and size. Incremental builds reuse the existing toolchain and build files in `openwrt/staging_dir/` and `openwrt/build_dir/`. `make distclean` removes these build files, downloads, cache, and APK signing keys.

## Add packages

The profile builds the following features as signed APKs. Install the ones you need after the router is running the matching firmware.

| Feature | Package to install |
| --- | --- |
| SQM with CAKE | `luci-app-sqm` |
| AdGuard Home with LuCI | `luci-app-adguardhome` |
| Lightweight DNS filtering and encrypted DNS | `luci-app-adblock-fast`, optionally `luci-app-https-dns-proxy` |
| Usage and system graphs | `luci-app-nlbwmon`, `luci-app-statistics`, `collectd-mod-thermal`, `collectd-mod-ping` |
| Compressed swap | `zram-swap` |
| Optional WireGuard and TUN support | `luci-proto-wireguard`, `kmod-tun` |
| Additional diagnostics | `iperf3`, `ip-full`, `htop` |
| USB Ethernet adapters | `kmod-usb-net-rtl8152`, `kmod-usb-net-asix-ax88179` |
| Additional disk support and tools | `kmod-fs-ntfs3`, `kmod-usb-storage-extras`, `blkid`, `fdisk`, `dosfstools` |

Choose AdGuard Home or Adblock Fast as your DNS filtering service. If AdGuard Home and dnsmasq both provide DNS, give them separate listening ports and keep dnsmasq responsible for DHCP. For CAKE, set the actual uplink and measured speeds in LuCI and keep hardware flow offload disabled while shaping.

### Compile a package later

On the build computer, run `make menuconfig`, press `/`, and search for the package. Select `<M>` for a separate APK and save. Compile it with `make package PACKAGE=<name>` and update the local repository with `make package-index`. For the standard profile, use `make save-config` to keep the selection in `config/jidu6111.diffconfig`. For the reflash profiles, record the selection in `config/jidu6111-reflash.diffconfig`. For example, after selecting `htop`:

```sh
make package PACKAGE=htop
make package-index
```

After a fresh checkout, perform a full build once to create the toolchain and signing keys. A userspace package can be added without a firmware rebuild if its dependencies work with the installed firmware. This profile already compiles the kernel modules needed by its APKs, including CAKE and IFB. A new feature that changes the kernel configuration can require a new firmware build and a matching set of kernel modules. Keep the source revisions, feed pins, and original signing keys for the installed image.

You can also edit `config/jidu6111.diffconfig` directly and run `make configure` to apply it. This replaces `openwrt/.config` and saves the previous configuration as `openwrt/.config.old`. Select `<*>` or `=y` only for packages you want to include in the next firmware image.

Put your own OpenWrt package recipe at `openwrt/package/local/<name>/Makefile`, then select it in `menuconfig`. Use the binary package name shown there with `make package PACKAGE=<name>`.

### Install from the matching APK repository

`make package-index` refreshes the signed repository for the active profile. The standard profile uses `openwrt/staging_dir/packages/qualcommbe/`. The Clang ThinLTO and GCC profiles use `openwrt/bin-clang-thinlto/repository/` and `openwrt/bin-gcc-kernel/repository/`, respectively. Serve the repository from the build tree so its links to the APK files resolve. Replace `BUILD_HOST_LAN_IP` with the address the router can reach. This example serves the Clang ThinLTO repository.

```sh
python3 -m http.server 8000 --bind BUILD_HOST_LAN_IP --directory openwrt/bin-clang-thinlto/repository
```

On the router, use that repository for the install. APK will resolve the dependencies and verify signatures with the key in the firmware.

```sh
apk --repositories-file /dev/null -X http://BUILD_HOST_LAN_IP:8000/packages.adb add luci-app-sqm
```

You can also copy a selected batch of APKs and their dependencies to the router and install the files locally. Compare the output of `apk --repositories-file /dev/null query --from installed --fields name,version kernel` on the router with the kernel package in the firmware manifest. Compatibility includes the identifier after the kernel version.

The [`router` branch](https://github.com/NICxKMS/openwrt-jidu6111/tree/router) contains the JIDU6111 sysupgrade image and its full signed APK repository. Clone it and serve its package directory from a computer on your LAN.

```sh
git clone --single-branch --branch router https://github.com/NICxKMS/openwrt-jidu6111.git jidu6111-router
cd jidu6111-router
sha256sum -c sha256sums
python3 -m http.server 8000 --bind BUILD_HOST_LAN_IP --directory packages
```

## Edit board support and drivers

Work inside `openwrt/`. Normal OpenWrt build commands and Git work there. To keep an edit in this repository, save additions such as local driver patches under `sources/openwrt/` with the same paths. Refresh `sources/openwrt.patch` with `git -C openwrt diff --binary HEAD` when you edit tracked OpenWrt files.

- `target/linux/qualcommbe/dts/` contains the JIDU6111 device tree and the shared JIDU6J11 `.dtsi`.
- `target/linux/qualcommbe/image/ipq95xx.mk` defines the image and default driver packages for each SKU.
- `target/linux/qualcommbe/patches-6.18/` and `config-6.18` hold the platform's kernel patches and configuration.
- `package/kernel/mac80211/patches/ath11k/` holds the Wi-Fi driver patches. Edit those files to persist changes across builds.
- `package/firmware/ipq-wifi/src/` holds the IPQ9574 and QCN9074 board files. Each contains a `JIDU6111` entry, selected by the device tree. Calibration unique to the router comes from its ART partition.

## Install on the router

1. Check the label for **JIDU6111**. In the build output, choose the image ending in `jiorouter_ax6000-jidu6111-squashfs-sysupgrade.bin` and verify it against `sha256sums`. The `jiorouter_ax6000-jidu6111-initramfs-uImage.itb` image is for a temporary RAM boot.
2. If the router already runs OpenWrt, save its configuration and check `ubus call system board`. Use the regular sysupgrade image for `jiorouter,ax6000-jidu6111`. For the older `jiorouter,ax6000-jidu6j11-6111` board ID, use the dated migration image under `migration/` and verify it against the checksum in that folder. Upload the selected image to `/tmp` on the router and run `sysupgrade -T /tmp/<image-name>.bin`. If validation succeeds, use LuCI's **Backup / Flash Firmware** screen or run `sysupgrade /tmp/<image-name>.bin`. Run the check again after uploading a newer image. Keep the downloaded configuration backup on your computer.
3. For a first install from stock, follow the device maintainer's [UART/TFTP and RAM-boot instructions](https://github.com/openwrt/openwrt/pull/26498). The 6111 uses **3.3 V UART at 115200 8N1**. Back up `0:ART`, `MFG`, `0:BDF`, and the U-Boot environment before flashing. Check both Ethernet and Wi-Fi radios on the RAM boot before writing NAND.

### Connect behind an upstream router

1. Connect your computer to a JIDU LAN port. On a clean boot, open LuCI at `https://192.168.1.1`. If you kept settings during upgrade, use the LAN address from your saved configuration. If the upstream router also uses `192.168.1.0/24`, set the JIDU LAN to a different subnet in LuCI before connecting the uplink.
2. Connect an upstream **LAN** port to the JIDU **WAN** port. Leave JIDU WAN on DHCP and keep the WAN firewall and IPv4 masquerading enabled. The JIDU serves DHCP to its own clients. Enable Wi-Fi with your country and a password. If all Wi-Fi clients are moving to the JIDU, you can turn off the upstream router's radios.

If both routers perform NAT, outbound IPv4 traffic uses double NAT. Inbound port forwarding then needs matching rules on both routers. A connection behind carrier-grade NAT also needs a reachable public address or another way in. IPv6 for LAN clients depends on the upstream router delegating a prefix to the JIDU.

### Recover without an internet connection

- The image includes `nano`, `tcpdump-mini`, `ethtool`, and `lsusb` for inspecting settings and diagnosing the uplink over local SSH. It can read USB storage formatted as ext4, FAT, or exFAT. Use `block info` to identify the backup drive.
- Android USB tethering ships in the image. Create and test a DHCP uplink for your phone in LuCI before you need it. Give the backup interface a higher route metric than the primary WAN if you configure both. The backup takes over when the primary route goes away. Detecting an upstream outage while the Ethernet link stays up requires separate configuration.
- Download a configuration backup from LuCI and keep a copy of the matching RAM-boot image and checksum on your computer. To recover from a configuration lockout, disconnect the upstream cable, plug your computer directly into LAN1, and enter [OpenWrt failsafe](https://openwrt.org/docs/guide-user/troubleshooting/failsafe_and_factory_reset). Set the computer to `192.168.1.10/24`, connect with `ssh root@192.168.1.1`, and use `mount_root` to access saved settings. If OpenWrt cannot boot, use the UART/TFTP recovery path above.

## Source revisions

- The local collectd feed patch shares the RRD library lock between file creation and updates. It fixes startup graph errors such as “Not enough arguments” and publishes `collectd-mod-rrdtool` as `5.12.0-r60`. `make feeds` and the wrapper build checks apply this patch automatically.

- The 26 November 2026 source pin merges [OpenWrt main `f76496253dfc`](https://github.com/openwrt/openwrt/commit/f76496253dfc6a987843a32c5f18b92f668dd3e0) with [JIDU6J11 support `727ed7916a1d`](https://github.com/openwrt/openwrt/commit/727ed7916a1df588a5a325119e837fec5483c062). The board update derives the label MAC from the WAN MAC and updates the U-Boot tools release. The pinned official package feeds include AdGuard Home 1.0.0. [Feed revisions](sources/feeds.conf)
- [IPQ9574 and QCN9074 board data](https://github.com/openwrt/firmware_qca-wireless/commit/be12dccc79b79799192206514b7ef2dbc222d482) and [iwinfo IPQ9574 device ID](https://github.com/openwrt/iwinfo/commit/49e3d3fa4752971deefe3af9c0608fe461a32df9).
- The build includes the OpenWrt ath11k fixes for suspend/resume interrupts, short management frames, and IRQ cleanup, plus the community per-ring RX memory, interrupt lifecycle, and ring sizing changes. The per-ring patch uses the OpenWrt recovery interrupt sequence. The firmware honors the configured Wi-Fi country.

### Included upstream pull requests

| Area | Pull requests used in these builds |
| --- | --- |
| Linux 6.18.65 | [kernel update #26893](https://github.com/openwrt/openwrt/pull/26893) |
| Board, calibration and memory | [OpenWrt #26498](https://github.com/openwrt/openwrt/pull/26498) · [board data #193](https://github.com/openwrt/firmware_qca-wireless/pull/193) · [WCSS reservation #26847](https://github.com/openwrt/openwrt/pull/26847) · [iwinfo #51](https://github.com/openwrt/iwinfo/pull/51) |
| Ethernet | [#25405](https://github.com/openwrt/openwrt/pull/25405) · [#25569](https://github.com/openwrt/openwrt/pull/25569) · [#26055](https://github.com/openwrt/openwrt/pull/26055) · [#26461](https://github.com/openwrt/openwrt/pull/26461) · [#26741](https://github.com/openwrt/openwrt/pull/26741) |
| Shared network fixes | [#26122](https://github.com/openwrt/openwrt/pull/26122) · [#26492](https://github.com/openwrt/openwrt/pull/26492) |
| Wi-Fi driver | [#25807](https://github.com/openwrt/openwrt/pull/25807) · [#25982](https://github.com/openwrt/openwrt/pull/25982) · [#26253](https://github.com/openwrt/openwrt/pull/26253) · [#26866](https://github.com/openwrt/openwrt/pull/26866) · [#25520](https://github.com/openwrt/openwrt/pull/25520) · [#26161](https://github.com/openwrt/openwrt/pull/26161) · [#25733](https://github.com/openwrt/openwrt/pull/25733) |
| Wi-Fi control | [#26341](https://github.com/openwrt/openwrt/pull/26341) · [#26652](https://github.com/openwrt/openwrt/pull/26652) · [#26342](https://github.com/openwrt/openwrt/pull/26342) · [#26534](https://github.com/openwrt/openwrt/pull/26534) · [#26395](https://github.com/openwrt/openwrt/pull/26395) · [#26326](https://github.com/openwrt/openwrt/pull/26326) · [#26392](https://github.com/openwrt/openwrt/pull/26392) · [#26494](https://github.com/openwrt/openwrt/pull/26494) · [#26655](https://github.com/openwrt/openwrt/pull/26655) · [#26939](https://github.com/openwrt/openwrt/pull/26939) |
| Wi-Fi recovery and compatibility | [#26875](https://github.com/openwrt/openwrt/pull/26875) · [#26709](https://github.com/openwrt/openwrt/pull/26709) · [#26613](https://github.com/openwrt/openwrt/pull/26613) · [#26057](https://github.com/openwrt/openwrt/pull/26057) |
| WAN and Wi-Fi service recovery | [#25851](https://github.com/openwrt/openwrt/pull/25851) · [#26273](https://github.com/openwrt/openwrt/pull/26273) · [#26164](https://github.com/openwrt/openwrt/pull/26164) · [#26653](https://github.com/openwrt/openwrt/pull/26653) · [#26894](https://github.com/openwrt/openwrt/pull/26894) |
| Existing driver backports | [RXDMA and interrupt handling #24254](https://github.com/openwrt/openwrt/pull/24254) · [receive coalescing #24658](https://github.com/openwrt/openwrt/pull/24658) |

For #26893, #26122, #25807, #25982, #26253 and #26655, the build uses the changes that apply to this board and backports version. The [driver audit](sources/jidu6111-driver-audit.md) records those portions, fixes already covered by upstream code, and why other candidates were omitted.

## Credits

- **Sahil Bakshi (SahilB69)** maintains the community daily builds, developed the JIDU6J11 OpenWrt port and RX ring sizing patch, and submitted the IPQ9574 device ID to iwinfo. Robert Marko signed off the iwinfo change. [Community build](https://github.com/SahilB69/jidu6j11-openwrt) · [OpenWrt device support](https://github.com/openwrt/openwrt/pull/26498) · [iwinfo change](https://github.com/openwrt/iwinfo/pull/51)
- **AliLostInTheDark** packaged the model-specific IPQ9574 and QCN9074 board data used here. [Board-data contribution](https://github.com/openwrt/firmware_qca-wireless/pull/193)
- **Mark Ruvald Pedersen (eisbaw)** authored the ath11k interrupt lifecycle and per-ring RX memory patches. **Baochen Qiang, Jiale Yao, and ZhaoJinming** authored the upstream ath11k fixes for suspend/resume interrupt handling, short management frames, and interrupt setup cleanup. [RX memory patch series](https://github.com/openwrt/openwrt/pull/24254) · [Upstream driver patches](https://github.com/openwrt/openwrt/tree/ecd9120f0451920fd277c717fa06cc358d553409/package/kernel/mac80211/patches/ath11k)
- The firmware and packages build on the work of the **OpenWrt, Linux, LuCI, and APK Tools** contributors, the maintainers of the individual packages, and the JIDU6J11 community testers. [OpenWrt](https://github.com/openwrt/openwrt) · [Linux](https://kernel.org/) · [LuCI](https://github.com/openwrt/luci) · [APK Tools](https://gitlab.alpinelinux.org/alpine/apk-tools) · [Package feed revisions](sources/feeds.conf)

This is an independent community build for the JIDU6111. OpenWrt is licensed under [GPL-2.0-only](sources/licenses/GPL-2.0.txt). Individual packages and firmware retain their upstream licenses. The upstream [IPQ9574 license](sources/licenses/IPQ9574-firmware.txt), [QCN9074 license](sources/licenses/QCN9074-firmware.txt), and [QCN9074 notices](sources/licenses/QCN9074-notices.txt) are included here.
