#!/usr/bin/env python3
"""Compile the deliberately small v1 application DSL into signed PVM bytecode."""

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import tempfile
from collections import deque
from pathlib import Path


FORMAT_VERSION = 5
RUNTIME_VERSION = 5

PROFILES = {
    "offline_sealed": 1,
    "online_provisioned": 2,
    "store_on_demand": 3,
    "enterprise_managed": 4,
}
PLATFORMS = {"android": 1, "ios": 2, "harmonyos": 3, "desktop": 4}
VALUE_TYPES = {"int": 1, "bool": 2, "string": 3}
NODE_TYPES = {
    "text": 1,
    "image": 2,
    "row": 3,
    "column": 4,
    "stack": 5,
    "scroll": 6,
    "list": 7,
    "button": 8,
    "input": 9,
    "switch": 10,
    "native_surface": 11,
}
PROPERTY_KEYS = {
    "text": 1,
    "source": 2,
    "accessibility_label": 3,
    "enabled": 4,
    "value": 5,
    "surface_type": 6,
}
EVENT_TYPES = {"tap": 1, "change": 2, "submit": 3, "appear": 4}
OPS = {
    "const": 1,
    "state.get": 4,
    "state.set": 5,
    "int.add": 6,
    "equal": 7,
    "jump": 8,
    "jump_if_false": 9,
    "effect": 10,
    "pop": 11,
    "render": 12,
    "halt": 13,
    "effect.async": 14,
    "event.value": 15,
}


class CompileError(ValueError):
    pass


class Writer:
    def __init__(self):
        self.data = bytearray()

    def u8(self, value):
        self.data += struct.pack("<B", value)

    def u16(self, value):
        self.data += struct.pack("<H", value)

    def u32(self, value):
        self.data += struct.pack("<I", value)

    def u64(self, value):
        self.data += struct.pack("<Q", value)

    def i64(self, value):
        self.data += struct.pack("<q", value)

    def text(self, value):
        raw = value.encode("utf-8")
        if len(raw) > 65535:
            raise CompileError("string exceeds 65535 UTF-8 bytes")
        self.u16(len(raw))
        self.data += raw


def require(condition, message):
    if not condition:
        raise CompileError(message)


def fnv1a32(value):
    result = 2166136261
    for byte in value.encode("utf-8"):
        result = ((result ^ byte) * 16777619) & 0xFFFFFFFF
    return result


def find_openssl():
    candidates = (
        os.environ.get("PVM_OPENSSL"),
        "/opt/homebrew/opt/openssl@3/bin/openssl",
        "/usr/local/opt/openssl@3/bin/openssl",
        shutil.which("openssl"),
    )
    return next((candidate for candidate in candidates if candidate and Path(candidate).is_file()), None)


