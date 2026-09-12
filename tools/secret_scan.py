"""Fail on likely credentials, personal paths, or private artifacts in Git."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_PATTERNS = {
    "OpenAI-style key": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "GitHub token": re.compile(rb"\bgh[opsu]_[A-Za-z0-9]{20,}\b"),
    "generic bearer token": re.compile(rb"Bearer\s+[A-Za-z0-9._~+/-]{24,}"),
    "Windows personal path": re.compile(rb"[A-Za-z]:\\Users\\[^\\\r\n]+\\"),
}
FORBIDDEN_NAMES = re.compile(
    r"(?:chat|assistant).*\.log$|(?:cookie|token|contact|screenshot)|"
    r"\.(?:gguf|safetensors|pt|pth|onnx)$",
    re.IGNORECASE,
)


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.DEVNULL)


def scan_blob(label: str, data: bytes, findings: list[str]) -> None:
    for kind, pattern in TEXT_PATTERNS.items():
        if pattern.search(data):
            findings.append(f"{label}: {kind}")


def main() -> None:
    findings: list[str] = []
    commits = git("rev-list", "--all").decode().splitlines()
    for commit in commits:
        names = git("ls-tree", "-r", "--name-only", commit).decode("utf-8", "replace").splitlines()
        for name in names:
            if FORBIDDEN_NAMES.search(name):
                findings.append(f"{commit[:12]}:{name}: forbidden filename")
            try:
                data = git("show", f"{commit}:{name}")
            except subprocess.CalledProcessError:
                continue
            if len(data) <= 5_000_000:
                scan_blob(f"{commit[:12]}:{name}", data, findings)
    working_names = git("ls-files", "--cached", "--others", "--exclude-standard").decode(
        "utf-8", "replace"
    ).splitlines()
    for name in working_names:
        path = ROOT / name
        if FORBIDDEN_NAMES.search(name):
            findings.append(f"working-tree:{name}: forbidden filename")
        if path.is_file() and path.stat().st_size <= 5_000_000:
            scan_blob(f"working-tree:{name}", path.read_bytes(), findings)
    if findings:
        raise SystemExit("Secret scan failed:\n- " + "\n- ".join(sorted(set(findings))))
    print(f"secret scan passed ({len(commits)} commits and current tracked files)")


if __name__ == "__main__":
    main()
