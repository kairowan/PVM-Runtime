#!/usr/bin/env python3
"""Small self-check for selective legacy migration."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server" / "src"))

from pvm_server.compiler import Compiler  # noqa: E402
from pvm_server.migrate import (  # noqa: E402
    scan_project,
    verify_conversion,
    write_conversion,
)


class SelectiveMigrationTest(unittest.TestCase):
    def test_json_line_progress_events(self):
        with tempfile.TemporaryDirectory(prefix="pvm-migrate-events-") as name:
            root = Path(name) / "legacy"
            root.mkdir()
            (root / "Counter.kt").write_text(
                "class Counter { var count: Int = 0 }\n",
                encoding="utf-8",
            )
            report = Path(name) / "scan.json"
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(ROOT / "server" / "src")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pvm_server.migrate",
                    "scan",
                    str(root),
                    "--class",
                    "Counter",
                    "--output",
                    str(report),
                    "--events-jsonl",
                ],
                cwd=ROOT,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
            events = [
                json.loads(line) for line in completed.stdout.splitlines() if line
            ]
            self.assertTrue(report.is_file())
            self.assertTrue(
                all(event["type"] == "migration.event" for event in events)
            )
            self.assertEqual([event["progress"] for event in events], [2, 10, 90, 100])
            self.assertEqual(events[-1]["status"], "pass")

    def test_single_multiple_module_and_dependency_selection(self):
        with tempfile.TemporaryDirectory(prefix="pvm-migrate-test-") as name:
            root = Path(name) / "legacy"
            checkout = root / "app" / "checkout"
            profile = root / "app" / "profile"
            account = root / "app" / "account"
            harmony = root / "harmony" / "settings"
            checkout.mkdir(parents=True)
            profile.mkdir(parents=True)
            account.mkdir(parents=True)
            harmony.mkdir(parents=True)
            (checkout / "Checkout.kt").write_text(
                """
package com.example.checkout
import retrofit2.Retrofit
import com.android.billingclient.api.BillingClient

class CheckoutViewModel {
    var count: Int = 1
    var token: String = "must-not-migrate"
    private val gateway = PaymentGateway()
    fun refresh() = gateway.load()
}

class PaymentGateway {
    fun load() = Retrofit.Builder()
}
""",
                encoding="utf-8",
            )
            (profile / "Profile.swift").write_text(
                """
import SwiftUI
struct ProfileView {
    @State var displayName: String = "Alice"
    var body: some View { Text(displayName) }
}
""",
                encoding="utf-8",
            )
            (account / "AccountState.java").write_text(
                """
package com.example.account;
public class AccountState {
    private boolean enabled = true;
}
""",
                encoding="utf-8",
            )
            (harmony / "Settings.ets").write_text(
                """
@Component
struct SettingsPage {
  @State enabled: boolean = false
  build() { Column() { Text('Settings') } }
}
""",
                encoding="utf-8",
            )

            inventory = scan_project(root)
            self.assertEqual(
                {unit["language"] for unit in inventory["units"]},
                {"arkts", "java", "kotlin", "swift"},
            )
            states_by_unit = {
                unit["name"]: {state["name"] for state in unit["states"]}
                for unit in inventory["units"]
            }
            self.assertEqual(states_by_unit["AccountState"], {"enabled"})
            self.assertEqual(states_by_unit["SettingsPage"], {"enabled"})

            single = scan_project(root, classes=["CheckoutViewModel"])
            self.assertEqual(
                [unit["name"] for unit in single["units"]], ["CheckoutViewModel"]
            )
            self.assertEqual(
                [state["name"] for state in single["units"][0]["states"]], ["count"]
            )
            self.assertIn(
                "sensitive_state",
                {item["id"] for item in single["units"][0]["manualReview"]},
            )
            self.assertTrue(single["units"][0]["unselectedLocalDependencies"])

            multiple = scan_project(
                root,
                classes=["CheckoutViewModel", "ProfileView"],
                include_dependencies=True,
            )
            self.assertEqual(
                {unit["name"] for unit in multiple["units"]},
                {"CheckoutViewModel", "PaymentGateway", "ProfileView"},
            )

            module = scan_project(root, modules=[":app:checkout"])
            self.assertEqual(
                {unit["name"] for unit in module["units"]},
                {"CheckoutViewModel", "PaymentGateway"},
            )

            output = Path(name) / "converted"
            artifacts = write_conversion(
                multiple,
                output,
                application_id="com.example.legacy",
                platform="android",
                module_id="legacy.checkout",
            )
            self.assertEqual(set(artifacts), {
                "capabilities.json",
                "migration-approvals.json",
                "migration-cases.json",
                "migration-report.json",
                "migration-report.md",
                "module.pvm.json",
            })
            dsl = json.loads((output / "module.pvm.json").read_text(encoding="utf-8"))
            Compiler(dsl).build()
            self.assertEqual(dsl["state"]["count"]["initial"], 1)
            self.assertEqual(dsl["state"]["displayName"]["initial"], "")
            capabilities = json.loads(
                (output / "capabilities.json").read_text(encoding="utf-8")
            )
            self.assertIn(
                "payment.purchase",
                {item["id"] for item in capabilities["decisions"]},
            )
            pending = verify_conversion(root, output, strict=True)
            self.assertEqual(pending["result"], "failed")
            self.assertEqual(pending["gates"]["reviews"]["status"], "fail")
            self.assertEqual(pending["gates"]["capabilities"]["status"], "fail")
            approvals = json.loads(
                (output / "migration-approvals.json").read_text(encoding="utf-8")
            )
            for item in approvals["items"]:
                item.update(status="resolved", note="Covered by the legacy regression test.")
            (output / "migration-approvals.json").write_text(
                json.dumps(approvals, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            for decision in capabilities["decisions"]:
                decision.update(
                    status="approved",
                    adapter="ExistingHostAdapter",
                    tests=["LegacyCheckoutTest#capability"],
                )
            (output / "capabilities.json").write_text(
                json.dumps(capabilities, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            dsl["module"]["capabilities"] = sorted(
                decision["id"] for decision in capabilities["decisions"]
            )
            dsl["module"]["network_domains"] = ["api.example.com"]
            (output / "module.pvm.json").write_text(
                json.dumps(dsl, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            reviewed = verify_conversion(root, output, strict=True)
            self.assertEqual(reviewed["gates"]["reviews"]["status"], "pass")
            self.assertEqual(
                reviewed["gates"]["capabilities"]["status"],
                "pass",
                reviewed["gates"]["capabilities"],
            )
            self.assertEqual(reviewed["gates"]["behavior"]["status"], "fail")
            verification = verify_conversion(root, output)
            self.assertEqual(verification["result"], "structurally_valid")
            self.assertIn("must-not-migrate", (checkout / "Checkout.kt").read_text())
            (checkout / "Checkout.kt").write_text(
                (checkout / "Checkout.kt").read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            drifted = verify_conversion(root, output)
            self.assertEqual(drifted["result"], "failed")
            self.assertEqual(drifted["gates"]["source"]["status"], "fail")


if __name__ == "__main__":
    unittest.main(verbosity=2)
