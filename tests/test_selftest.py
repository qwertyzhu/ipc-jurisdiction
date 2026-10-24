"""CI wrapper: the engine's --selftest is the source of truth."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "jurisdiction.py"


def test_selftest_passes():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--selftest"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "passed" in result.stdout
    assert "FAIL" not in result.stdout


def test_cli_help_is_chinese():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "管辖" in result.stdout
    assert "--def-prov" in result.stdout


def test_default_readme_is_chinese():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "信息网络传播权" in text
    assert "管辖" in text


def test_skill_entry_is_chinese():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "管辖" in text
    assert "查表" in text


def test_pages_html_is_chinese():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert 'lang="zh-CN"' in html
    assert "管辖" in html
    assert "<title>" in html
    title = html.split("<title>", 1)[1].split("</title>", 1)[0]
    assert any("\u4e00" <= ch <= "\u9fff" for ch in title)


def test_page_does_not_calculate_courts():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert "CITY_IP_COURT" not in html
    assert "REGION_DATA" not in html
    assert "以其为准" not in html
    assert "不计算" in html


def test_community_files_are_chinese_first():
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "贡献" in contributing
    assert "虚构" in contributing
    assert "禁止" in security or "不要" in security
    assert "起诉状" in security or "卷宗" in security
    assert "首次公开发布" in changelog or "管辖助手" in changelog