def validate_policy(source):
    module = source.get("module", {})
    delivery = source.get("delivery", {})
    profile = delivery.get("profile")
    platform = delivery.get("platform")
    require(profile in PROFILES, "delivery.profile must be one of: " + ", ".join(PROFILES))
    require(platform in PLATFORMS, "delivery.platform must be one of: " + ", ".join(PLATFORMS))

    if profile == "offline_sealed":
        require(
            delivery.get("startup_dependencies_bundled") is True,
            "Offline Sealed requires startup_dependencies_bundled=true",
        )
    if profile == "online_provisioned":
        require(
            delivery.get("fallback_ui") is True,
            "Online Provisioned requires fallback_ui=true",
        )
    if profile == "store_on_demand" and platform == "ios":
        require(
            delivery.get("native_dynamic_download") is not True,
            "Apple Store profile forbids native dynamic downloads",
        )
    if profile == "store_on_demand" and platform == "android":
        forbidden = (".dex", ".jar", ".so")
        artifacts = delivery.get("external_code_artifacts", [])
        rejected = [name for name in artifacts if str(name).lower().endswith(forbidden)]
        require(not rejected, "Google Play profile forbids external DEX/JAR/SO: " + ", ".join(rejected))

    required = ["id", "application_id", "tenant", "channel", "release"]
    for key in required:
        require(key in module, "module.%s is required" % key)
    for key in ("id", "application_id", "tenant", "channel"):
        require(
            isinstance(module[key], str) and 0 < len(module[key].encode("utf-8")) <= 255,
            "module.%s must be a non-empty string of at most 255 UTF-8 bytes" % key,
        )
        require(
            module[key] not in (".", "..")
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}", module[key]) is not None,
            "module.%s contains unsafe characters" % key,
        )
    require(isinstance(module["release"], int) and module["release"] > 0, "module.release must be positive")
    require(
        isinstance(module.get("key_version", 1), int) and module.get("key_version", 1) > 0,
        "module.key_version must be positive",
    )
    require(
        module.get("minimum_runtime", 1) <= RUNTIME_VERSION,
        "module.minimum_runtime is newer than this compiler/runtime",
    )
    capabilities = module.get("capabilities", [])
    require(
        isinstance(capabilities, list)
        and all(isinstance(value, str) for value in capabilities)
        and len(capabilities) == len(set(capabilities))
        and all(
            re.fullmatch(r"[a-z][a-z0-9]*(?:[._][A-Za-z][A-Za-z0-9]*)+", value)
            is not None
            for value in capabilities
        ),
        "module.capabilities must be a unique safe identifier list",
    )
    capability_versions = module.get("capability_versions", {})
    require(
        isinstance(capability_versions, dict)
        and set(capability_versions).issubset(capabilities)
        and all(
            isinstance(value, int) and not isinstance(value, bool) and 0 < value <= 65535
            for value in capability_versions.values()
        ),
        "module.capability_versions must map declared capabilities to versions in [1, 65535]",
    )
    if any(value.startswith("network.") for value in capabilities):
        require(
            bool(module.get("network_domains")),
            "network capabilities require at least one module.network_domains entry",
        )
    if any(value.startswith("storage.") for value in capabilities):
        require(
            bool(module.get("storage_scopes")),
            "storage capabilities require at least one module.storage_scopes entry",
        )
    domains = module.get("network_domains", [])
    require(
        isinstance(domains, list)
        and all(isinstance(value, str) for value in domains)
        and len(domains) == len(set(domains))
        and all(
            len(value) <= 253
            and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value)
            is not None
            and ".." not in value
            for value in domains
        ),
        "module.network_domains must be a unique hostname list",
    )
    scopes = module.get("storage_scopes", [])
    require(
        isinstance(scopes, list)
        and all(isinstance(value, str) for value in scopes)
        and len(scopes) == len(set(scopes))
        and all(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}", value) is not None
            and value not in (".", "..")
            for value in scopes
        ),
        "module.storage_scopes must be a unique safe identifier list",
    )


