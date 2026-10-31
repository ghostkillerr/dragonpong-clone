"""Prepare a public EXE update asset and its SHA-256 manifest locally.

Upload the ZIP to a GitHub Release first, then publish update.json. Do not
include the local reference-sound package in a public release.
"""

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path


def build(exe: Path, version: str, output: Path) -> tuple[Path, Path, Path]:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("version must be MAJOR.MINOR.PATCH")
    if not exe.is_file() or exe.stat().st_size == 0:
        raise ValueError("EXE is missing or empty")
    output.mkdir(parents=True, exist_ok=True)
    tag = f"v{version}"
    asset_name = f"DragonPongClone_client_{tag}.zip"
    archive_path = output / asset_name
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(exe, "DragonPongClone.exe")
    with zipfile.ZipFile(archive_path) as archive:
        if archive.namelist() != ["DragonPongClone.exe"] or archive.testzip() is not None:
            raise ValueError("invalid update archive")
    bootstrap_path = output / f"DragonPongClone_first_install_{tag}.zip"
    base = Path(__file__).resolve().parent
    with zipfile.ZipFile(bootstrap_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(exe, "DragonPongClone.exe")
        for filename in ("start_clone.bat", "update_launcher.ps1", "OYNA.md", "LICENSE", "THIRD_PARTY_NOTICES.md"):
            archive.write(base / filename, filename)
        archive.writestr("client_version.txt", version)
    with zipfile.ZipFile(bootstrap_path) as archive:
        if archive.testzip() is not None:
            raise ValueError("invalid first-install archive")
    with archive_path.open("rb") as packaged:
        digest = hashlib.file_digest(packaged, "sha256").hexdigest()
    manifest = {
        "version": version,
        "package_url": (
            "https://github.com/ghostkillerr/dragonpong-clone/releases/download/"
            f"{tag}/{asset_name}"
        ),
        "sha256": digest,
    }
    manifest_path = output / "update.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return archive_path, bootstrap_path, manifest_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("version", help="e.g. 2.5.0")
    parser.add_argument("--exe", type=Path, default=Path("dist/DragonPongClone.exe"))
    parser.add_argument("--out", type=Path, default=Path("dist_update"))
    args = parser.parse_args()
    print(*build(args.exe, args.version, args.out), sep="\n")
