# Stable bootstrap provenance

This baseline preserves the existing installation. It identifies the OpenWrt firmware published as `r0+38470-c3af7ee2f2` and the compatible package feed. The firmware image source is `d2e7f9259b31074846f04d6de1970ac2b9600d1c`. The legacy feed also includes the package fix at `738a13719aeba1853f693ddad84e176a74b3fb86`, whose firmware configuration, feed pins and OpenWrt overlays are kept here.

The installed `nicx-telemetry` and `luci-app-nicx-telemetry` packages are both `1.0.0-r2`. Their source is `ad68a3bcbb0e7337d9ffea82753e25d8953f543d`. The signed recovery packages remain separate from the original signed feed to preserve its index. The schema contains the six migrations matched to the hosted database. The public dashboard assets matched source commit `75832626ea975cbd39b173946930ab87663f3ecd`.

The live Cloudflare Worker version is `bdd78582-b7d0-4c14-92c6-4b103d92ab8d`. Its exact Git source is unverified. The Worker source retained from the release tooling merge provides a starting point for future reviewed changes. Bootstrap verifies the active deployment without deploying that source.

The preserved firmware configuration describes the historical build. Use the current Development source and isolated release builder for new firmware candidates.
