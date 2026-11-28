# Building and trusting APK packages

## Build and install

Use the signed APK feed linked to the image in the release manifest. For a kernel module or a userspace package with a kernel dependency, verify the complete installed kernel APK version, including its ABI hash. The board, target, architecture, profile and signing key also identify the matching feed. For an architecture-independent or compatible userspace package without a kernel dependency, APK checks the actual runtime dependencies and signatures. The firmware version alone cannot establish compatibility.

On a prepared OpenWrt tree, select the package as a module with `make menuconfig`. Run `make package PACKAGE=name` and `make package-index`. Reuse the same profile's configured tree and toolchain. For a cold environment use a compatible OpenWrt SDK when the recipe or compiled dependencies need the toolchain. Use source, configuration, toolchain and feed pins from build information. Build a local SDK with OpenWrt's `CONFIG_SDK` option when needed. Verify SDK source and checksum before use. [OpenWrt build system and SDK](https://openwrt.org/docs/guide-developer/toolchain/start)

The baseline `nicx-telemetry` and `luci-app-nicx-telemetry` recipes from the pinned external feed package architecture-independent scripts and LuCI resources. They still need the installed userspace dependencies, compatible LuCI and pinned build tools such as the LuCI minifier. For a prepared firmware build tree:

```sh
make package PACKAGE=nicx-telemetry
make package PACKAGE=luci-app-nicx-telemetry
make package-index
```

For independent publication, use a compatible OpenWrt packaging environment, the recipes' declared dependencies and the package publisher's signing key. An independently signed compatible update can be installed without reflashing after establishing trust. A full firmware SDK download is unnecessary for consumers installing built packages. Record the built APK architectures, dependency metadata and checksums and test on the supported firmware before distributing.

The current external package installer can use Stable manifests or the extracted directory of a compatible Beta feed through its local feed option. Automatic discovery of the Beta tag format depends on the external installer supporting it. [Monitoring packages](https://github.com/NICxKMS/openwrt-router-monitor)

The pinned Qt 5, Qt 6 and fwknop recipe groups produce recursive Kconfig dependencies. The firmware feed setup leaves those four local recipe links uninstalled. Their pinned source remains available, and neither firmware profile selects their packages. Check those metadata cycles before enabling the recipes in a separate build tree.

## Signing and trust

Keep the firmware APK private key offline or in private maintainer storage outside the repository and scratch tree. Keep encrypted recovery backups and record the public SHA-256 fingerprint. The build embeds the public PEM, signs the package files and index, and records its exact file hash. The release workflow requires this fingerprint to match the configured trusted key. Reused key files must be the expected format and access-restricted. CI verifies signatures with public keys and has no signing key.

For a separately signed package feed, obtain the publisher's public PEM and its SHA-256 fingerprint through a separately verified publisher channel. Compare the exact downloaded bytes before installing the public key in `/etc/apk/keys/`. Verify the index and APKs with the router's APK tools before installation. Scope the feed used by the install command to the intended repositories. APK trust applies to signatures and grants a trusted publisher system-wide package authority. Repository choice aids dependency selection. [APK keys and package verification](https://github.com/alpinelinux/apk-tools/blob/master/doc/apk.8.scd) · [APK security model](https://github.com/alpinelinux/apk-tools/blob/master/SECURITY.md)

Use distinct signing keys for independent publishers. For rotation, distribute and authenticate the replacement public key with trusted instructions before publishing packages that require it. Keep the previous public key and its signed recovery feed as needed for recovery. Remove a compromised key from the router trust store and switch to verified recovery artifacts or packages before resuming normal installs. The firmware signing key remains with the firmware maintainer.
