# OpenWrt for the JioRouter AX6000 JIDU6111

This workspace builds the community `qualcommbe/ipq95xx` profile for the JIDU6111 on Linux **6.18.65**. The editable OpenWrt checkout is `openwrt/`. The base image includes LuCI with HTTPS, routing, DHCP, DNS, firewall, Ethernet and USB controller drivers, and both ath11k radios with their firmware and JIDU board data.

## Downloads and variants

Use [GitHub Releases](https://github.com/NICxKMS/openwrt-jidu6111/releases) for Stable and Beta downloads. **Stable** is hardware verified and the newest eligible version appears as Latest. **Beta** is a verified build candidate. The release manifest and notes identify which hardware tests were performed. Until replacement downloads are available, use the [existing image and matching signed feed archive](https://github.com/NICxKMS/openwrt-jidu6111/tree/router).

Choose the compiler and radio variant from the same release as its signed feed. Use dual-band for 2.4 GHz and 5 GHz, or WCSS-off to keep 5 GHz and free the 43 MiB WCSS reservation. The filename identifies both selections. GCC is the fallback kernel compiler. See [installation and recovery](#install-on-the-router) and [release operations](docs/release-operations.md).

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

The firmware includes two monitoring recipes from the pinned external OpenWrt feed. The manifest records their bundled versions and source commit. Router inventory reports the installed versions separately. See [package building and trust](docs/packages.md).

| Radio choice | Sysupgrade filename ending |
| --- | --- |
| **Dual-band** for 2.4 GHz and 5 GHz | `jidu6111-squashfs-sysupgrade.bin` |
| **5 GHz only** to free the 43 MiB WCSS reservation | `jidu6111-wcss-off-squashfs-sysupgrade.bin` |

OpenWrt's local build keeps the same filenames under compiler-specific directories. Official release asset names include the compiler and radio. Each image must use the signed APK feed from its own build profile. In each output root, `targets/qualcommbe/ipq95xx/` holds the images, manifests and `sha256sums`, while `repository/` holds the signed APK feed. From the image directory, run `sha256sum -c sha256sums` before uploading.

Edit `config/jidu6111-reflash.diffconfig` to persist package changes for both reflash profiles. `make save-config` saves changes from the standard profile.

Clang ThinLTO requires LLVM 15 or newer and was tested with LLVM 21. Ubuntu 22.04 ships LLVM 14 by default. After `make host-deps`, install and select the LLVM 15 toolchain from the Ubuntu package repositories.

```bash
sudo apt-get install clang-15 llvm-15 lld-15
make build-clang-thinlto KERNEL_LLVM=-15
```

For another versioned toolchain, pass its suffix (for example, `KERNEL_LLVM=-21`) or an absolute tool directory ending in `/`. Both profiles use smaller ath11k RX buffers and include AdGuard Home, Nicx Router Monitor, vnStat, nlbwmon, collectd and zram.

#### Resource use

The reflash profiles enable IRQ accounting, pressure stalls, process memory counters and SLUB statistics. Leave allocation-site profiling off for normal operation. The profiles include vnStat, nlbwmon and collectd for different interface, client and system statistics. Keep their existing databases when upgrading. Compare idle memory, slab, throughput and reliability under the same workload before changing defaults. See the [hardware test procedure](docs/hardware-testing.md).

The standard `make build` writes firmware images, the build manifest, and checksums to `openwrt/bin/targets/qualcommbe/ipq95xx/`. Target APKs are under that target directory and feed APKs are in `openwrt/bin/packages/`.

The interactive OpenWrt targets share the generated checkout in your worktree. Use them for local experiments. Release builds use the isolated `make build-firmware` entry point, keep downloads and intermediates in its disposable workspace and preserve the independently stored signing key.

## Add packages

The following features are available as signed APKs. The reflash profiles already bundle AdGuard Home, usage and system statistics, and zram. Install others as needed from the feed that matches your firmware.

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

Reuse a prepared build tree or compatible SDK for package-only builds. See the [package build and signing guide](docs/packages.md). A userspace package can be added without a firmware rebuild if its dependencies work with the installed firmware. This profile already compiles the kernel modules needed by its APKs, including CAKE and IFB. A new feature that changes the kernel configuration can require a new firmware build and a matching set of kernel modules. Keep the source revisions, feed pins, and original signing keys for the installed image.

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

1. Check the case label for **JIDU6111**. Confirm the board using `ubus call system board`. Choose the matching sysupgrade image and compare its SHA-256 with the release manifest before uploading. The `initramfs-uImage.itb` image produced by the OpenWrt build is for temporary RAM boot.
2. Connect by Ethernet and back up the LuCI configuration, package list, existing image and matching signed feed. Keep a private copy of `/etc/config/nicx-telemetry`, applicable files under `/etc/nicx-telemetry/`, and the actual configured vnStat, nlbwmon and collectd/RRD database paths. Save DNS filtering configuration and data where used.
3. The regular image expects `jiorouter,ax6000-jidu6111`. For `jiorouter,ax6000-jidu6j11-6111`, the dated JIDU6111 board-ID transition image and its checksum are required. Use your verified local copy of the November 19, 2026 transition image. If you lack that image or its checksum, stop and obtain the matching recovery files. Run `sysupgrade -T /tmp/<image-name>.bin` before every flash. Proceed in LuCI or with `sysupgrade /tmp/<image-name>.bin` only after validation. Keep settings for a compatible upgrade.
4. After reboot, check the build identity, Ethernet, WAN, DNS, radios, package trust and any enabled local monitoring services. Check WAN6 and USB WAN where configured.
5. For first installation from stock, use the device maintainer's UART/TFTP and RAM-boot procedure. The JIDU6111 uses **3.3 V UART at 115200 8N1**. Back up `0:ART`, `MFG`, `0:BDF` and the U-Boot environment before writing NAND. Verify Ethernet and both radios on the dual-band RAM boot. [JIDU6111 board support and installation](https://github.com/openwrt/openwrt/pull/26498)

### Connect behind an upstream router

1. Connect your computer to a JIDU LAN port. On a clean boot, open LuCI at `https://192.168.1.1`. If you kept settings during upgrade, use the LAN address from your saved configuration. If the upstream router also uses `192.168.1.0/24`, set the JIDU LAN to a different subnet in LuCI before connecting the uplink.
2. Connect an upstream **LAN** port to the JIDU **WAN** port. Leave JIDU WAN on DHCP and keep the WAN firewall and IPv4 masquerading enabled. The JIDU serves DHCP to its own clients. Enable Wi-Fi with your country and a password. If all Wi-Fi clients are moving to the JIDU, you can turn off the upstream router's radios.

If both routers perform NAT, outbound IPv4 traffic uses double NAT. Inbound port forwarding then needs matching rules on both routers. A connection behind carrier-grade NAT also needs a reachable public address or another way in. IPv6 for LAN clients depends on the upstream router delegating a prefix to the JIDU.

### Recover without an internet connection

- The image includes `nano`, `tcpdump-mini`, `ethtool`, and `lsusb` for inspecting settings and diagnosing the uplink over local SSH. It can read USB storage formatted as ext4, FAT, or exFAT. Use `block info` to identify the backup drive.
- Android USB tethering ships in the image. Create and test a DHCP uplink for your phone in LuCI before you need it. Give the backup interface a higher route metric than the primary WAN if you configure both. The backup takes over when the primary route goes away. Detecting an upstream outage while the Ethernet link stays up requires separate configuration.
- Download a configuration backup from LuCI and keep a copy of the matching RAM-boot image and checksum on your computer. To recover from a configuration lockout, disconnect the upstream cable, plug your computer directly into LAN1, and enter [OpenWrt failsafe](https://openwrt.org/docs/guide-user/troubleshooting/failsafe_and_factory_reset). Set the computer to `192.168.1.10/24`, connect with `ssh root@192.168.1.1`, and use `mount_root` to access saved settings. If OpenWrt cannot boot, use the UART/TFTP recovery path above.

## Development and limitations

Open firmware changes against `main`, using a temporary development branch and a separate worktree. Run `make test-release` and `make patch-report` locally. The pinned board support is a community build. Hardware and performance results apply to the tested image and configuration. Full image builds require substantial local disk space. Follow the [release guide](docs/release-operations.md) and [contributor instructions](AGENTS.md).

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
