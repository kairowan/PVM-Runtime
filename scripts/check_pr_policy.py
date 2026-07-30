#!/usr/bin/env python3
"""Review PVM pull-request metadata and maintain one bilingual bot comment."""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


TITLE = re.compile(
    r"^(build|chore|ci|docs|feat|fix|perf|refactor|release|security|test)"
    r"(?:\([a-z0-9._/-]+\))?!?: .+"
)
ISSUE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+"
    r"(?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?#\d+\b",
    re.IGNORECASE,
)
AUTOMATION = {"dependabot[bot]", "github-actions[bot]", "renovate[bot]"}
MARKER = "<!-- pvm-pr-policy -->"


def evaluate(payload):
    pr = payload["pull_request"]
    repository = payload["repository"]
    author = pr.get("user", {}).get("login", "")
    body = pr.get("body") or ""
    passed = []
    failed = []

    if TITLE.fullmatch(pr.get("title", "")):
        passed.append("Conventional PR title / PR 标题格式")
    else:
        failed.append(
            "Use `type(scope): summary`, for example `fix(android): reject stale modules`. "
            "/ 请使用 `类型(范围): 摘要` 格式。"
        )

    default_branch = repository.get("default_branch", "main")
    if pr.get("base", {}).get("ref") == default_branch:
        passed.append("Targets the default branch / 目标为默认分支")
    else:
        failed.append(
            f"Target `{default_branch}` unless a maintainer approved another base. "
            f"/ 除非维护者确认，请以 `{default_branch}` 为目标分支。"
        )

    if author in AUTOMATION:
        passed.append("Automation PR: linked Issue waived / 自动化 PR：免除关联 Issue")
    elif ISSUE.search(body):
        passed.append("Linked Issue with closing keyword / 已用关闭关键字关联 Issue")
    else:
        failed.append(
            "Link an accepted Issue in the PR body, for example `Closes #123`. "
            "/ 请在 PR 正文中关联已确认的 Issue，例如 `Closes #123`。"
        )

    if author in AUTOMATION or len(body.strip()) >= 80:
        passed.append("Reviewable PR description / PR 描述信息充分")
    else:
        failed.append(
            "Describe the change, risk, and verification in at least 80 characters. "
            "/ 请用至少 80 个字符说明变更、风险和验证结果。"
        )
    return passed, failed


def request_json(method, url, token, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        encoded = response.read()
    return json.loads(encoded) if encoded else None


def render_comment(passed, failed):
    status = "PASS / 通过" if not failed else "ACTION REQUIRED / 需要修改"
    lines = [
        MARKER,
        "## PVM PR Policy Review / PVM PR 策略审核",
        "",
        f"**{status}**",
        "",
    ]
    lines.extend(f"- ✅ {item}" for item in passed)
    lines.extend(f"- ❌ {item}" for item in failed)
    lines.extend(
        [
            "",
            "The bot updates this comment after each PR edit or push. "
            "/ 每次修改 PR 或推送提交后，机器人都会更新本评论。",
        ]
    )
    return "\n".join(lines)


def upsert_comment(repository, number, token, body):
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    comments_url = f"{api}/repos/{repository}/issues/{number}/comments?per_page=100"
    comments = request_json("GET", comments_url, token)
    existing = next((item for item in comments if MARKER in item.get("body", "")), None)
    if existing:
        url = f"{api}/repos/{repository}/issues/comments/{existing['id']}"
        request_json("PATCH", url, token, {"body": body})
    else:
        url = f"{api}/repos/{repository}/issues/{number}/comments"
        request_json("POST", url, token, {"body": body})


def self_test():
    base = {
        "repository": {"default_branch": "main"},
        "pull_request": {
            "title": "fix(android): reject stale modules",
            "body": "Closes #12\n\nSummary and verification details " + ("x" * 80),
            "base": {"ref": "main"},
            "user": {"login": "contributor"},
        },
    }
    assert not evaluate(base)[1]
    missing_issue = json.loads(json.dumps(base))
    missing_issue["pull_request"]["body"] = "Detailed verification " + ("x" * 100)
    assert any("Closes #123" in item for item in evaluate(missing_issue)[1])
    bot = json.loads(json.dumps(base))
    bot["pull_request"]["user"]["login"] = "dependabot[bot]"
    bot["pull_request"]["body"] = ""
    assert not evaluate(bot)[1]
    print("PR policy: PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", type=Path)
    parser.add_argument("--repository")
    parser.add_argument("--comment", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.event:
        parser.error("--event is required unless --self-test is used")

    payload = json.loads(args.event.read_text(encoding="utf-8"))
    passed, failed = evaluate(payload)
    comment = render_comment(passed, failed)
    print(comment)
    if args.comment:
        token = os.environ.get("GH_TOKEN")
        if not token or not args.repository:
            print("GH_TOKEN and --repository are required for --comment", file=sys.stderr)
            return 2
        try:
            upsert_comment(
                args.repository,
                payload["pull_request"]["number"],
                token,
                comment,
            )
        except urllib.error.HTTPError as error:
            print(f"Unable to update PR comment: HTTP {error.code}", file=sys.stderr)
            return 2
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
