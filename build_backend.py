from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


NAME = "lorien"
VERSION = "0.1.0"


def _dist_info_dir() -> str:
    return f"{NAME}-{VERSION}.dist-info"


def _wheel_name(tag: str) -> str:
    normalized = NAME.replace("-", "_")
    return f"{normalized}-{VERSION}-{tag}.whl"


def _metadata() -> str:
    return "\n".join(
        [
            "Metadata-Version: 2.1",
            f"Name: {NAME}",
            f"Version: {VERSION}",
            "Summary: Personal knowledge graph for AI agents - backed by Kuzu embedded graph DB",
            "Requires-Python: >=3.12",
            "Requires-Dist: kuzu>=0.8.0",
            "Requires-Dist: click>=8.0",
            "Requires-Dist: gitpython>=3.1",
            "",
        ]
    )


def _wheel_file() -> str:
    return "\n".join(
        [
            "Wheel-Version: 1.0",
            "Generator: build_backend",
            "Root-Is-Purelib: true",
            "Tag: py3-none-any",
            "",
        ]
    )


def _entry_points() -> str:
    return "\n".join(["[console_scripts]", "lorien = lorien.cli:main", ""])


def _hash_bytes(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _build_wheel(wheel_directory: str, editable: bool) -> str:
    wheel_dir = Path(wheel_directory)
    wheel_dir.mkdir(parents=True, exist_ok=True)
    wheel_name = _wheel_name("py3-none-any")
    wheel_path = wheel_dir / wheel_name
    dist_info = _dist_info_dir()
    src_path = Path(__file__).resolve().parent / "src"
    records: list[tuple[str, bytes]] = []

    with ZipFile(wheel_path, "w", compression=ZIP_DEFLATED) as wheel:
        files: list[tuple[str, bytes]] = [
            (f"{dist_info}/METADATA", _metadata().encode()),
            (f"{dist_info}/WHEEL", _wheel_file().encode()),
            (f"{dist_info}/entry_points.txt", _entry_points().encode()),
        ]
        if editable:
            files.append((f"{NAME}.pth", f"{src_path}\n".encode()))
        for archive_name, data in files:
            wheel.writestr(archive_name, data)
            records.append((archive_name, data))

        record_lines: list[list[str]] = []
        for archive_name, data in records:
            record_lines.append([archive_name, _hash_bytes(data), str(len(data))])
        record_lines.append([f"{dist_info}/RECORD", "", ""])

        output = []
        for line in record_lines:
            output.append(",".join(line))
        record_data = ("\n".join(output) + "\n").encode()
        wheel.writestr(f"{dist_info}/RECORD", record_data)

    return wheel_name


def build_wheel(
    wheel_directory: str,
    config_settings: dict | None = None,
    metadata_directory: str | None = None,
) -> str:
    return _build_wheel(wheel_directory, editable=False)


def build_editable(
    wheel_directory: str,
    config_settings: dict | None = None,
    metadata_directory: str | None = None,
) -> str:
    return _build_wheel(wheel_directory, editable=True)


def get_requires_for_build_wheel(config_settings: dict | None = None) -> list[str]:
    return []


def get_requires_for_build_editable(config_settings: dict | None = None) -> list[str]:
    return []


def prepare_metadata_for_build_wheel(
    metadata_directory: str,
    config_settings: dict | None = None,
) -> str:
    return _prepare_metadata(metadata_directory)


def prepare_metadata_for_build_editable(
    metadata_directory: str,
    config_settings: dict | None = None,
) -> str:
    return _prepare_metadata(metadata_directory)


def _prepare_metadata(metadata_directory: str) -> str:
    target = Path(metadata_directory) / _dist_info_dir()
    target.mkdir(parents=True, exist_ok=True)
    (target / "METADATA").write_text(_metadata(), encoding="utf-8")
    (target / "WHEEL").write_text(_wheel_file(), encoding="utf-8")
    (target / "entry_points.txt").write_text(_entry_points(), encoding="utf-8")
    (target / "RECORD").write_text("", encoding="utf-8")
    return target.name
