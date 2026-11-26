# JIDU6111 firmware and packages

This branch contains the JioRouter AX6000 **JIDU6111** sysupgrade image for OpenWrt `r0+38470-c3af7ee2f2` and its matching signed APK repository.

The firmware image is built from [main commit `d2e7f9259b31074846f04d6de1970ac2b9600d1c`](https://github.com/NICxKMS/openwrt-jidu6111/tree/d2e7f9259b31074846f04d6de1970ac2b9600d1c). Its manifest records the packages built into that image.

The signed repository also includes `collectd-mod-rrdtool` **5.12.0-r60**, built from [main commit `738a13719aeba1853f693ddad84e176a74b3fb86`](https://github.com/NICxKMS/openwrt-jidu6111/tree/738a13719aeba1853f693ddad84e176a74b3fb86). This update shares the RRD library lock between file creation and updates to fix startup graph errors. It passed a package upgrade and reboot check on the JIDU6111.

To upgrade an existing installation using this signed repository, run on the router and restart graph collection afterward.

```sh
apk --repositories-file /dev/null -X https://raw.githubusercontent.com/NICxKMS/openwrt-jidu6111/router/packages/packages.adb add --upgrade collectd-mod-rrdtool
/etc/init.d/collectd restart
```

- [Firmware manifest](openwrt-qualcommbe-ipq95xx-jiorouter_ax6000-jidu6111.manifest)
- [SHA-256 checksums](sha256sums)
- [Signed APK repository](packages/)
- [Firmware installation guide](https://github.com/NICxKMS/openwrt-jidu6111/blob/d2e7f9259b31074846f04d6de1970ac2b9600d1c/README.md#install-on-the-router)
- [Package installation guide](https://github.com/NICxKMS/openwrt-jidu6111/blob/d2e7f9259b31074846f04d6de1970ac2b9600d1c/README.md#install-from-the-matching-apk-repository)

## Beta firmware

The [Linux 6.18.64 beta](beta/README.md) offers **Try first · Clang ThinLTO** and **Fallback · GCC**, each with dual-band and 5 GHz-only images and a matching signed APK feed.

## Current source

The [shared firmware and monitor source](https://github.com/NICxKMS/openwrt-jidu6111/tree/75832626ea975cbd39b173946930ab87663f3ecd) targets Linux **6.18.65** and includes Nicx Telemetry **1.0.0-r9**. The published beta above contains Linux **6.18.64** and Nicx Telemetry **1.0.0-r4**. Use the image and signed APK feed from the same published build.
