#!/usr/bin/env python3
"""One small integration suite for the protected compiler/delivery/runtime chain."""

import copy
import base64
import json
import os
import shlex
import subprocess
import struct
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server" / "src"))

from pvm_server.compiler import (  # noqa: E402
    CompileError,
    Compiler,
    compile_file,
    find_openssl,
    sign_payload,
)
from pvm_server.compatibility import variants as compatibility_variants  # noqa: E402
from pvm_server.conformance import check as check_renderer_conformance  # noqa: E402
from pvm_server.publish import publish  # noqa: E402
from pvm_server.serve import ModuleServer  # noqa: E402
from pvm_server.host_manifest import generate as generate_host_manifest  # noqa: E402
from pvm_server.host_idl import check_outputs, load as load_host_idl  # noqa: E402
from pvm_server.manifest import decode_envelope, encode_payload, payload_from_control  # noqa: E402
from pvm_server.release import set_rollout  # noqa: E402
from pvm_server.security_check import scan_strings  # noqa: E402
from pvm_server.tooling import lint as lint_source  # noqa: E402


class ProtectedRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="pvm-test-")
        cls.directory = Path(cls.temporary.name)
        cls.runtime = Path(os.environ.get("PVM_RUNTIME", ROOT / "build" / "client" / "pvm_cli"))
        cls.c_api_smoke = cls.runtime.with_name("pvm_c_api_smoke")
        if not cls.runtime.is_file():
            raise RuntimeError("build pvm_cli first or set PVM_RUNTIME")
        if not cls.c_api_smoke.is_file():
            raise RuntimeError("build pvm_c_api_smoke first")
        openssl = find_openssl()
        if openssl is None:
            raise RuntimeError("OpenSSL 3 is required")
        cls.private_key = cls.directory / "private.pem"
        cls.public_key = cls.directory / "public.pem"
        subprocess.run(
            [openssl, "genpkey", "-algorithm", "ED25519", "-out", str(cls.private_key)],
            check=True,
        )
        subprocess.run(
            [
                openssl,
                "pkey",
                "-in",
                str(cls.private_key),
                "-pubout",
                "-out",
                str(cls.public_key),
            ],
            check=True,
        )
        cls.source = ROOT / "server" / "sample" / "counter.pvm.json"
        cls.module = cls.directory / "counter.pvm"
        compile_file(cls.source, cls.private_key, cls.module)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_runtime(self, module=None, *arguments):
        return subprocess.run(
            [
                str(self.runtime),
                "--module",
                str(module or self.module),
                "--public-key",
                str(self.public_key),
                "--app-id",
                "com.example.protected",
                *arguments,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_deterministic_compile_and_state_recovery(self):
        second = self.directory / "counter-second.pvm"
        compile_file(self.source, self.private_key, second)
        self.assertEqual(self.module.read_bytes(), second.read_bytes())

        state = self.directory / "state.bin"
        first = self.run_runtime(None, "--tap-index", "0", "--state-file", str(state))
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn('text="Protected counter: 1"', first.stdout)
        second_run = self.run_runtime(None, "--tap-index", "0", "--state-file", str(state))
        self.assertEqual(second_run.returncode, 0, second_run.stderr)
        self.assertIn("Restored persisted state", second_run.stdout)
        self.assertIn('text="Protected counter: 2"', second_run.stdout)

        source_text = self.source.read_text(encoding="utf-8")
        migrated = json.loads(
            source_text.replace('"count"', '"total"').replace("{count}", "{total}")
        )
        migrated["module"]["release"] = 6
        migrated["state"]["total"]["persistence_id"] = "count"
        migrated["state"]["enabled"] = {
            "type": "bool",
            "persistence_id": "enabled",
            "initial": True,
        }
        renamed_source = self.directory / "renamed-state.pvm.json"
        renamed_source.write_text(json.dumps(migrated), encoding="utf-8")
        renamed_module = self.directory / "renamed-state.pvm"
        compile_file(renamed_source, self.private_key, renamed_module)
        migrated_run = self.run_runtime(
            renamed_module, "--tap-index", "0", "--state-file", str(state)
        )
        self.assertEqual(migrated_run.returncode, 0, migrated_run.stderr)
        self.assertIn("Restored persisted state", migrated_run.stdout)
        self.assertIn('text="Protected counter: 3"', migrated_run.stdout)

        migrated["module"]["release"] = 7
        migrated["state"]["status"] = {
            "type": "bool",
            "persistence_id": "status",
            "initial": False,
        }
        migrated["handlers"].pop("load_status")
        migrated["pages"]["main"]["children"] = [
            node
            for node in migrated["pages"]["main"]["children"]
            if node["id"] != "counter_load_status"
        ]
        incompatible_source = self.directory / "incompatible-state.pvm.json"
        incompatible_source.write_text(json.dumps(migrated), encoding="utf-8")
        incompatible_module = self.directory / "incompatible-state.pvm"
        compile_file(incompatible_source, self.private_key, incompatible_module)
        incompatible_run = self.run_runtime(
            incompatible_module, "--state-file", str(state)
        )
        self.assertNotEqual(incompatible_run.returncode, 0)
        self.assertIn("type mismatch", incompatible_run.stderr)

    def test_remote_signer_protocol_matches_local_signing(self):
        remote = self.directory / "remote-signed.pvm"
        command = shlex.join(
            [
                sys.executable,
                str(ROOT / "server" / "tools" / "local_signer.py"),
                "--openssl",
                find_openssl(),
                "--private-key",
                str(self.private_key),
            ]
        )
        compile_file(self.source, None, remote, signer_command=command)
        self.assertEqual(remote.read_bytes(), self.module.read_bytes())

    def test_c_abi_callbacks_effects_and_snapshot(self):
        completed = subprocess.run(
            [
                str(self.c_api_smoke),
                str(self.module),
                str(self.public_key),
                "com.example.protected",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("C ABI smoke: PASS", completed.stdout)

    def test_tamper_binding_and_rollback_are_rejected(self):
        tampered = self.directory / "tampered.pvm"
        body = bytearray(self.module.read_bytes())
        body[40] ^= 1
        tampered.write_bytes(body)
        self.assertIn("signature verification failed", self.run_runtime(tampered, "--validate-only").stderr)

        mismatch = subprocess.run(
            [
                str(self.runtime),
                "--module",
                str(self.module),
                "--public-key",
                str(self.public_key),
                "--app-id",
                "com.attacker.clone",
                "--validate-only",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertNotEqual(mismatch.returncode, 0)
        self.assertIn("binding mismatch", mismatch.stderr)
        channel_mismatch = self.run_runtime(
            None, "--channel", "other", "--validate-only"
        )
        self.assertNotEqual(channel_mismatch.returncode, 0)
        self.assertIn("channel binding mismatch", channel_mismatch.stderr)
        platform_mismatch = self.run_runtime(
            None, "--platform", "ios", "--profile", "online_provisioned", "--validate-only"
        )
        self.assertNotEqual(platform_mismatch.returncode, 0)
        self.assertIn("platform binding mismatch", platform_mismatch.stderr)
        profile_mismatch = self.run_runtime(
            None, "--platform", "desktop", "--profile", "offline_sealed", "--validate-only"
        )
        self.assertNotEqual(profile_mismatch.returncode, 0)
        self.assertIn("profile binding mismatch", profile_mismatch.stderr)
        rollback = self.run_runtime(None, "--min-release", "6", "--validate-only")
        self.assertNotEqual(rollback.returncode, 0)
        self.assertIn("anti-rollback", rollback.stderr)

    def test_validly_signed_malformed_bytecode_is_rejected(self):
        package = self.module.read_bytes()
        payload_size = struct.unpack_from("<I", package, 8)[0]
        payload = bytearray(package[14 : 14 + payload_size])
        struct.pack_into("<H", payload, 4, 99)
        unsupported = self.directory / "signed-unsupported.pvm"
        unsupported.write_bytes(sign_payload(bytes(payload), self.private_key))
        completed = self.run_runtime(unsupported, "--validate-only")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unsupported bytecode format", completed.stderr)

        struct.pack_into("<H", payload, 4, 5)
        truncated = self.directory / "signed-truncated.pvm"
        truncated.write_bytes(sign_payload(bytes(payload[:32]), self.private_key))
        completed = self.run_runtime(truncated, "--validate-only")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("truncated module", completed.stderr)

    def test_runtime_keeps_bytecode_v1_compatibility(self):
        source = json.loads(self.source.read_text(encoding="utf-8"))
        source["module"]["release"] = 1
        source["module"]["minimum_runtime"] = 1
        source["handlers"].pop("set_name")
        source["handlers"].pop("load_status")
        source["pages"]["main"]["children"] = [
            node
            for node in source["pages"]["main"]["children"]
            if node["id"] not in ("counter_load_status", "counter_name")
        ]
        v1_source = self.directory / "legacy-v1.pvm.json"
        v1_source.write_text(json.dumps(source), encoding="utf-8")
        v1_module = self.directory / "legacy-v1.pvm"
        compile_file(v1_source, self.private_key, v1_module, format_version=1)
        completed = self.run_runtime(v1_module, "--validate-only")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("release 1", completed.stdout)

    def test_profile_policy_is_a_compile_constraint(self):
        source = json.loads(self.source.read_text(encoding="utf-8"))
        source["delivery"] = {
            "profile": "store_on_demand",
            "platform": "ios",
            "native_dynamic_download": True,
        }
        with self.assertRaisesRegex(CompileError, "forbids native dynamic"):
            Compiler(source).build()
        source["delivery"] = {
            "profile": "offline_sealed",
            "platform": "android",
            "startup_dependencies_bundled": False,
        }
        with self.assertRaisesRegex(CompileError, "startup_dependencies_bundled"):
            Compiler(source).build()
        source = json.loads(self.source.read_text(encoding="utf-8"))
        source["module"]["application_id"] = "../../escaped"
        with self.assertRaisesRegex(CompileError, "unsafe characters"):
            Compiler(source).build()
        source = json.loads(self.source.read_text(encoding="utf-8"))
        source["module"]["minimum_runtime"] = 2
        with self.assertRaisesRegex(CompileError, "at least the bytecode format"):
            Compiler(source, format_version=5).build()

    def test_event_value_requires_bytecode_v5_and_is_type_checked(self):
        source = json.loads(self.source.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(CompileError, "requires bytecode format 5"):
            Compiler(source, format_version=4).build()
        broken = json.loads(self.source.read_text(encoding="utf-8"))
        broken["handlers"]["set_name"][1]["name"] = "count"
        with self.assertRaisesRegex(CompileError, "type error"):
            Compiler(broken).build()
        wrong_event = json.loads(self.source.read_text(encoding="utf-8"))
        wrong_event["pages"]["main"]["children"][-1]["events"] = {"tap": "set_name"}
        with self.assertRaisesRegex(CompileError, "only handle change or submit"):
            Compiler(wrong_event).build()

    def test_capabilities_generate_platform_packaging_declarations(self):
        source = json.loads(self.source.read_text(encoding="utf-8"))
        manifest = generate_host_manifest(source)
        self.assertEqual(manifest["android"]["usesPermissions"], [])
        self.assertEqual(
            manifest["capabilityVersions"], {"storage.kv": 1, "ui.toast": 1}
        )
        source["module"]["capabilities"].append("network.http")
        source["module"]["network_domains"] = ["api.example.com"]
        manifest = generate_host_manifest(source)
        self.assertIn("android.permission.INTERNET", manifest["android"]["usesPermissions"])
        self.assertIn("ohos.permission.INTERNET", manifest["harmony"]["requestPermissions"])
        source["module"]["capabilities"].append("camera.capture")
        with self.assertRaisesRegex(CompileError, "NSCameraUsageDescription"):
            generate_host_manifest(source)

    def test_release_rejects_newer_capability_than_host_idl(self):
        source = json.loads(self.source.read_text(encoding="utf-8"))
        source["module"]["capability_versions"]["storage.kv"] = 2
        incompatible = self.directory / "incompatible-capability.json"
        incompatible.write_text(json.dumps(source), encoding="utf-8")
        with self.assertRaisesRegex(CompileError, "requires 2 but IDL provides 1"):
            publish(incompatible, self.private_key, self.directory / "incompatible-repository")

    def test_generated_host_idl_is_current(self):
        host_idl = load_host_idl(ROOT / "spec" / "host_idl.json")
        check_outputs(host_idl, ROOT / "generated" / "host")
        lint_source(json.loads(self.source.read_text(encoding="utf-8")), host_idl)
        check_renderer_conformance(ROOT / "spec" / "renderer_conformance.json")

    def test_five_domain_historical_matrix_compiles(self):
        base = json.loads(self.source.read_text(encoding="utf-8"))
        domains = json.loads(
            (ROOT / "server" / "sample" / "domain-matrix.json").read_text(encoding="utf-8")
        )
        built = [
            (domain, version, len(Compiler(source, format_version=version).build()))
            for domain, version, source in compatibility_variants(base, domains)
        ]
        self.assertEqual(len(built), 15)
        self.assertTrue(all(size > 0 for _, _, size in built))

    def test_release_string_scan_rejects_plaintext_leak(self):
        scan_strings(self.module, ["increment", "counter_root", str(self.source)])
        leaked = self.directory / "leaked.pvm"
        leaked.write_bytes(self.module.read_bytes() + b"counter_root")
        with self.assertRaisesRegex(CompileError, "forbidden plaintext"):
            scan_strings(leaked, ["counter_root"])

    def test_http_provisioning_and_last_known_good(self):
        repository = self.directory / "repository"
        first_publish = publish(self.source, self.private_key, repository)
        self.assertEqual(first_publish, publish(self.source, self.private_key, repository))
        offline_source = json.loads(self.source.read_text(encoding="utf-8"))
        offline_source["delivery"] = {
            "profile": "offline_sealed",
            "platform": "desktop",
            "startup_dependencies_bundled": True,
        }
        offline_path = self.directory / "offline-public.json"
        offline_path.write_text(json.dumps(offline_source), encoding="utf-8")
        publish(offline_path, self.private_key, repository)
        server = ModuleServer(("127.0.0.1", 0), repository, "test-token")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        manifest = json.loads(
            (
                repository
                / "apps/com.example.protected/enterprise/desktop/"
                "online_provisioned/manifest.json"
            ).read_text(encoding="utf-8")
        )
        manifest = payload_from_control(manifest)
        module_url = (
            "http://127.0.0.1:%d%s"
            % (server.server_address[1], manifest["module_url"])
        )
        with self.assertRaises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(module_url)
        self.assertEqual(denied.exception.code, 401)
        with urllib.request.urlopen(
            urllib.request.Request(
                module_url, headers={"Authorization": "Bearer test-token"}
            )
        ) as protected_module:
            self.assertTrue(
                protected_module.headers["Cache-Control"].startswith("private")
            )
        public_manifest = json.loads(
            (
                repository
                / "apps/com.example.protected/enterprise/desktop/offline_sealed/manifest.json"
            ).read_text(encoding="utf-8")
        )
        public_manifest = payload_from_control(public_manifest)
        with urllib.request.urlopen(
            "http://127.0.0.1:%d%s"
            % (server.server_address[1], public_manifest["module_url"])
        ) as public_module:
            self.assertEqual(public_module.status, 200)
            self.assertTrue(public_module.headers["Cache-Control"].startswith("public"))
        cache = self.directory / "cache"
        command = [
            sys.executable,
            str(ROOT / "client" / "tools" / "provision.py"),
            "--server",
            "http://127.0.0.1:%d" % server.server_address[1],
            "--app-id",
            "com.example.protected",
            "--channel",
            "enterprise",
            "--profile",
            "online_provisioned",
            "--platform",
            "desktop",
            "--token",
            "test-token",
            "--cache",
            str(cache),
            "--runtime",
            str(self.runtime),
            "--public-key",
            str(self.public_key),
        ]
        first = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        module_path = Path(first.stdout.strip())
        self.assertTrue(module_path.is_file())
        wrong_binding = command.copy()
        wrong_binding[wrong_binding.index("enterprise")] = "other"
        rejected_fallback = subprocess.run(
            wrong_binding, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        self.assertNotEqual(rejected_fallback.returncode, 0)
        self.assertNotIn("last-known-good", rejected_fallback.stderr)
        online_manifest_path = (
            repository
            / "apps/com.example.protected/enterprise/desktop/"
            "online_provisioned/manifest.json"
        )
        valid_manifest = online_manifest_path.read_text(encoding="utf-8")
        invalid_manifest = json.loads(valid_manifest)
        tampered_payload = decode_envelope(invalid_manifest["current"])[0]
        tampered_payload["module_url"] = "/v1/modules/" + ("0" * 64) + ".pvm"
        invalid_manifest["current"]["payload"] = base64.b64encode(
            encode_payload(tampered_payload)
        ).decode("ascii")
        online_manifest_path.write_text(json.dumps(invalid_manifest), encoding="utf-8")
        rejected_update = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        self.assertEqual(rejected_update.returncode, 0, rejected_update.stderr)
        self.assertEqual(Path(rejected_update.stdout.strip()), module_path)
        self.assertIn("module refresh failed", rejected_update.stderr)
        online_manifest_path.write_text(valid_manifest, encoding="utf-8")

        first_install_floor = command.copy()
        first_install_floor[first_install_floor.index(str(cache))] = str(
            self.directory / "floor-cache"
        )
        first_install_floor.extend(["--minimum-release", "6"])
        rejected_first_install = subprocess.run(
            first_install_floor,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertNotEqual(rejected_first_install.returncode, 0)
        self.assertIn("anti-rollback", rejected_first_install.stderr)
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        offline = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(offline.returncode, 0, offline.stderr)
        self.assertEqual(Path(offline.stdout.strip()), module_path)
        self.assertIn("last-known-good", offline.stderr)

    def test_rollout_is_stable_and_audited(self):
        repository = self.directory / "rollout-repository"
        publish(self.source, self.private_key, repository)
        source = json.loads(self.source.read_text(encoding="utf-8"))
        source["module"]["release"] = 6
        next_source = self.directory / "rollout-next.json"
        next_source.write_text(json.dumps(source), encoding="utf-8")
        publish(next_source, self.private_key, repository)
        manifest_path = (
            repository
            / "apps/com.example.protected/enterprise/desktop/online_provisioned/manifest.json"
        )
        set_rollout(manifest_path, 0)
        audit = self.directory / "module-audit.jsonl"
        server = ModuleServer(("127.0.0.1", 0), repository, "test-token", audit_path=audit)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = (
            "http://127.0.0.1:%d/v1/apps/com.example.protected/enterprise/"
            "desktop/online_provisioned/manifest" % server.server_address[1]
        )
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": "Bearer test-token",
                "X-PVM-Installation-ID": "stable-device",
            },
        )
        with urllib.request.urlopen(request) as response:
            self.assertEqual(decode_envelope(json.load(response))[0]["release"], 5)
        set_rollout(manifest_path, 100)
        with urllib.request.urlopen(request) as response:
            self.assertEqual(decode_envelope(json.load(response))[0]["release"], 6)
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        events = [json.loads(line)["event"] for line in audit.read_text().splitlines()]
        self.assertEqual(events, ["manifest", "manifest"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
