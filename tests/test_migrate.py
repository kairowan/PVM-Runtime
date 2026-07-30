#!/usr/bin/env python3
"""Small self-check for selective legacy migration."""

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server" / "src"))

from pvm_server.compiler import Compiler  # noqa: E402
from pvm_server.migrate import scan_project, write_conversion  # noqa: E402


class SelectiveMigrationTest(unittest.TestCase):
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
                {item["id"] for item in capabilities["suggested"]},
            )
            self.assertIn("must-not-migrate", (checkout / "Checkout.kt").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