class Compiler:
    def __init__(self, source, format_version=FORMAT_VERSION):
        validate_policy(source)
        require(
            format_version in (1, 2, 3, 4, 5),
            "compiler supports bytecode formats 1, 2, 3, 4, and 5",
        )
        self.source = source
        self.format_version = format_version
        self.constants = []
        self.constant_ids = {}
        self.state_names = sorted(source.get("state", {}))
        self.state_ids = {name: i for i, name in enumerate(self.state_names)}
        if format_version >= 4:
            require(
                all(
                    isinstance(source["state"][name].get("persistence_id"), str)
                    for name in self.state_names
                ),
                "bytecode v4 requires an explicit persistence_id for every state field",
            )
        persistence_names = [
            source["state"][name].get("persistence_id", name) for name in self.state_names
        ]
        require(
            all(
                isinstance(value, str)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}", value)
                is not None
                for value in persistence_names
            ),
            "state persistence_id must be a safe non-empty identifier",
        )
        require(
            len(persistence_names) == len(set(persistence_names)),
            "state persistence_id values must be unique",
        )
        identity_prefix = "%s\x00%s\x00" % (
            source["module"]["application_id"],
            source["module"]["id"],
        )
        self.state_persistence_ids = [
            int.from_bytes(
                hashlib.sha256((identity_prefix + value).encode("utf-8")).digest()[:8],
                "little",
            )
            for value in persistence_names
        ]
        require(
            0 not in self.state_persistence_ids
            and len(self.state_persistence_ids) == len(set(self.state_persistence_ids)),
            "state persistence_id hash collision",
        )
        self.page_names = sorted(source.get("pages", {}))
        self.page_ids = {name: i for i, name in enumerate(self.page_names)}
        self.handler_names = sorted(source.get("handlers", {}))
        self.handler_ids = {name: i for i, name in enumerate(self.handler_names)}
        self.capabilities = sorted(set(source.get("module", {}).get("capabilities", [])))
        self.capability_ids = {name: i for i, name in enumerate(self.capabilities)}
        versions = source.get("module", {}).get("capability_versions", {})
        self.capability_versions = [versions.get(name, 1) for name in self.capabilities]
        self.node_ids = set()
        self.node_count = 0
        self.event_value_handlers = set()

    def intern(self, value):
        require(isinstance(value, str), "only strings may enter the constant pool")
        if value not in self.constant_ids:
            self.constant_ids[value] = len(self.constants)
            self.constants.append(value)
        return self.constant_ids[value]

    def build(self):
        states = self._states()
        handlers = self._handlers(states)
        pages = [self._node(self.source["pages"][name]) for name in self.page_names]
        self._validate_event_value_bindings()
        module = self.source["module"]
        delivery = self.source["delivery"]
        require(
            int(module.get("minimum_runtime", 1)) >= self.format_version,
            "module.minimum_runtime must be at least the bytecode format version",
        )
        budget = module.get("budget", {})
        limits = {
            "max_instructions_per_event": int(budget.get("max_instructions_per_event", 1000)),
            "max_stack": int(budget.get("max_stack", 64)),
            "max_state_bytes": int(budget.get("max_state_bytes", 65536)),
            "max_ui_nodes": int(budget.get("max_ui_nodes", 1000)),
            "max_tasks": int(budget.get("max_tasks", 64)),
        }
        for key, value in limits.items():
            require(0 < value <= 10_000_000, "invalid module.budget.%s" % key)
        require(self.node_count <= limits["max_ui_nodes"], "UI node budget exceeded at compile time")
        require(len(self.state_names) <= 4096, "too many state slots")
        require(len(self.handler_names) <= 4096, "too many handlers")

        entry_page = module.get("entry_page")
        require(entry_page in self.page_ids, "module.entry_page must name an existing page")
        entry_handler = module.get("entry_handler")
        require(entry_handler is None or entry_handler in self.handler_ids, "unknown module.entry_handler")

        writer = Writer()
        writer.data += b"PVBC"
        writer.u16(self.format_version)
        writer.u16(int(module.get("minimum_runtime", 1)))
        writer.u64(module["release"])
        writer.u8(PROFILES[delivery["profile"]])
        writer.u8(PLATFORMS[delivery["platform"]])
        writer.text(module["id"])
        writer.text(module["application_id"])
        writer.text(module["tenant"])
        writer.text(module["channel"])
        schema_material = json.dumps(
            {
                "application_id": module["application_id"],
                "module_id": module["id"],
                "state": [
                    [
                        self.source["state"][name].get("persistence_id", name),
                        self.source["state"][name]["type"],
                    ]
                    for name in self.state_names
                ],
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        writer.u64(int.from_bytes(hashlib.sha256(schema_material).digest()[:8], "little"))
        writer.u32(module.get("key_version", 1))
        budget_keys = [
            "max_instructions_per_event",
            "max_stack",
            "max_state_bytes",
            "max_ui_nodes",
        ]
        if self.format_version >= 2:
            budget_keys.append("max_tasks")
        for key in budget_keys:
            writer.u32(limits[key])

        self._write_text_list(writer, self.capabilities)
        if self.format_version >= 3:
            for version in self.capability_versions:
                writer.u16(version)
        self._write_text_list(writer, sorted(set(module.get("network_domains", []))))
        self._write_text_list(writer, sorted(set(module.get("storage_scopes", []))))
        self._write_text_list(writer, self.constants)

        writer.u16(len(states))
        for index, (value_type, initial) in enumerate(states):
            if self.format_version >= 4:
                writer.u64(self.state_persistence_ids[index])
            writer.u8(value_type)
            if value_type == VALUE_TYPES["int"]:
                writer.i64(initial)
            elif value_type == VALUE_TYPES["bool"]:
                writer.u8(1 if initial else 0)
            else:
                writer.u16(initial)

        writer.u16(len(handlers))
        for instructions in handlers:
            writer.u32(len(instructions))
            for instruction in instructions:
                self._write_instruction(writer, instruction)

        writer.u16(len(pages))
        for page in pages:
            self._write_node(writer, page)
        writer.u16(self.page_ids[entry_page])
        writer.u16(0xFFFF if entry_handler is None else self.handler_ids[entry_handler])
        return bytes(writer.data)

    def _write_text_list(self, writer, values):
        require(len(values) <= 65535, "table has too many entries")
        writer.u16(len(values))
        for value in values:
            writer.text(value)

    def _states(self):
        states = []
        for name in self.state_names:
            spec = self.source["state"][name]
            value_type = spec.get("type")
            require(value_type in VALUE_TYPES, "state %s has unsupported type" % name)
            initial = spec.get("initial")
            if value_type == "int":
                require(isinstance(initial, int) and not isinstance(initial, bool), "state %s must be int" % name)
                require(-(2**63) <= initial < 2**63, "state %s is outside signed 64-bit range" % name)
                encoded = initial
            elif value_type == "bool":
                require(isinstance(initial, bool), "state %s must be bool" % name)
                encoded = initial
            else:
                require(isinstance(initial, str), "state %s must be string" % name)
                encoded = self.intern(initial)
            states.append((VALUE_TYPES[value_type], encoded))
        return states

    def _handlers(self, states):
        result = []
        state_types = [item[0] for item in states]
        for name in self.handler_names:
            raw = self.source["handlers"][name]
            require(isinstance(raw, list), "handler %s must be an instruction list" % name)
            instructions = [self._instruction(item) for item in raw]
            if any(item[0] == OPS["event.value"] for item in instructions):
                self.event_value_handlers.add(name)
            if not instructions or instructions[-1][0] != OPS["halt"]:
                instructions.append((OPS["halt"],))
            self._check_handler(name, instructions, state_types)
            result.append(instructions)
        return result

    def _validate_event_value_bindings(self):
        if not self.event_value_handlers:
            return
        entry = self.source["module"].get("entry_handler")
        require(
            entry not in self.event_value_handlers,
            "module.entry_handler cannot use event.value",
        )
        bindings = {name: [] for name in self.event_value_handlers}

        def visit(node):
            for event, handler in node.get("events", {}).items():
                if handler in bindings:
                    bindings[handler].append(event)
            for child in node.get("children", []):
                visit(child)

        for page in self.source.get("pages", {}).values():
            visit(page)
        for handler, events in bindings.items():
            require(events, "handler %s uses event.value but is not bound to a UI event" % handler)
            require(
                all(event in ("change", "submit") for event in events),
                "handler %s uses event.value and may only handle change or submit" % handler,
            )

    def _instruction(self, item):
        require(isinstance(item, dict), "instruction must be an object")
        name = item.get("op")
        require(name in OPS, "unsupported instruction: %r" % name)
        require(
            self.format_version >= 2 or name != "effect.async",
            "effect.async requires bytecode format 2",
        )
        require(
            self.format_version >= 5 or name != "event.value",
            "event.value requires bytecode format 5",
        )
        op = OPS[name]
        if name == "const":
            value = item.get("value")
            if isinstance(value, bool):
                return (op, VALUE_TYPES["bool"], value)
            if isinstance(value, int):
                require(-(2**63) <= value < 2**63, "integer constant is outside signed 64-bit range")
                return (op, VALUE_TYPES["int"], value)
            require(isinstance(value, str), "const supports int, bool, or string")
            return (op, VALUE_TYPES["string"], self.intern(value))
        if name in ("state.get", "state.set"):
            state = item.get("name")
            require(state in self.state_ids, "unknown state: %r" % state)
            return (op, self.state_ids[state])
        if name in ("jump", "jump_if_false"):
            target = item.get("target")
            require(isinstance(target, int) and target >= 0, "%s target must be an instruction index" % name)
            return (op, target)
        if name in ("effect", "effect.async"):
            capability = item.get("capability")
            require(capability in self.capability_ids, "undeclared capability: %r" % capability)
            operation = item.get("operation")
            argc = item.get("args", 0)
            require(isinstance(operation, str) and operation, "effect.operation is required")
            require(isinstance(argc, int) and 0 <= argc <= 32, "effect.args must be in [0, 32]")
            return (op, self.capability_ids[capability], self.intern(operation), argc)
        if name == "render":
            page = item.get("page")
            require(page in self.page_ids, "unknown page: %r" % page)
            return (op, self.page_ids[page])
        return (op,)

    def _check_handler(self, name, instructions, state_types):
        count = len(instructions)
        incoming = {0: ()}
        queue = deque([0])
        while queue:
            pc = queue.popleft()
            stack = list(incoming[pc])
            instruction = instructions[pc]
            op = instruction[0]

            def pop(expected=None):
                require(stack, "handler %s underflows the stack at instruction %d" % (name, pc))
                actual = stack.pop()
                require(expected is None or actual == expected, "handler %s has a type error at instruction %d" % (name, pc))
                return actual

            if op == OPS["const"]:
                stack.append(instruction[1])
            elif op == OPS["event.value"]:
                stack.append(VALUE_TYPES["string"])
            elif op == OPS["state.get"]:
                stack.append(state_types[instruction[1]])
            elif op == OPS["state.set"]:
                pop(state_types[instruction[1]])
            elif op == OPS["int.add"]:
                pop(VALUE_TYPES["int"])
                pop(VALUE_TYPES["int"])
                stack.append(VALUE_TYPES["int"])
            elif op == OPS["equal"]:
                right = pop()
                require(pop() == right, "handler %s compares different types at instruction %d" % (name, pc))
                stack.append(VALUE_TYPES["bool"])
            elif op == OPS["jump_if_false"]:
                pop(VALUE_TYPES["bool"])
            elif op in (OPS["effect"], OPS["effect.async"]):
                for _ in range(instruction[3]):
                    pop()
                stack.append(VALUE_TYPES["string"])
            elif op == OPS["pop"]:
                pop()
            elif op == OPS["halt"]:
                require(not stack, "handler %s must have an empty stack at halt" % name)

            successors = []
            if op == OPS["jump"]:
                successors.append(instruction[1])
            elif op == OPS["jump_if_false"]:
                successors.extend((instruction[1], pc + 1))
            elif op != OPS["halt"]:
                successors.append(pc + 1)
            for target in successors:
                require(0 <= target < count, "handler %s jumps outside its instruction table" % name)
                next_stack = tuple(stack)
                if target in incoming:
                    require(incoming[target] == next_stack, "handler %s has incompatible branch stack shapes" % name)
                else:
                    incoming[target] = next_stack
                    queue.append(target)
        require(any(ins[0] == OPS["halt"] for ins in instructions), "handler %s has no halt" % name)

    def _segments(self, value):
        if isinstance(value, (int, bool)):
            value = str(value).lower() if isinstance(value, bool) else str(value)
        require(isinstance(value, str), "UI properties must be strings, numbers, or booleans")
        segments = []
        position = 0
        for match in re.finditer(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", value):
            if match.start() > position:
                segments.append((1, self.intern(value[position : match.start()])))
            state = match.group(1)
            require(state in self.state_ids, "UI template references unknown state: %s" % state)
            segments.append((2, self.state_ids[state]))
            position = match.end()
        if position < len(value) or not segments:
            segments.append((1, self.intern(value[position:])))
        return segments

    def _node(self, source):
        require(isinstance(source, dict), "UI node must be an object")
        node_type = source.get("type")
        require(node_type in NODE_TYPES, "unsupported UI node type: %r" % node_type)
        source_id = source.get("id")
        require(isinstance(source_id, str) and source_id, "every UI node requires a stable id")
        node_id = fnv1a32(source_id)
        require(node_id not in self.node_ids, "UI node id hash collision: %s" % source_id)
        self.node_ids.add(node_id)
        self.node_count += 1

        props = []
        for key in sorted(source.get("props", {})):
            require(key in PROPERTY_KEYS, "unsupported property: %s" % key)
            props.append((PROPERTY_KEYS[key], self._segments(source["props"][key])))
        events = []
        for event in sorted(source.get("events", {})):
            handler = source["events"][event]
            require(event in EVENT_TYPES, "unsupported event: %s" % event)
            require(handler in self.handler_ids, "unknown event handler: %s" % handler)
            events.append((EVENT_TYPES[event], self.handler_ids[handler]))
        children = [self._node(child) for child in source.get("children", [])]
        return (NODE_TYPES[node_type], node_id, props, events, children)

    def _write_instruction(self, writer, instruction):
        op = instruction[0]
        writer.u8(op)
        if op == OPS["const"]:
            writer.u8(instruction[1])
            if instruction[1] == VALUE_TYPES["int"]:
                writer.i64(instruction[2])
            elif instruction[1] == VALUE_TYPES["bool"]:
                writer.u8(1 if instruction[2] else 0)
            else:
                writer.u16(instruction[2])
        elif op in (OPS["state.get"], OPS["state.set"], OPS["render"]):
            writer.u16(instruction[1])
        elif op in (OPS["jump"], OPS["jump_if_false"]):
            writer.u32(instruction[1])
        elif op in (OPS["effect"], OPS["effect.async"]):
            writer.u16(instruction[1])
            writer.u16(instruction[2])
            writer.u8(instruction[3])

    def _write_node(self, writer, node):
        node_type, node_id, props, events, children = node
        writer.u8(node_type)
        writer.u32(node_id)
        writer.u16(len(props))
        for key, segments in props:
            writer.u8(key)
            writer.u16(len(segments))
            for kind, index in segments:
                writer.u8(kind)
                writer.u16(index)
        writer.u16(len(events))
        for event, handler in events:
            writer.u8(event)
            writer.u16(handler)
        writer.u16(len(children))
        for child in children:
            self._write_node(writer, child)


def sign_detached(payload, private_key=None, signer_command=None):
    if signer_command:
        command = shlex.split(signer_command) if isinstance(signer_command, str) else signer_command
        completed = subprocess.run(
            command, input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if completed.returncode:
            raise CompileError(
                "remote signer failed: "
                + completed.stderr.decode("utf-8", errors="replace").strip()
            )
        signature = completed.stdout
    else:
        require(private_key is not None, "a private key or signer command is required")
        openssl = find_openssl()
        require(openssl is not None, "OpenSSL 3 executable was not found; set PVM_OPENSSL")
        with tempfile.TemporaryDirectory(prefix="pvm-sign-") as directory:
            payload_path = Path(directory) / "payload.bin"
            signature_path = Path(directory) / "signature.bin"
            payload_path.write_bytes(payload)
            command = [
                openssl,
                "pkeyutl",
                "-sign",
                "-rawin",
                "-inkey",
                str(private_key),
                "-in",
                str(payload_path),
                "-out",
                str(signature_path),
            ]
            completed = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            if completed.returncode:
                raise CompileError("OpenSSL signing failed: " + completed.stderr.strip())
            signature = signature_path.read_bytes()
    require(len(signature) == 64, "Ed25519 signature must be 64 bytes")
    return signature


def sign_payload(payload, private_key=None, signer_command=None):
    signature = sign_detached(payload, private_key, signer_command)
    package = Writer()
    package.data += b"PVMP"
    package.u16(1)
    package.u16(1)  # Ed25519
    package.u32(len(payload))
    package.u16(len(signature))
    package.data += payload
    package.data += signature
    return bytes(package.data)


def compile_file(
    source_path, private_key, output_path, format_version=FORMAT_VERSION, signer_command=None
):
    try:
        source = json.loads(Path(source_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CompileError("cannot read DSL source: %s" % error)
    payload = Compiler(source, format_version=format_version).build()
    package = sign_payload(payload, private_key, signer_command)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_bytes(package)
    os.replace(str(temporary), str(output))
    return {
        "sha256": hashlib.sha256(package).hexdigest(),
        "size": len(package),
        "release": source["module"]["release"],
        "application_id": source["module"]["application_id"],
        "channel": source["module"]["channel"],
        "profile": source["delivery"]["profile"],
        "platform": source["delivery"]["platform"],
        "minimum_runtime": source["module"].get("minimum_runtime", 1),
        "bytecode_format": format_version,
        "capability_versions": {
            capability: source["module"].get("capability_versions", {}).get(capability, 1)
            for capability in sorted(set(source["module"].get("capabilities", [])))
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    signing = parser.add_mutually_exclusive_group(required=True)
    signing.add_argument("--private-key", type=Path)
    signing.add_argument(
        "--signer-command",
        help="command that accepts the payload on stdin and returns a raw 64-byte signature",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--format-version", choices=(1, 2, 3, 4, 5), default=FORMAT_VERSION, type=int
    )
    args = parser.parse_args()
    try:
        result = compile_file(
            args.source,
            args.private_key,
            args.output,
            format_version=args.format_version,
            signer_command=args.signer_command,
        )
    except CompileError as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
