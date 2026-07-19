from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (REPOSITORY_ROOT / path).read_text(encoding="utf-8")


def test_readme_uses_actual_environment_variable_names() -> None:
    readme = read("README.md")
    env_example = read("config/env.example")

    for name in (
        "BOOK_SYSTEM_ENV",
        "BOOK_API_KEY",
        "BOOK_ADMIN_USERNAME",
        "BOOK_ADMIN_PASSWORD",
        "BOOK_BIND_HOST",
        "BOOK_BIND_PORT",
    ):
        assert name in readme
        assert name in env_example

    for obsolete_name in (
        "BOOK_SYSTEM_ADMIN_TOKEN",
        "BOOK_SYSTEM_API_KEY",
        "BOOK_SYSTEM_REQUIRE_AUTH",
    ):
        assert obsolete_name not in readme
        assert obsolete_name not in env_example


def test_service_names_agree_across_readme_deploy_script_and_units() -> None:
    readme = read("README.md")
    deploy_script = read("scripts/deploy_server.sh")

    for service in ("book-system-api.service", "book-system-worker.service"):
        assert service in readme
        assert service in deploy_script
        unit_path = REPOSITORY_ROOT / "deploy" / "systemd" / service
        assert unit_path.is_file()
        unit = unit_path.read_text(encoding="utf-8")
        assert "EnvironmentFile=/opt/book-system/config/env" in unit
        assert "WorkingDirectory=/opt/book-system" in unit


def test_apache_asset_claimed_by_readme_is_committed() -> None:
    readme = read("README.md")
    relative_path = "deploy/apache/publish.toiletrage.co.uk.conf"
    assert relative_path in readme
    apache = REPOSITORY_ROOT / relative_path
    assert apache.is_file()
    content = apache.read_text(encoding="utf-8")
    assert "ProxyPass / http://127.0.0.1:8080/" in content
    assert "ServerName publish.toiletrage.co.uk" in content


def test_completion_authority_files_are_present() -> None:
    for relative_path in (
        "docs/PRODUCT_CONTRACT.md",
        "docs/COMPLETION_CONTRACT.md",
        "docs/RELEASE_ACCEPTANCE.md",
        "docs/completion-authority.json",
    ):
        assert (REPOSITORY_ROOT / relative_path).is_file()
