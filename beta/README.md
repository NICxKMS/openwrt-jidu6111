# JIDU6111 firmware beta

Pick a build, then choose the Wi-Fi bands you use. Both builds include the same driver fixes, AdGuard Home, monitoring and LTO for eligible packages. The kernel and its modules use different compilers.

| Build | Dual-band · 2.4 and 5 GHz | 5 GHz only · frees 43 MiB reserved for 2.4 GHz | Signed packages |
| --- | --- | --- | --- |
| **Try first · Clang ThinLTO** | [Image](clang-thinlto/openwrt-qualcommbe-ipq95xx-jiorouter_ax6000-jidu6111-squashfs-sysupgrade.bin) | [Image](clang-thinlto/openwrt-qualcommbe-ipq95xx-jiorouter_ax6000-jidu6111-wcss-off-squashfs-sysupgrade.bin) | [Feed](clang-thinlto/packages/) · [Checksums](clang-thinlto/sha256sums) |
| **Fallback · GCC** if you hit a problem with Clang | [Image](gcc-kernel/openwrt-qualcommbe-ipq95xx-jiorouter_ax6000-jidu6111-squashfs-sysupgrade.bin) | [Image](gcc-kernel/openwrt-qualcommbe-ipq95xx-jiorouter_ax6000-jidu6111-wcss-off-squashfs-sysupgrade.bin) | [Feed](gcc-kernel/packages/) · [Checksums](gcc-kernel/sha256sums) |

Both radio images in a row use that row's signed APK feed. The filenames match between rows, so keep the profile folder when you download. The GCC kernel and modules have kernel LTO off.

These images target the JioRouter AX6000 JIDU6111 (`jiorouter,ax6000-jidu6111`). They were built from the [PR #6 source](https://github.com/NICxKMS/openwrt-jidu6111/tree/55310bf292b7b76449454b286c2e59a046554cf8). Router testing is pending. Use Ethernet, back up your settings and monitoring history, and follow the [reflash steps](https://github.com/NICxKMS/openwrt-jidu6111/blob/55310bf292b7b76449454b286c2e59a046554cf8/README.md#choose-a-reflash-build).

To verify and serve the matching packages from a computer on your LAN, clone the beta tag and enter the folder for the image you installed. Change `clang-thinlto` to `gcc-kernel` if you chose the fallback.

```sh
git clone --single-branch --branch jidu6111-6.18.64-beta.1 https://github.com/NICxKMS/openwrt-jidu6111.git jidu6111-beta
cd jidu6111-beta/beta/clang-thinlto
sha256sum -c sha256sums
python3 -m http.server 8000 --bind BUILD_HOST_LAN_IP --directory packages
```
