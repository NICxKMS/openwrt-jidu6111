import argparse
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import release_composition as composition


class ComponentScopeTests(unittest.TestCase):
    def test_dashboard_changes_reuse_firmware(self):
        self.assertEqual(composition.components(["nicx-router-monitor/apps/dashboard/src/App.tsx"]), {"dashboard"})

    def test_shared_agent_and_database_changes_recheck_integrated_stack(self):
        self.assertEqual(
            composition.components(["nicx-router-monitor/packages/shared/schema.ts",
                                    "nicx-router-monitor/supabase/migrations/01_test.sql"]),
            {"dashboard", "worker", "agent", "database"},
        )

    def test_makefile_changes_reverify_build_and_monitoring(self):
        self.assertEqual(composition.components(["Makefile"]), composition.ALL)

    def test_unknown_paths_trigger_broader_validation(self):
        self.assertEqual(composition.components(["unknown.json"]), composition.ALL)


class RepeatPromotionTests(unittest.TestCase):
    def test_replaces_the_carried_worker_bundle_without_rebuilding_firmware(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            release = root / "release"
            release.mkdir()
            bundle = release / "monitor-bundle.tar.gz"
            bundle.write_bytes(b"prior")
            candidate = root / "verified-bundle.tar.gz"
            candidate.write_bytes(b"candidate")
            (release / composition.MANIFEST).write_text(json.dumps({"source_commit": "a" * 40}))
            promotion = root / "promotion.json"
            promotion.write_text('{"kind":"dashboard"}')
            components = root / "components.json"
            components.write_text('{"dashboard":{"source_commit":"new"}}')
            args = argparse.Namespace(directory=release, commit="b" * 40, promotion=promotion,
                                      observed_components=components, bundle=candidate)
            with patch.object(composition, "verify_local", return_value={
                    "source_commit": "a" * 40, "profiles": [{}], "assets": {bundle.name: {}}}):
                composition.compose(args)
            self.assertEqual(bundle.read_bytes(), candidate.read_bytes())
            manifest = json.loads((release / composition.MANIFEST).read_text())
            self.assertEqual(manifest["profiles"][0]["firmware_source_commit"], "a" * 40)
            self.assertEqual(manifest["assets"][bundle.name]["sha256"], composition.digest(candidate))
