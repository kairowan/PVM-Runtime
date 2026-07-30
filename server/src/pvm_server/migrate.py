#!/usr/bin/env python3
"""Scan selected legacy code and generate a reviewable PVM migration scaffold."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections import Counter, deque
from pathlib import Path

from .compiler import CompileError, Compiler, PLATFORMS, PROFILES, compile_file
from .host_idl import load as load_host_idl
from .tooling import lint


ROOT = Path(__file__).resolve().parents[3]
SOURCE_LANGUAGES = {
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
    ".ets": "arkts",
}
SKIPPED_DIRECTORIES = {
    ".build",
    ".git",
    ".gradle",
    ".idea",
    "Pods",
    "build",
    "DerivedData",
    "dist",
    "node_modules",
    "vendor",
}
MAX_SOURCE_BYTES = 2 * 1024 * 1024
GENERATED_FILES = {
    "capabilities.json",
    "migration-approvals.json",
    "migration-cases.json",
    "migration-report.json",
    "migration-report.md",
    "module.pvm.json",
    "verification.json",
}

DECLARATIONS = {
    "kotlin": re.compile(
        r"(?m)^[ \t]*(?:(?:public|internal|private|protected|open|abstract|"
        r"sealed|data|enum|annotation|value|expect|actual)\s+)*"
        r"(?P<kind>class|object|interface)\s+(?P<name>[A-Za-z_]\w*)"
    ),
    "java": re.compile(
        r"(?m)^[ \t]*(?:(?:public|private|protected|abstract|static|final|"
        r"sealed|non-sealed|strictfp)\s+)*"
        r"(?P<kind>class|interface|enum|record)\s+(?P<name>[A-Za-z_]\w*)"
    ),
    "swift": re.compile(
        r"(?m)^[ \t]*(?:(?:public|internal|private|fileprivate|open|final|"
        r"indirect|nonisolated)\s+)*"
        r"(?P<kind>class|struct|enum|protocol|actor)\s+(?P<name>[A-Za-z_]\w*)"
    ),
    "arkts": re.compile(
        r"(?m)^[ \t]*(?:@\w+(?:\([^)]*\))?\s*)*"
        r"(?:(?:export|default|abstract|declare)\s+)*"
        r"(?P<kind>class|struct|enum|interface)\s+(?P<name>[A-Za-z_]\w*)"
    ),
}

PACKAGE_PATTERNS = {
    "kotlin": re.compile(r"(?m)^[ \t]*package\s+([A-Za-z_][\w.]*)"),
    "java": re.compile(r"(?m)^[ \t]*package\s+([A-Za-z_][\w.]*)\s*;"),
}
IMPORT_PATTERNS = {
    "kotlin": re.compile(r"(?m)^[ \t]*import\s+([^\s;]+)"),
    "java": re.compile(r"(?m)^[ \t]*import\s+(?:static\s+)?([^;]+)\s*;"),
    "swift": re.compile(r"(?m)^[ \t]*import\s+([A-Za-z_]\w*)"),
    "arkts": re.compile(r"(?m)^[ \t]*import\b[^\n]*?\bfrom\s+['\"]([^'\"]+)['\"]"),
}

STATE_PATTERNS = {
    "kotlin": re.compile(
        r"\bvar\s+(?P<name>[A-Za-z_]\w*)\s*"
        r"(?::\s*(?P<type>[A-Za-z_][\w<>?.]*))?\s*=\s*"
        r"(?P<value>[^;\n]+)"
    ),
    "java": re.compile(
        r"(?m)^[ \t]*(?:(?:public|private|protected|static|transient|volatile)\s+)*"
        r"(?P<type>String|int|long|boolean|Integer|Long|Boolean)\s+"
        r"(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<value>[^;\n]+)"
    ),
    "swift": re.compile(
        r"\bvar\s+(?P<name>[A-Za-z_]\w*)\s*"
        r"(?::\s*(?P<type>String|Int|Int64|Bool))?\s*=\s*"
        r"(?P<value>[^\n]+)"
    ),
    "arkts": re.compile(
        r"(?m)^[ \t]*(?:@\w+(?:\([^)]*\))?[ \t]*)*"
        r"(?:(?:public|private|protected|static|readonly)\s+)*"
        r"(?P<name>[A-Za-z_]\w*)\s*:\s*"
        r"(?P<type>string|number|boolean)\s*=\s*(?P<value>[^;\n]+)"
    ),
}

UI_HINTS = (
    ("text", r"\b(?:Text|TextView|UILabel)\s*(?:\(|\b)"),
    ("button", r"\b(?:Button|UIButton)\s*(?:\(|\b)"),
    ("input", r"\b(?:EditText|TextField|TextInput|UITextField)\s*(?:\(|\b)"),
    ("image", r"\b(?:Image|ImageView|UIImageView)\s*(?:\(|\b)"),
    ("row", r"\b(?:Row|HStack|LinearLayout\.HORIZONTAL)\s*(?:\(|\b)"),
    ("column", r"\b(?:Column|VStack|UIStackView)\s*(?:\(|\b)"),
    ("list", r"\b(?:List|RecyclerView|UITableView)\s*(?:\(|\b)"),
    ("scroll", r"\b(?:Scroll|ScrollView|UIScrollView)\s*(?:\(|\b)"),
    ("stack", r"\b(?:Stack|ZStack|FrameLayout)\s*(?:\(|\b)"),
    ("switch", r"\b(?:Switch|Toggle|UISwitch)\s*(?:\(|\b)"),
)

CAPABILITY_HINTS = (
    ("payment.purchase", r"\b(?:BillingClient|StoreKit|IAP|Purchase|Payment)\b"),
    ("camera.capture", r"\b(?:Camera|AVCapture|ImagePicker)\b"),
    ("location.current", r"\b(?:Location|CoreLocation|CLLocation)\b"),
    ("map.control", r"\b(?:MapView|MapKit|GoogleMap|AMap)\b"),
    ("network.websocket", r"\b(?:WebSocket|URLSessionWebSocketTask)\b"),
    ("network.http", r"\b(?:OkHttp|Retrofit|URLSession|HttpClient|fetch)\b"),
    ("database.scoped", r"\b(?:RoomDatabase|SQLite|CoreData|RelationalStore)\b"),
    ("secure.keystore", r"\b(?:Keychain|KeyStore|HUKS)\b"),
    ("storage.kv", r"\b(?:SharedPreferences|UserDefaults|Preferences)\b"),
    ("notification.post", r"\b(?:NotificationManager|UNUserNotificationCenter)\b"),
    ("push.inbox", r"\b(?:FirebaseMessaging|PushKit|PushService)\b"),
    ("biometric.auth", r"\b(?:BiometricPrompt|LocalAuthentication|UserAuth)\b"),
    ("bluetooth.scan", r"\b(?:Bluetooth|CoreBluetooth)\b"),
    ("media.player", r"\b(?:MediaPlayer|AVPlayer)\b"),
    ("share.system", r"\b(?:ACTION_SEND|UIActivityViewController|ShareController)\b"),
    ("clipboard.system", r"\b(?:ClipboardManager|UIPasteboard|Pasteboard)\b"),
    ("file.scoped", r"\b(?:FileManager|FileInputStream|fileIo)\b"),
)

MANUAL_REVIEW_HINTS = (
    ("reflection", r"\b(?:Class\.forName|NSClassFromString|Mirror|Reflect)\b"),
    ("concurrency", r"\b(?:Thread|CoroutineScope|DispatchQueue|Task|Promise|async|await)\b"),
    ("dynamic_loading", r"\b(?:DexClassLoader|dlopen|loadLibrary|NSBundle)\b"),
    ("custom_drawing", r"\b(?:Canvas|drawRect|CustomPainter|XComponent)\b"),
    ("web_content", r"\b(?:WebView|WKWebView)\b"),
)

SENSITIVE_STATE = re.compile(
    r"(?:api[_-]?key|password|secret|token|private[_-]?key|credential)",
    re.IGNORECASE,
)


class MigrationError(ValueError):
    pass


def _emit_event(enabled, action, stage, status, progress, message, details=None):
    if not enabled:
        return
    event = {
        "schemaVersion": 1,
        "type": "migration.event",
        "action": action,
        "stage": stage,
        "status": status,
        "progress": progress,
        "message": message,
    }
    if details is not None:
        event["details"] = details
    print(json.dumps(event, sort_keys=True), flush=True)


def _line_number(source, offset):
    return source.count("\n", 0, offset) + 1


def _masked(source):
    # ponytail: this dependency-free lexical mask covers ordinary mobile source.
    # Move to compiler ASTs/Tree-sitter if macro-heavy or generated code becomes common.
    pattern = re.compile(
        r'(?s)/\*.*?\*/|//[^\n]*|"""(?:.|\n)*?"""|"(?:\\.|[^"\\])*"|'
        r"'(?:\\.|[^'\\])*'"
    )

    def hide(match):
        return "".join("\n" if character == "\n" else " " for character in match.group())

    return pattern.sub(hide, source)


def _matching_brace(masked, opening):
    depth = 0
    for index in range(opening, len(masked)):
        if masked[index] == "{":
            depth += 1
        elif masked[index] == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return len(masked)


def _safe_relative(path, root):
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve())
    except ValueError as error:
        raise MigrationError(f"path escapes source root: {path}") from error


def _source_files(root):
    diagnostics = []
    files = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if SKIPPED_DIRECTORIES.intersection(relative.parts):
            continue
        if path.suffix not in SOURCE_LANGUAGES or not path.is_file():
            continue
        if path.is_symlink():
            diagnostics.append({"path": relative.as_posix(), "reason": "symlink skipped"})
            continue
        if path.stat().st_size > MAX_SOURCE_BYTES:
            diagnostics.append(
                {"path": relative.as_posix(), "reason": "source exceeds 2 MiB limit"}
            )
            continue
        files.append(path)
    return files, diagnostics


def _units_for_file(path, root):
    language = SOURCE_LANGUAGES[path.suffix]
    relative = path.relative_to(root).as_posix()
    source = path.read_text(encoding="utf-8")
    source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    masked = _masked(source)
    package_match = PACKAGE_PATTERNS.get(language)
    package = ""
    if package_match:
        match = package_match.search(masked)
        package = match.group(1) if match else ""
    imports = sorted(set(IMPORT_PATTERNS[language].findall(source)))
    declarations = list(DECLARATIONS[language].finditer(masked))
    units = []
    for match in declarations:
        opening = masked.find("{", match.end())
        next_declaration = next(
            (candidate.start() for candidate in declarations if candidate.start() > match.start()),
            len(masked),
        )
        if opening < 0 or opening > next_declaration:
            end = source.find("\n", match.end())
            end = len(source) if end < 0 else end
        else:
            end = _matching_brace(masked, opening)
        name = match.group("name")
        start = match.start()
        line = _line_number(source, start)
        qualified = f"{package}.{name}" if package else name
        units.append(
            {
                "id": f"{relative}:{name}@{line}",
                "path": relative,
                "language": language,
                "name": name,
                "qualifiedName": qualified,
                "kind": match.group("kind"),
                "startLine": line,
                "endLine": _line_number(source, end),
                "imports": imports,
                "sourceSha256": source_sha256,
                "_body": source[start:end],
                "_masked": masked[start:end],
            }
        )
    if not declarations:
        units.append(
            {
                "id": f"{relative}:<file>",
                "path": relative,
                "language": language,
                "name": path.stem,
                "qualifiedName": path.stem,
                "kind": "file",
                "startLine": 1,
                "endLine": source.count("\n") + 1,
                "imports": imports,
                "sourceSha256": source_sha256,
                "_body": source,
                "_masked": masked,
            }
        )
    return units


def _literal(value, declared_type):
    value = value.strip().rstrip(",")
    if value in ("true", "false", "True", "False"):
        return "bool", value.lower() == "true", False
    if re.fullmatch(r"-?\d+[lL]?", value):
        return "int", int(value.rstrip("lL")), False
    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in ("'", '"')
        and "$" not in value
        and "\\(" not in value
    ):
        return "string", "", value[1:-1] != ""
    normalized = (declared_type or "").rstrip("?")
    if normalized in ("String", "string"):
        return "string", "", True
    return None


def _state_analysis(unit):
    states = []
    review = []
    source = unit["_body"]
    masked = unit["_masked"]
    for match in STATE_PATTERNS[unit["language"]].finditer(source):
        if not masked[match.start("name") : match.end("name")].strip():
            continue
        name = match.group("name")
        line = unit["startLine"] + _line_number(source, match.start()) - 1
        if SENSITIVE_STATE.search(name):
            review.append({"id": "sensitive_state", "line": line, "token": name})
            continue
        parsed = _literal(match.group("value"), match.groupdict().get("type"))
        if parsed is None:
            review.append({"id": "non_literal_state", "line": line, "token": name})
            continue
        value_type, initial, redacted = parsed
        states.append(
            {
                "name": name,
                "type": value_type,
                "initial": initial,
                "initialRedacted": redacted,
                "line": line,
            }
        )
    unique = {}
    for state in states:
        unique.setdefault(state["name"], state)
    return list(unique.values()), review


def _matches(unit, hints, include_imports=False):
    source = unit["_masked"]
    found = []
    for identifier, pattern in hints:
        match = re.search(pattern, source, re.IGNORECASE)
        from_import = False
        if match is None and include_imports:
            match = re.search(
                pattern,
                "\n".join(unit["imports"]),
                re.IGNORECASE,
            )
            from_import = match is not None
        if match:
            found.append(
                {
                    "id": identifier,
                    "line": (
                        None
                        if from_import
                        else unit["startLine"] + _line_number(source, match.start()) - 1
                    ),
                    "token": match.group(0).strip(),
                }
            )
    return found


def _analyze(unit):
    states, state_review = _state_analysis(unit)
    return {
        **{key: value for key, value in unit.items() if not key.startswith("_")},
        "states": states,
        "uiHints": _matches(unit, UI_HINTS),
        "capabilityHints": _matches(unit, CAPABILITY_HINTS, include_imports=True),
        "manualReview": state_review + _matches(unit, MANUAL_REVIEW_HINTS),
    }


def _module_relative(root, module):
    value = module
    if ":" in value and "/" not in value and "\\" not in value:
        value = value.strip(":").replace(":", "/")
    path = Path(value)
    path = path if path.is_absolute() else root / path
    relative = _safe_relative(path, root)
    if not path.is_dir():
        raise MigrationError(f"module directory does not exist: {module}")
    value = relative.as_posix().rstrip("/")
    return "" if value == "." else value


def _selector_matches(unit, selector):
    normalized = selector.replace("\\", "/")
    if ":" in normalized:
        path, name = normalized.rsplit(":", 1)
        return unit["path"] == path.lstrip("./") and unit["name"] == name
    return normalized in (unit["id"], unit["name"], unit["qualifiedName"])


def scan_project(source_root, classes=(), modules=(), include_dependencies=False):
    root = Path(source_root).resolve()
    if not root.is_dir():
        raise MigrationError(f"source root is not a directory: {source_root}")
    files, diagnostics = _source_files(root)
    units = []
    for path in files:
        try:
            units.extend(_units_for_file(path, root))
        except UnicodeDecodeError:
            diagnostics.append(
                {"path": path.relative_to(root).as_posix(), "reason": "non-UTF-8 source skipped"}
            )
    by_name = {}
    for unit in units:
        by_name.setdefault(unit["name"], []).append(unit)
    for unit in units:
        dependencies = []
        ambiguous = []
        tokens = set(re.findall(r"\b[A-Za-z_]\w*\b", unit["_masked"]))
        for name in sorted(tokens):
            candidates = by_name.get(name, [])
            if len(candidates) == 1 and candidates[0]["id"] != unit["id"]:
                dependencies.append(candidates[0]["id"])
            elif len(candidates) > 1:
                ambiguous.append(
                    {"name": name, "candidates": [item["id"] for item in candidates]}
                )
        unit["localDependencies"] = dependencies
        unit["ambiguousLocalDependencies"] = ambiguous

    selected = {}
    for selector in classes:
        matches = [unit for unit in units if _selector_matches(unit, selector)]
        if not matches:
            raise MigrationError(f"class selector did not match: {selector}")
        if len(matches) > 1:
            choices = ", ".join(unit["id"] for unit in matches)
            raise MigrationError(f"ambiguous class selector {selector}; use one of: {choices}")
        selected[matches[0]["id"]] = matches[0]

    module_paths = [_module_relative(root, module) for module in modules]
    for module in module_paths:
        prefix = f"{module}/" if module else ""
        for unit in units:
            if not prefix or unit["path"].startswith(prefix):
                selected[unit["id"]] = unit

    if not classes and not modules:
        selected = {unit["id"]: unit for unit in units}

    if include_dependencies:
        pending = deque(selected)
        by_id = {unit["id"]: unit for unit in units}
        while pending:
            current = by_id[pending.popleft()]
            for dependency in current["localDependencies"]:
                if dependency not in selected:
                    selected[dependency] = by_id[dependency]
                    pending.append(dependency)

    analyzed = []
    selected_ids = set(selected)
    for unit in sorted(selected.values(), key=lambda item: item["id"]):
        item = _analyze(unit)
        item["unselectedLocalDependencies"] = [
            dependency
            for dependency in item["localDependencies"]
            if dependency not in selected_ids
        ]
        analyzed.append(item)
    review_count = sum(
        len(unit["uiHints"])
        + len(unit["capabilityHints"])
        + len(unit["manualReview"])
        + sum(1 for state in unit["states"] if state["initialRedacted"])
        + len(unit["unselectedLocalDependencies"])
        + len(unit["ambiguousLocalDependencies"])
        for unit in analyzed
    )
    return {
        "schemaVersion": 1,
        "scannerVersion": 1,
        "sourceRoot": root.name,
        "selection": {
            "classes": list(classes),
            "modules": module_paths,
            "includeDependencies": bool(include_dependencies),
        },
        "summary": {
            "discoveredSourceFiles": len(files),
            "discoveredUnits": len(units),
            "selectedUnits": len(analyzed),
            "autoConvertibleStates": sum(len(unit["states"]) for unit in analyzed),
            "reviewItems": review_count,
        },
        "diagnostics": diagnostics,
        "units": analyzed,
    }


def _safe_name(value, fallback):
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    if not normalized:
        return fallback
    if normalized[0].isdigit():
        normalized = f"m_{normalized}"
    return normalized


def _dsl(report, application_id, platform, profile, module_id, channel, release):
    if platform not in PLATFORMS or platform == "desktop":
        raise MigrationError("platform must be android, ios, or harmonyos")
    if profile not in PROFILES:
        raise MigrationError("unsupported delivery profile: " + profile)
    if not report["units"]:
        raise MigrationError("selection contains no source units")
    state_name_counts = Counter(
        state["name"] for unit in report["units"] for state in unit["states"]
    )
    state = {}
    pages = {}
    page_names = set()
    for index, unit in enumerate(report["units"], 1):
        page_name = _safe_name(unit["name"], f"page_{index}").lower()
        candidate = page_name
        suffix = 2
        while candidate in page_names:
            candidate = f"{page_name}_{suffix}"
            suffix += 1
        page_name = candidate
        page_names.add(page_name)
        children = [
            {
                "type": "text",
                "id": f"{page_name}_title",
                "props": {"text": unit["name"]},
            }
        ]
        for state_index, item in enumerate(unit["states"], 1):
            source_name = item["name"]
            if state_name_counts[source_name] == 1:
                target_name = _safe_name(source_name, f"state_{state_index}")
            else:
                target_name = _safe_name(
                    f"{unit['name']}_{source_name}", f"state_{index}_{state_index}"
                )
            unique_name = target_name
            unique_suffix = 2
            while unique_name in state:
                unique_name = f"{target_name}_{unique_suffix}"
                unique_suffix += 1
            state[unique_name] = {
                "type": item["type"],
                "persistence_id": f"{page_name}.{source_name}",
                "initial": item["initial"],
            }
            children.append(
                {
                    "type": "text",
                    "id": f"{page_name}_state_{state_index}",
                    "props": {"text": f"{source_name}: {{{unique_name}}}"},
                }
            )
        pages[page_name] = {
            "type": "column",
            "id": f"{page_name}_root",
            "props": {"accessibility_label": f"Migrated {unit['name']}"},
            "children": children,
        }
    entry_page = next(iter(pages))
    source = {
        "module": {
            "id": module_id,
            "application_id": application_id,
            "tenant": "migration",
            "channel": channel,
            "release": release,
            "key_version": 1,
            "minimum_runtime": 5,
            "entry_page": entry_page,
            "capabilities": [],
            "capability_versions": {},
            "network_domains": [],
            "storage_scopes": [],
            "budget": {
                "max_instructions_per_event": 1000,
                "max_stack": 32,
                "max_state_bytes": 65536,
                "max_ui_nodes": max(100, len(pages) * 20),
                "max_tasks": 16,
            },
        },
        "delivery": {
            "profile": profile,
            "platform": platform,
            "fallback_ui": profile == "online_provisioned",
            "startup_dependencies_bundled": profile == "offline_sealed",
            "native_dynamic_download": False,
            "external_code_artifacts": [],
        },
        "state": state,
        "handlers": {},
        "pages": pages,
    }
    Compiler(source).build()
    return source


def _capability_report(report):
    usages = {}
    for unit in report["units"]:
        for hint in unit["capabilityHints"]:
            usages.setdefault(hint["id"], []).append(
                {"unit": unit["id"], "line": hint["line"], "token": hint["token"]}
            )
    return {
        "schemaVersion": 1,
        "decisions": [
            {
                "id": identifier,
                "status": "pending",
                "adapter": "",
                "tests": [],
                "note": "",
                "evidence": evidence,
            }
            for identifier, evidence in sorted(usages.items())
        ],
    }


def _approval_id(unit, kind, detail, line=None):
    material = json.dumps(
        [unit["id"], kind, detail, line],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:16]


def _required_review_items(report):
    items = []
    for unit in report["units"]:
        for state in unit["states"]:
            if state["initialRedacted"]:
                items.append(
                    {
                        "id": _approval_id(
                            unit, "redacted_state", state["name"], state["line"]
                        ),
                        "kind": "redacted_state",
                        "unit": unit["id"],
                        "detail": state["name"],
                        "line": state["line"],
                    }
                )
        for hint in unit["uiHints"]:
            items.append(
                {
                    "id": _approval_id(unit, "ui_hint", hint["id"], hint["line"]),
                    "kind": "ui_hint",
                    "unit": unit["id"],
                    "detail": hint["id"],
                    "line": hint["line"],
                }
            )
        for finding in unit["manualReview"]:
            items.append(
                {
                    "id": _approval_id(
                        unit,
                        "manual_review",
                        f"{finding['id']}:{finding['token']}",
                        finding["line"],
                    ),
                    "kind": "manual_review",
                    "unit": unit["id"],
                    "detail": f"{finding['id']}:{finding['token']}",
                    "line": finding["line"],
                }
            )
        for dependency in unit["unselectedLocalDependencies"]:
            items.append(
                {
                    "id": _approval_id(unit, "unselected_dependency", dependency),
                    "kind": "unselected_dependency",
                    "unit": unit["id"],
                    "detail": dependency,
                    "line": None,
                }
            )
        for dependency in unit["ambiguousLocalDependencies"]:
            items.append(
                {
                    "id": _approval_id(
                        unit, "ambiguous_dependency", dependency["name"]
                    ),
                    "kind": "ambiguous_dependency",
                    "unit": unit["id"],
                    "detail": dependency["name"],
                    "line": None,
                }
            )
    return sorted(items, key=lambda item: item["id"])


def _approval_template(report):
    return {
        "schemaVersion": 1,
        "items": [
            {**item, "status": "pending", "note": ""}
            for item in _required_review_items(report)
        ],
    }


def _cases_template():
    return {
        "schemaVersion": 1,
        "cases": [],
    }


def _markdown(report):
    summary = report["summary"]
    lines = [
        "# Migration report / 迁移报告",
        "",
        "> The source project was scanned read-only. Generated DSL is a review scaffold.",
        "> 扫描过程不会修改源项目；生成的 DSL 是需要人工复核的迁移骨架。",
        "",
        "## Summary / 摘要",
        "",
        f"- Selected units / 已选单元：{summary['selectedUnits']}",
        f"- Auto-converted states / 自动转换状态：{summary['autoConvertibleStates']}",
        f"- Review items / 待复核项：{summary['reviewItems']}",
        "",
        "## Selected units / 已选类与文件",
        "",
    ]
    for unit in report["units"]:
        lines.extend(
            [
                f"### `{unit['qualifiedName']}`",
                "",
                f"- Source / 来源：`{unit['path']}:{unit['startLine']}`",
                f"- Language / 语言：`{unit['language']}`",
                f"- Converted states / 已转换状态：{len(unit['states'])}",
                "- Redacted defaults / 已脱敏默认值："
                + (
                    ", ".join(
                        state["name"]
                        for state in unit["states"]
                        if state["initialRedacted"]
                    )
                    or "none / 无"
                ),
                "- UI hints / UI 提示："
                + (", ".join(item["id"] for item in unit["uiHints"]) or "none / 无"),
                "- Capability hints / 能力提示："
                + (
                    ", ".join(item["id"] for item in unit["capabilityHints"])
                    or "none / 无"
                ),
                "- Manual review / 人工复核："
                + (
                    ", ".join(item["id"] for item in unit["manualReview"])
                    or "none / 无"
                ),
                "- Unselected local dependencies / 未选择的本地依赖："
                + (
                    ", ".join(unit["unselectedLocalDependencies"])
                    or "none / 无"
                ),
                "- Ambiguous local dependencies / 有歧义的本地依赖："
                + (
                    ", ".join(
                        dependency["name"]
                        for dependency in unit["ambiguousLocalDependencies"]
                    )
                    or "none / 无"
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Next review / 后续复核",
            "",
            "1. Confirm state names, persistence IDs, and redacted string defaults.",
            "2. 按报告重建 UI 层级，不要把 UI 提示当成已完成转换。",
            "3. Approve required capabilities and implement them with existing app services.",
            "4. 编译、签名并通过原页面与 PVM 页面行为对照测试后再切换路由。",
            "",
        ]
    )
    return "\n".join(lines)


def _write(path, content, force):
    if path.exists() and not force:
        raise MigrationError(f"output exists; pass --force to replace generated file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        os.replace(temporary, path)
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _require_output_outside_source(output, source):
    output = Path(output).resolve()
    source = Path(source).resolve()
    try:
        output.relative_to(source)
    except ValueError:
        return
    raise MigrationError("output must be outside the legacy source root")


def write_conversion(
    report,
    output,
    *,
    application_id,
    platform,
    profile="offline_sealed",
    module_id="migration.module",
    channel="enterprise",
    release=1,
    force=False,
):
    output = Path(output).resolve()
    if output.exists():
        unknown = {path.name for path in output.iterdir()} - GENERATED_FILES
        if unknown:
            raise MigrationError(
                "output directory contains non-migration files: " + ", ".join(sorted(unknown))
            )
        if any(output.iterdir()) and not force:
            raise MigrationError("output directory is not empty; pass --force to replace generated files")
    output.mkdir(parents=True, exist_ok=True)
    dsl = _dsl(
        report,
        application_id,
        platform,
        profile,
        module_id,
        channel,
        release,
    )
    artifacts = {
        "migration-report.json": json.dumps(report, indent=2, sort_keys=True) + "\n",
        "migration-report.md": _markdown(report),
        "capabilities.json": json.dumps(
            _capability_report(report), indent=2, sort_keys=True
        )
        + "\n",
        "migration-approvals.json": json.dumps(
            _approval_template(report), indent=2, sort_keys=True
        )
        + "\n",
        "migration-cases.json": json.dumps(
            _cases_template(), indent=2, sort_keys=True
        )
        + "\n",
        "module.pvm.json": json.dumps(dsl, indent=2, sort_keys=True) + "\n",
    }
    for name, content in artifacts.items():
        _write(output / name, content, force)
    return {name: output / name for name in artifacts}


def _read_json(path):
    path = Path(path)
    if path.is_symlink():
        raise MigrationError(f"verification input must not be a symlink: {path.name}")
    if not path.is_file():
        raise MigrationError(f"missing verification input: {path.name}")
    if path.stat().st_size > 10 * 1024 * 1024:
        raise MigrationError(f"verification input exceeds 10 MiB: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise MigrationError(f"invalid JSON in {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise MigrationError(f"JSON root must be an object: {path.name}")
    return value


def _verify_source(source, recorded):
    selection = recorded.get("selection")
    if (
        recorded.get("schemaVersion") != 1
        or recorded.get("scannerVersion") != 1
        or not isinstance(selection, dict)
    ):
        raise MigrationError("migration-report.json has an unsupported schema")
    classes = selection.get("classes")
    modules = selection.get("modules")
    include_dependencies = selection.get("includeDependencies")
    if (
        not isinstance(classes, list)
        or not all(isinstance(value, str) for value in classes)
        or not isinstance(modules, list)
        or not all(isinstance(value, str) for value in modules)
        or not isinstance(include_dependencies, bool)
    ):
        raise MigrationError("migration-report.json has an invalid selection")
    current = scan_project(
        source,
        classes=classes,
        modules=modules,
        include_dependencies=include_dependencies,
    )
    if current != recorded:
        recorded_units = {
            unit["id"]: unit.get("sourceSha256")
            for unit in recorded.get("units", [])
            if isinstance(unit, dict) and isinstance(unit.get("id"), str)
        }
        current_units = {
            unit["id"]: unit.get("sourceSha256") for unit in current.get("units", [])
        }
        changed = sorted(
            identifier
            for identifier in set(recorded_units) | set(current_units)
            if recorded_units.get(identifier) != current_units.get(identifier)
        )
        raise MigrationError(
            "legacy selection changed after conversion"
            + (": " + ", ".join(changed) if changed else "")
        )
    return {"selectedUnits": len(current["units"])}


def _verify_dsl(output):
    path = output / "module.pvm.json"
    source = _read_json(path)
    canonical = json.dumps(source, indent=2, sort_keys=True) + "\n"
    if path.read_text(encoding="utf-8") != canonical:
        raise MigrationError(
            "module.pvm.json is not canonical; run pvm_server.tooling format"
        )
    Compiler(source).build()
    host_idl = Path(
        os.environ.get("PVM_HOST_IDL", ROOT / "spec/host_idl.json")
    )
    lint(source, load_host_idl(host_idl))
    return source, {
        "moduleId": source["module"]["id"],
        "applicationId": source["module"]["application_id"],
        "platform": source["delivery"]["platform"],
        "profile": source["delivery"]["profile"],
        "release": source["module"]["release"],
    }


def _verify_approvals(recorded, approvals):
    required = {item["id"]: item for item in _required_review_items(recorded)}
    provided_items = approvals.get("items")
    if approvals.get("schemaVersion") != 1 or not isinstance(provided_items, list):
        raise MigrationError("migration-approvals.json has an unsupported schema")
    provided = {}
    for item in provided_items:
        if not isinstance(item, dict):
            raise MigrationError("migration approval entries must be objects")
        identifier = item.get("id")
        if not isinstance(identifier, str) or identifier in provided:
            raise MigrationError("migration approval IDs must be unique strings")
        provided[identifier] = item
    if set(provided) != set(required):
        missing = sorted(set(required) - set(provided))
        extra = sorted(set(provided) - set(required))
        raise MigrationError(
            "migration approvals do not match current review items"
            f" (missing={len(missing)}, extra={len(extra)})"
        )
    pending = []
    for identifier, item in provided.items():
        if item.get("status") not in ("accepted", "resolved"):
            pending.append(identifier)
        elif not isinstance(item.get("note"), str) or not item["note"].strip():
            pending.append(identifier)
    if pending:
        raise MigrationError(f"{len(pending)} migration review items remain pending")
    return {"reviewItems": len(required)}


def _verify_capabilities(recorded, source, capabilities):
    decisions = capabilities.get("decisions")
    if capabilities.get("schemaVersion") != 1 or not isinstance(decisions, list):
        raise MigrationError("capabilities.json has an unsupported schema")
    by_id = {}
    for decision in decisions:
        if not isinstance(decision, dict):
            raise MigrationError("capability decisions must be objects")
        identifier = decision.get("id")
        if not isinstance(identifier, str) or identifier in by_id:
            raise MigrationError("capability decision IDs must be unique strings")
        by_id[identifier] = decision
    suggested = {
        hint["id"] for unit in recorded["units"] for hint in unit["capabilityHints"]
    }
    declared = set(source["module"].get("capabilities", []))
    if set(by_id) != suggested | declared:
        raise MigrationError(
            "capability decisions must cover exactly the suggested and declared capabilities"
        )
    approved = set()
    pending = []
    for identifier, decision in by_id.items():
        status = decision.get("status")
        if status == "approved":
            adapter = decision.get("adapter")
            tests = decision.get("tests")
            if (
                not isinstance(adapter, str)
                or not adapter.strip()
                or not isinstance(tests, list)
                or not tests
                or not all(isinstance(test, str) and test.strip() for test in tests)
            ):
                pending.append(identifier)
            else:
                approved.add(identifier)
        elif status == "excluded":
            if not isinstance(decision.get("note"), str) or not decision["note"].strip():
                pending.append(identifier)
        else:
            pending.append(identifier)
    if pending:
        raise MigrationError(f"{len(pending)} capability decisions remain pending")
    if declared != approved:
        raise MigrationError(
            "declared capabilities must exactly match approved capability decisions"
        )
    return {"approved": sorted(approved), "excluded": sorted(suggested - approved)}


def _validate_cases(cases):
    values = cases.get("cases")
    if cases.get("schemaVersion") != 1 or not isinstance(values, list):
        raise MigrationError("migration-cases.json has an unsupported schema")
    if not values:
        raise MigrationError("strict verification requires at least one behavior case")
    names = set()
    for case in values:
        if not isinstance(case, dict):
            raise MigrationError("behavior cases must be objects")
        name = case.get("name")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise MigrationError("behavior case names must be unique non-empty strings")
        names.add(name)
        if (
            not isinstance(case.get("legacyEvidence"), str)
            or not case["legacyEvidence"].strip()
        ):
            raise MigrationError(f"behavior case {name} requires legacyEvidence")
        steps = case.get("steps")
        if not isinstance(steps, list) or not steps:
            raise MigrationError(f"behavior case {name} requires at least one step")
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise MigrationError(f"behavior case {name} steps must be objects")
            tap = step.get("tapIndex")
            expected = step.get("expectedOutput")
            forbidden = step.get("forbiddenOutput", [])
            if tap is not None and (
                not isinstance(tap, int) or isinstance(tap, bool) or tap < 0
            ):
                raise MigrationError(f"behavior case {name} step {index} has invalid tapIndex")
            if (
                not isinstance(expected, list)
                or not expected
                or not all(isinstance(value, str) and value for value in expected)
            ):
                raise MigrationError(
                    f"behavior case {name} step {index} requires expectedOutput"
                )
            if not isinstance(forbidden, list) or not all(
                isinstance(value, str) and value for value in forbidden
            ):
                raise MigrationError(
                    f"behavior case {name} step {index} has invalid forbiddenOutput"
                )
    return values


def _verify_behavior(output, source, cases, runtime, private_key, public_key):
    values = _validate_cases(cases)
    runtime = Path(runtime) if runtime else None
    private_key = Path(private_key) if private_key else None
    public_key = Path(public_key) if public_key else None
    if runtime is None or not runtime.is_file():
        raise MigrationError("strict verification requires --runtime")
    if private_key is None or not private_key.is_file():
        raise MigrationError("strict verification requires --private-key")
    if public_key is None or not public_key.is_file():
        raise MigrationError("strict verification requires --public-key")
    passed_steps = 0
    with tempfile.TemporaryDirectory(prefix="pvm-migration-verify-") as name:
        temporary = Path(name)
        module = temporary / "module.pvm"
        compile_file(output / "module.pvm.json", private_key, module)
        for case_index, case in enumerate(values):
            state = temporary / f"case-{case_index}.state"
            for step_index, step in enumerate(case["steps"]):
                command = [
                    str(runtime),
                    "--module",
                    str(module),
                    "--public-key",
                    str(public_key),
                    "--app-id",
                    source["module"]["application_id"],
                    "--channel",
                    source["module"]["channel"],
                    "--platform",
                    source["delivery"]["platform"],
                    "--profile",
                    source["delivery"]["profile"],
                    "--min-release",
                    str(source["module"]["release"]),
                    "--state-file",
                    str(state),
                ]
                if step.get("tapIndex") is not None:
                    command.extend(["--tap-index", str(step["tapIndex"])])
                try:
                    completed = subprocess.run(
                        command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=20,
                    )
                except subprocess.TimeoutExpired as error:
                    raise MigrationError(
                        f"behavior case {case['name']} step {step_index} timed out"
                    ) from error
                if completed.returncode:
                    raise MigrationError(
                        f"behavior case {case['name']} step {step_index} "
                        f"returned {completed.returncode}"
                    )
                missing = [
                    index
                    for index, value in enumerate(step["expectedOutput"])
                    if value not in completed.stdout
                ]
                present = [
                    index
                    for index, value in enumerate(step.get("forbiddenOutput", []))
                    if value in completed.stdout
                ]
                if missing or present:
                    raise MigrationError(
                        f"behavior case {case['name']} step {step_index} output mismatch "
                        f"(missing={missing}, forbidden={present})"
                    )
                passed_steps += 1
    return {"cases": len(values), "steps": passed_steps}


def _gate(action):
    try:
        details = action()
        return {"status": "pass", "details": details}
    except (MigrationError, CompileError, KeyError, OSError, TypeError) as error:
        return {"status": "fail", "error": str(error)}


def verify_conversion(
    source,
    output,
    *,
    strict=False,
    runtime=None,
    private_key=None,
    public_key=None,
    event=None,
):
    output = Path(output).resolve()
    if not output.is_dir():
        raise MigrationError(f"migration output is not a directory: {output}")
    recorded = _read_json(output / "migration-report.json")
    gates = {
        "source": _gate(lambda: _verify_source(source, recorded)),
    }
    if event:
        event(
            "source",
            gates["source"]["status"],
            20,
            "Checked the selected legacy source fingerprints",
            gates["source"],
        )
    dsl_holder = {}

    def verify_dsl():
        dsl, details = _verify_dsl(output)
        dsl_holder["source"] = dsl
        return details

    gates["dsl"] = _gate(verify_dsl)
    if event:
        event(
            "dsl",
            gates["dsl"]["status"],
            40,
            "Compiled and linted the generated DSL",
            gates["dsl"],
        )
    if strict:
        source_ok = gates["source"]["status"] == "pass"
        if source_ok:
            gates["reviews"] = _gate(
                lambda: _verify_approvals(
                    recorded,
                    _read_json(output / "migration-approvals.json"),
                )
            )
        else:
            gates["reviews"] = {
                "status": "fail",
                "error": "source verification failed first",
            }
        if event:
            event(
                "reviews",
                gates["reviews"]["status"],
                58,
                "Checked migration review decisions",
                gates["reviews"],
            )
        if source_ok and "source" in dsl_holder:
            gates["capabilities"] = _gate(
                lambda: _verify_capabilities(
                    recorded,
                    dsl_holder["source"],
                    _read_json(output / "capabilities.json"),
                )
            )
            gates["behavior"] = _gate(
                lambda: _verify_behavior(
                    output,
                    dsl_holder["source"],
                    _read_json(output / "migration-cases.json"),
                    runtime,
                    private_key,
                    public_key,
                )
            )
        else:
            gates["capabilities"] = {
                "status": "fail",
                "error": "source or DSL verification failed first",
            }
            gates["behavior"] = {
                "status": "fail",
                "error": "source or DSL verification failed first",
            }
        if event:
            event(
                "capabilities",
                gates["capabilities"]["status"],
                72,
                "Checked Capability decisions and declarations",
                gates["capabilities"],
            )
            event(
                "behavior",
                gates["behavior"]["status"],
                95,
                "Executed migration behavior cases with the C++17 VM",
                gates["behavior"],
            )
    else:
        gates["reviews"] = {"status": "skipped"}
        gates["capabilities"] = {"status": "skipped"}
        gates["behavior"] = {"status": "skipped"}
    failed = any(gate["status"] == "fail" for gate in gates.values())
    result = "failed" if failed else ("verified" if strict else "structurally_valid")
    verification = {
        "schemaVersion": 1,
        "strict": bool(strict),
        "result": result,
        "gates": gates,
    }
    _write(
        output / "verification.json",
        json.dumps(verification, indent=2, sort_keys=True) + "\n",
        True,
    )
    return verification


def _selection_arguments(parser):
    parser.add_argument(
        "--class",
        dest="classes",
        action="append",
        default=[],
        help="class name, qualified name, or relative/path.ext:Class; repeat for multiple",
    )
    parser.add_argument(
        "--module",
        dest="modules",
        action="append",
        default=[],
        help="module directory relative to source root; repeat to combine modules",
    )
    parser.add_argument("--include-dependencies", action="store_true")


def _event_argument(parser):
    parser.add_argument(
        "--events-jsonl",
        action="store_true",
        help="write machine-readable progress events to stdout",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)

    scan_parser = subparsers.add_parser("scan", help="inventory migration candidates")
    scan_parser.add_argument("source", type=Path)
    _selection_arguments(scan_parser)
    scan_parser.add_argument("--output", type=Path)
    scan_parser.add_argument("--force", action="store_true")
    _event_argument(scan_parser)

    convert_parser = subparsers.add_parser(
        "convert", help="generate a reviewable DSL migration scaffold"
    )
    convert_parser.add_argument("source", type=Path)
    _selection_arguments(convert_parser)
    convert_parser.add_argument("--output", required=True, type=Path)
    convert_parser.add_argument("--application-id", required=True)
    convert_parser.add_argument(
        "--platform", required=True, choices=("android", "ios", "harmonyos")
    )
    convert_parser.add_argument(
        "--profile", choices=tuple(PROFILES), default="offline_sealed"
    )
    convert_parser.add_argument("--module-id", default="migration.module")
    convert_parser.add_argument("--channel", default="enterprise")
    convert_parser.add_argument("--release", type=int, default=1)
    convert_parser.add_argument("--force", action="store_true")
    _event_argument(convert_parser)

    verify_parser = subparsers.add_parser(
        "verify", help="verify source drift, review decisions, DSL, and behavior"
    )
    verify_parser.add_argument("output", type=Path)
    verify_parser.add_argument("--source", required=True, type=Path)
    verify_parser.add_argument("--strict", action="store_true")
    verify_parser.add_argument("--runtime", type=Path)
    verify_parser.add_argument("--private-key", type=Path)
    verify_parser.add_argument("--public-key", type=Path)
    _event_argument(verify_parser)

    args = parser.parse_args()
    emit = lambda stage, status, progress, message, details=None: _emit_event(
        args.events_jsonl,
        args.action,
        stage,
        status,
        progress,
        message,
        details,
    )
    try:
        emit("prepare", "running", 2, "Validated migration command arguments")
        if args.action == "verify":
            _require_output_outside_source(args.output, args.source)
            verification = verify_conversion(
                args.source,
                args.output,
                strict=args.strict,
                runtime=args.runtime,
                private_key=args.private_key,
                public_key=args.public_key,
                event=emit,
            )
            if args.events_jsonl:
                emit(
                    "complete",
                    "pass" if verification["result"] != "failed" else "fail",
                    100,
                    "Migration verification completed",
                    {
                        "result": verification["result"],
                        "verification": str(args.output / "verification.json"),
                    },
                )
            else:
                print(args.output / "verification.json")
            if verification["result"] == "failed":
                raise MigrationError("migration verification failed")
            return
        if args.action == "scan" and args.events_jsonl and args.output is None:
            raise MigrationError("scan with --events-jsonl requires --output")
        if args.action == "convert" and not args.classes and not args.modules:
            raise MigrationError("convert requires at least one --class or --module selector")
        emit("scan", "running", 10, "Scanning selected legacy sources")
        report = scan_project(
            args.source,
            classes=args.classes,
            modules=args.modules,
            include_dependencies=args.include_dependencies,
        )
        emit(
            "scan",
            "pass",
            38 if args.action == "convert" else 90,
            "Selected legacy source scan completed",
            report["summary"],
        )
        if args.action == "scan":
            encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
            if args.output:
                _require_output_outside_source(args.output, args.source)
                _write(args.output, encoded, args.force)
                if args.events_jsonl:
                    emit(
                        "complete",
                        "pass",
                        100,
                        "Migration scan completed",
                        {"report": str(args.output)},
                    )
                else:
                    print(args.output)
            else:
                print(encoded, end="")
            return
        _require_output_outside_source(args.output, args.source)
        emit("generate", "running", 55, "Generating the migration scaffold")
        artifacts = write_conversion(
            report,
            args.output,
            application_id=args.application_id,
            platform=args.platform,
            profile=args.profile,
            module_id=args.module_id,
            channel=args.channel,
            release=args.release,
            force=args.force,
        )
        if args.events_jsonl:
            emit(
                "complete",
                "pass",
                100,
                "Migration scaffold generated",
                {
                    "artifacts": {
                        name: str(path) for name, path in artifacts.items()
                    }
                },
            )
        else:
            print("\n".join(str(path) for path in artifacts.values()))
    except (MigrationError, CompileError, OSError) as error:
        emit("failed", "fail", 100, str(error))
        parser.error(str(error))


if __name__ == "__main__":
    main()
