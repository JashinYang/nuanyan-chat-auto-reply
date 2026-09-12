"""Reproduce and verify the Windows runtime license inventory."""
from __future__ import annotations

import argparse
import importlib.metadata as md
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "THIRD_PARTY_LICENSES"
EXPECTED = {
    "requests": "2.34.2",
    "urllib3": "2.7.0",
    "certifi": "2026.7.22",
    "charset-normalizer": "3.5.1",
    "idna": "3.19",
    "uiautomation": "2.0.29",
    "comtypes": "1.4.16",
    "pywin32": "311",
    "pywebview": "6.1",
    "pythonnet": "3.1.0",
    "clr-loader": "0.3.1",
    "cffi": "2.1.1",
    "pycparser": "3.0",
    "proxy-tools": "0.1.0",
    "bottle": "0.13.4",
    "typing-extensions": "4.16.0",
    "windows-capture": "2.0.1",
    "numpy": "2.5.3",
    "opencv-python": "5.0.0.93",
    "setuptools": "84.0.0",
    "packaging": "26.3",
    "pywin32-ctypes": "0.2.3",
}
ALIASES = {"opencv-python": "opencv-python", "clr-loader": "clr-loader"}
REQUIRED_DIRS = set(EXPECTED) | {"python", "pyinstaller", "webview2", "qqsafechat"}
FORBIDDEN_SUFFIXES = {".gguf", ".safetensors", ".pt", ".pth", ".onnx"}


def distribution_root(name: str) -> Path:
    dist = md.distribution(name)
    return Path(dist.locate_file(""))


def license_files(name: str) -> list[Path]:
    dist = md.distribution(name)
    files = []
    for item in dist.files or []:
        basename = Path(str(item)).name.upper()
        if basename.startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE")):
            path = Path(dist.locate_file(item))
            if path.is_file():
                files.append(path)
    return files


def sync() -> None:
    OUT.mkdir(exist_ok=True)
    for name in EXPECTED:
        target = OUT / ALIASES.get(name, name)
        if name == "proxy-tools":
            # The 0.1.0 wheel omits LICENSE.txt; a verified upstream copy is
            # maintained in the repository instead.
            continue
        if target.exists():
            shutil.rmtree(target)
        target.mkdir()
        files = license_files(name)
        if not files:
            raise SystemExit(f"No license file found in installed distribution: {name}")
        used: set[str] = set()
        for source in files:
            label = source.name
            counter = 2
            while label.lower() in used:
                label = f"{source.stem}-{counter}{source.suffix}"
                counter += 1
            used.add(label.lower())
            shutil.copy2(source, target / label)

    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise SystemExit(f"Python license not found: {python_license}")
    (OUT / "python").mkdir(exist_ok=True)
    shutil.copy2(python_license, OUT / "python" / "LICENSE.txt")

    pyinstaller = md.distribution("pyinstaller")
    copying = next(
        Path(pyinstaller.locate_file(item))
        for item in pyinstaller.files or []
        if Path(str(item)).name == "COPYING.txt"
    )
    (OUT / "pyinstaller").mkdir(exist_ok=True)
    shutil.copy2(copying, OUT / "pyinstaller" / "COPYING.txt")


def check(release_dir: Path | None) -> None:
    errors = []
    for name, expected in EXPECTED.items():
        try:
            actual = md.version(name)
        except md.PackageNotFoundError:
            errors.append(f"missing package: {name}")
            continue
        if actual != expected:
            errors.append(f"{name}: expected {expected}, found {actual}")
    for name in sorted(REQUIRED_DIRS):
        path = OUT / name
        if not path.is_dir() or not any(path.rglob("*")):
            errors.append(f"missing license directory: {name}")
    if release_dir:
        for required in (
            "README.md", "LICENSE", "PRIVACY.md", "THIRD_PARTY_NOTICES.txt",
            "THIRD_PARTY_COMPONENTS.md", "THIRD_PARTY_LICENSES",
        ):
            if not (release_dir / required).exists():
                errors.append(f"release missing: {required}")
        for item in release_dir.rglob("*"):
            if item.suffix.lower() in FORBIDDEN_SUFFIXES:
                errors.append(f"forbidden model artifact: {item.name}")
        dll64 = release_dir / "lib" / "uiautomation" / "bin" / "UIAutomationClient_VC140_X64.dll"
        dll86 = release_dir / "lib" / "uiautomation" / "bin" / "UIAutomationClient_VC140_X86.dll"
        if not dll64.is_file() or not dll86.is_file():
            errors.append("release missing UIAutomation client DLL(s)")
    if errors:
        raise SystemExit("License audit failed:\n- " + "\n- ".join(errors))
    print(f"license audit passed ({len(EXPECTED)} pinned runtime packages)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sync", action="store_true", help="copy installed license texts")
    parser.add_argument("--release-dir", type=Path)
    args = parser.parse_args()
    if args.sync:
        sync()
    check(args.release_dir)


if __name__ == "__main__":
    main()
