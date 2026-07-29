#!/usr/bin/env python3
"""Generate packaging declarations from a DSL capability manifest."""

import argparse
import json
import os
from pathlib import Path

from .compiler import CompileError, validate_policy


ANDROID_PERMISSIONS = {
    "network.http": ["android.permission.INTERNET"],
    "network.transfer": ["android.permission.INTERNET"],
    "network.websocket": ["android.permission.INTERNET"],
    "camera.capture": ["android.permission.CAMERA"],
    "qr.scan": ["android.permission.CAMERA"],
    "location.current": ["android.permission.ACCESS_FINE_LOCATION"],
    "microphone.capture": ["android.permission.RECORD_AUDIO"],
    "notification.post": ["android.permission.POST_NOTIFICATIONS"],
    "push.inbox": ["android.permission.POST_NOTIFICATIONS"],
    "biometric.auth": ["android.permission.USE_BIOMETRIC"],
    "bluetooth.scan": [
        "android.permission.BLUETOOTH_SCAN",
        "android.permission.BLUETOOTH_CONNECT",
    ],
    "nfc.scan": ["android.permission.NFC"],
}
IOS_USAGE_KEYS = {
    "biometric.auth": "NSFaceIDUsageDescription",
    "camera.capture": "NSCameraUsageDescription",
    "location.current": "NSLocationWhenInUseUsageDescription",
    "microphone.capture": "NSMicrophoneUsageDescription",
    "qr.scan": "NSCameraUsageDescription",
}
HARMONY_PERMISSIONS = {
    "network.http": ["ohos.permission.INTERNET"],
    "network.transfer": ["ohos.permission.INTERNET"],
    "network.websocket": ["ohos.permission.INTERNET"],
    "camera.capture": ["ohos.permission.CAMERA"],
    "qr.scan": ["ohos.permission.CAMERA"],
    "location.current": ["ohos.permission.LOCATION"],
    "microphone.capture": ["ohos.permission.MICROPHONE"],
    "notification.post": ["ohos.permission.NOTIFICATION_CONTROLLER"],
}
STORE_DECLARATIONS = {
    "background.task": ["background-execution-purpose"],
    "camera.capture": ["camera-data-use"],
    "location.current": ["location-data-use"],
    "microphone.capture": ["microphone-data-use"],
    "payment.purchase": ["digital-goods-billing"],
    "push.inbox": ["remote-notification-purpose"],
    "system.extension": ["platform-extension-entitlement"],
}


def generate(source):
    validate_policy(source)
    module = source["module"]
    capabilities = sorted(set(module.get("capabilities", [])))
    versions = module.get("capability_versions", {})
    usage = module.get("permission_usage", {})
    android = sorted(
        {
            permission
            for capability in capabilities
            for permission in ANDROID_PERMISSIONS.get(capability, [])
        }
    )
    harmony = sorted(
        {
            permission
            for capability in capabilities
            for permission in HARMONY_PERMISSIONS.get(capability, [])
        }
    )
    ios = {}
    for capability in capabilities:
        key = IOS_USAGE_KEYS.get(capability)
        if key:
            value = usage.get(key)
            if not isinstance(value, str) or not value.strip():
                raise CompileError(
                    "module.permission_usage.%s is required by capability %s"
                    % (key, capability)
                )
            ios[key] = value
    return {
        "android": {"usesPermissions": android},
        "applicationId": module["application_id"],
        "capabilities": capabilities,
        "capabilityVersions": {
            capability: versions.get(capability, 1) for capability in capabilities
        },
        "harmony": {"requestPermissions": harmony},
        "ios": {"infoPlist": ios},
        "networkDomains": sorted(set(module.get("network_domains", []))),
        "platform": source["delivery"]["platform"],
        "reviewDeclarations": sorted(
            {
                declaration
                for capability in capabilities
                for declaration in STORE_DECLARATIONS.get(capability, [])
            }
        ),
        "storageScopes": sorted(set(module.get("storage_scopes", []))),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        source = json.loads(args.source.read_text(encoding="utf-8"))
        manifest = generate(source)
    except (OSError, json.JSONDecodeError, CompileError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    os.replace(str(temporary), str(args.output))
    print(args.output)


if __name__ == "__main__":
    main()
