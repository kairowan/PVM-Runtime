"""Signed release-manifest envelopes shared by publishing and serving."""

import base64
import binascii
import json

from .compiler import CompileError, sign_detached


def encode_payload(payload):
    return (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def create_envelope(payload, private_key=None, signer_command=None):
    encoded = encode_payload(payload)
    signature = sign_detached(encoded, private_key, signer_command)
    return {
        "envelope_format": 1,
        "payload": base64.b64encode(encoded).decode("ascii"),
        "signature": base64.b64encode(signature).decode("ascii"),
        "signature_algorithm": "Ed25519",
    }


def decode_envelope(envelope):
    if (
        not isinstance(envelope, dict)
        or envelope.get("envelope_format") != 1
        or envelope.get("signature_algorithm") != "Ed25519"
        or not isinstance(envelope.get("payload"), str)
        or not isinstance(envelope.get("signature"), str)
    ):
        raise CompileError("invalid signed manifest envelope")
    try:
        encoded = base64.b64decode(envelope["payload"], validate=True)
        signature = base64.b64decode(envelope["signature"], validate=True)
        payload = json.loads(encoded.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CompileError("invalid signed manifest encoding: %s" % error)
    if len(signature) != 64 or not isinstance(payload, dict):
        raise CompileError("invalid signed manifest payload or signature")
    if encode_payload(payload) != encoded:
        raise CompileError("signed manifest payload is not canonical")
    return payload, encoded, signature


def payload_from_control(control):
    if isinstance(control, dict) and control.get("control_format") == 1:
        return decode_envelope(control.get("current"))[0]
    if not isinstance(control, dict):
        raise CompileError("invalid manifest control")
    return legacy_payload(control)


def legacy_payload(manifest):
    return {
        key: value
        for key, value in manifest.items()
        if key not in ("previous", "rollout_percentage")
    }
