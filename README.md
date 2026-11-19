# OpenWrt for the JioRouter AX6000 JIDU6111

This workspace builds the community `qualcommbe/ipq95xx` profile for the JIDU6111 on Linux **6.18.60**. The editable OpenWrt checkout is `openwrt/`. The base image includes LuCI with HTTPS, routing, DHCP, DNS, firewall, Ethernet and USB controller drivers, and both ath11k radios with their firmware and JIDU board data.

## Install build tools and build

Run these in your Ubuntu or Debian terminal as your normal user. `make host-deps` uses `sudo` to install the system packages. `make source` applies the tracked patches and board data to the pinned OpenWrt checkout. An existing checkout can proceed directly to the build when the feeds and configuration are already prepared.

```sh
make host-deps
make source
make feeds
make configure
make build JOBS=4
```

The first build downloads sources and compiles the cross-toolchain. You can run `make download JOBS=4` to fetch sources before compiling. The [feed pins](sources/feeds.conf) are copied into the OpenWrt checkout during setup. If a build fails, rerun it with `make build JOBS=1 V=s` to see the failing command.

The workspace `make` commands pass only absolute, whitespace-free `PATH` entries to OpenWrt. If you run native OpenWrt commands on WSL and see `find: The relative path ... is included in the PATH`, prefix the command with `PATH=/usr/local/bin:/usr/bin:/bin`.

Firmware images, the build manifest, and checksums go in `openwrt/bin/targets/qualcommbe/ipq95xx/`. Target APKs are under that target directory and feed APKs are in `openwrt/bin/packages/`.

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

On the build computer, run `make menuconfig`, press `/`, and search for the package. Select `<M>` for a separate APK and save. Compile it with `make package PACKAGE=<name>` and update the local repository with `make package-index`. Use `make save-config` to keep the selection in `config/jidu6111.diffconfig` for future builds. For example, after selecting `htop`:

```sh
make package PACKAGE=htop
make package-index
```

After a fresh checkout, perform a full build once to create the toolchain and signing keys. A userspace package can be added without a firmware rebuild if its dependencies work with the installed firmware. This profile already compiles the kernel modules needed by its APKs, including CAKE and IFB. A new feature that changes the kernel configuration can require a new firmware build and a matching set of kernel modules. Keep the source revisions, feed pins, and original signing keys for the installed image.

You can also edit `config/jidu6111.diffconfig` directly and run `make configure` to apply it. This replaces `openwrt/.config` and saves the previous configuration as `openwrt/.config.old`. Select `<*>` or `=y` only for packages you want to include in the next firmware image.

Put your own OpenWrt package recipe at `openwrt/package/local/<name>/Makefile`, then select it in `menuconfig`. Use the binary package name shown there with `make package PACKAGE=<name>`.

### Install from the matching APK repository

`make package-index` produces a combined signed repository at `openwrt/staging_dir/packages/qualcommbe/`. Serve that directory from a computer reachable from the router. Replace `BUILD_HOST_LAN_IP` with the address the router can reach.

```sh
python3 -m http.server 8000 --bind BUILD_HOST_LAN_IP --directory openwrt/staging_dir/packages/qualcommbe
```

On the router, use that repository for the install. APK will resolve the dependencies and verify signatures with the key in the firmware.

```sh
apk --repositories-file /dev/null -X http://BUILD_HOST_LAN_IP:8000/packages.adb add luci-app-sqm
```

You can also copy a selected batch of APKs and their dependencies to the router and install the files locally. Compare the output of `apk --repositories-file /dev/null query --from installed --fields name,version kernel` on the router with the kernel package in the firmware manifest. The kernel package's full version is the compatibility check, including the identifier after `6.18.60~`.

The `router` branch contains the JIDU6111 sysupgrade image for the installed firmware and its full signed APK repository. Download it with a GitHub account that can access the repository, then serve its package directory from a computer on your LAN.

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

### Connect to Airtel AirFiber

1. Connect your computer to a JIDU LAN port. On a clean boot, open LuCI at `https://192.168.1.1`. If you kept settings during upgrade, use the LAN address from your saved configuration. If Airtel also uses `192.168.1.0/24`, set the JIDU LAN to a different subnet in LuCI before plugging in the uplink.
2. Connect an Airtel **LAN** port to the JIDU **WAN** port. Leave JIDU WAN on DHCP and keep the WAN firewall and IPv4 masquerading enabled. The JIDU serves DHCP to its own clients. Enable its Wi-Fi with country `IN` and a password, then turn off the Airtel radios if all clients are moving to the JIDU.

Outbound traffic uses double NAT. For any future inbound port forward, both routers need matching rules, and an Airtel connection behind carrier-grade NAT also needs a reachable public address or a separate way in. IPv6 for LAN clients depends on Airtel delegating a prefix to the JIDU.

### Recover without an internet connection

- The image includes `nano`, `tcpdump-mini`, `ethtool`, and `lsusb` for inspecting settings and diagnosing the uplink over local SSH. It can read USB storage formatted as ext4, FAT, or exFAT. Use `block info` to identify the backup drive.
- Android USB tethering ships in the image. Create and test a DHCP uplink for your phone in LuCI before you need it. Give the backup interface a higher route metric than the Airtel WAN if you configure both. A higher metric takes effect when the primary route goes away. Automatic detection of an Airtel outage while the Ethernet link stays up requires separate configuration.
- Download a configuration backup from LuCI and keep a copy of the matching RAM-boot image and checksum on your computer. To recover from a configuration lockout, disconnect the Airtel uplink, plug your computer directly into LAN1, and enter [OpenWrt failsafe](https://openwrt.org/docs/guide-user/troubleshooting/failsafe_and_factory_reset). Set the computer to `192.168.1.10/24`, connect with `ssh root@192.168.1.1`, and use `mount_root` to access saved settings. If OpenWrt cannot boot, use the UART/TFTP recovery path above.

## Source revisions

- The [19 November 2026 daily](https://github.com/SahilB69/jidu6j11-openwrt/releases/tag/snapshot-20261119) uses [OpenWrt `ecd9120f0451`](https://github.com/openwrt/openwrt/commit/ecd9120f0451920fd277c717fa06cc358d553409) and [JIDU6J11 board support `5b52c230e955`](https://github.com/SahilB69/openwrt/commit/5b52c230e955eda0519db9a0961faf869bb66cdf). This build uses those revisions and matches the daily's [LuCI revision `6393a54`](https://github.com/openwrt/luci/commit/6393a54375c42772a6362352daa53272360ed389). The other feeds use the revisions in `sources/feeds.conf`.
- [IPQ9574 and QCN9074 board data](https://github.com/openwrt/firmware_qca-wireless/commit/be12dccc79b79799192206514b7ef2dbc222d482) and [iwinfo IPQ9574 device ID](https://github.com/openwrt/iwinfo/commit/49e3d3fa4752971deefe3af9c0608fe461a32df9).
- The build includes the OpenWrt ath11k fixes for suspend/resume interrupts, short management frames, and IRQ cleanup, plus the community per-ring RX memory, interrupt lifecycle, and ring sizing changes. The per-ring patch uses the OpenWrt recovery interrupt sequence. The firmware honors the configured Wi-Fi country.
