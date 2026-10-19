"""Build deterministic installation and source ZIPs, with optional real repo metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = Path("custom_components/smart_heat_manager")


def repository_metadata(repository):
    """Accept an HTTPS clone URL and generate canonical browser links."""
    url = urlparse(repository.rstrip("/"))
    parts = url.path.strip("/").split("/")
    if (
        url.scheme != "https"
        or url.netloc != "github.com"
        or len(parts) != 2
        or not all(parts)
        or url.query
        or url.fragment
        or url.params
    ):
        raise ValueError("Use a real https://github.com/owner/repository URL")
    owner, name = parts
    name = name.removesuffix(".git")
    if not name or owner in (".", "..") or name in (".", ".."):
        raise ValueError("Use a real https://github.com/owner/repository URL")
    base = f"https://github.com/{owner}/{name}"
    return {"documentation": f"{base}#readme", "issue_tracker": f"{base}/issues", "codeowners": [f"@{owner}"]}


def write_zip(path, contents):
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in sorted(contents.items()):
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", help="Real GitHub URL, e.g. https://github.com/account/repository")
    args = parser.parse_args()
    manifest_path = COMPONENT / "manifest.json"
    manifest = json.loads((ROOT / manifest_path).read_text(encoding="utf-8"))
    if args.repository:
        try:
            manifest.update(repository_metadata(args.repository))
        except ValueError as err:
            parser.error(str(err))
    content = {}
    include_roots = [
        ROOT / "custom_components",
        ROOT / "docs",
        ROOT / "tools",
        ROOT / "tests",
        ROOT / "examples",
        ROOT / ".github",
    ]
    for folder in include_roots:
        for path in folder.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                content[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    for name in ("README.md", "LICENSE", "hacs.json", "pyproject.toml", ".gitignore", "requirements-dev.txt"):
        content[name] = (ROOT / name).read_bytes()
    content[manifest_path.as_posix()] = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode()
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    version = manifest["version"]
    for filename, files in [
        (f"smart_heat_manager-{version}.zip", {k: v for k, v in content.items() if k.startswith("custom_components/")}),
        (f"smart_heat_manager-source-{version}.zip", content),
    ]:
        path = dist / filename
        write_zip(path, files)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"{filename}: {len(files)} files; SHA256 {digest}")
    print("Distribution metadata: " + manifest["documentation"])
    print("Local archives built; this command does not publish to GitHub.")


if __name__ == "__main__":
    main()
