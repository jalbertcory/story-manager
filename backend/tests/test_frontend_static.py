"""Tests for serving built frontend files without escaping the dist directory."""

import pytest

from backend.app.main import resolve_frontend_file


@pytest.fixture
def dist_dir(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>")
    (dist / "favicon.ico").write_bytes(b"icon")
    (tmp_path / "secret.txt").write_text("secret")
    return dist


def test_serves_file_inside_dist(dist_dir):
    assert resolve_frontend_file("favicon.ico", dist_dir) == (dist_dir / "favicon.ico").resolve()


def test_missing_or_empty_path_falls_back(dist_dir):
    assert resolve_frontend_file("", dist_dir) is None
    assert resolve_frontend_file("books/12", dist_dir) is None


@pytest.mark.parametrize(
    "full_path",
    [
        "/etc/hosts",
        "../secret.txt",
        "assets/../../secret.txt",
    ],
)
def test_rejects_paths_outside_dist(dist_dir, full_path):
    assert resolve_frontend_file(full_path, dist_dir) is None


def test_rejects_absolute_path_to_existing_file(dist_dir, tmp_path):
    assert resolve_frontend_file(str(tmp_path / "secret.txt"), dist_dir) is None


def test_rejects_symlink_escaping_dist(dist_dir, tmp_path):
    (dist_dir / "link.txt").symlink_to(tmp_path / "secret.txt")
    assert resolve_frontend_file("link.txt", dist_dir) is None
