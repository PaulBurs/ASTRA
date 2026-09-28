"""Translate an optional host CSV directory into the container's read-only mount."""
import os
from pathlib import Path


def resolve_source_path(value: str) -> Path:
    mount = os.getenv("SOURCE_MOUNT_ROOT")
    if not mount:
        return Path(value).expanduser().resolve(strict=True)
    root = Path(mount).resolve(strict=True)
    requested = Path(value)
    host = os.getenv("SOURCE_HOST_ROOT")
    if host and Path(host).is_absolute() and requested.is_relative_to(host):
        requested = root / requested.relative_to(host)
    elif not requested.is_absolute():
        requested = root / requested
    resolved = requested.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError("Папка находится вне подключённого каталога CSV (ASTRA_SOURCE_DIR)")
    return resolved
