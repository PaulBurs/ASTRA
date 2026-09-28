from pathlib import Path

import pytest

from source_agent.paths import resolve_source_path


def test_container_source_accepts_host_mounted_and_relative_paths(tmp_path, monkeypatch):
    root = tmp_path / "mount"
    (root / "archive").mkdir(parents=True)
    monkeypatch.setenv("SOURCE_MOUNT_ROOT", str(root))
    monkeypatch.setenv("SOURCE_HOST_ROOT", "/home/developer/ASTRA/DJKH_transport")
    expected = root / "archive"
    assert resolve_source_path("/home/developer/ASTRA/DJKH_transport/archive") == expected
    assert resolve_source_path(str(expected)) == expected
    assert resolve_source_path("archive") == expected


def test_container_source_rejects_escape_and_symlink(tmp_path, monkeypatch):
    root = tmp_path / "mount"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("SOURCE_MOUNT_ROOT", str(root))
    for path in ("../outside", "link", str(outside)):
        with pytest.raises(ValueError, match="вне подключённого"):
            resolve_source_path(path)


def test_local_agent_path_keeps_existing_behavior(tmp_path, monkeypatch):
    monkeypatch.delenv("SOURCE_MOUNT_ROOT", raising=False)
    assert resolve_source_path(str(tmp_path)) == Path(tmp_path)
