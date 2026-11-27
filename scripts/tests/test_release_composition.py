import pathlib
import sys
import unittest

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

    def test_unknown_paths_trigger_broader_validation(self):
        self.assertEqual(composition.components(["unknown.json"]), composition.ALL)
