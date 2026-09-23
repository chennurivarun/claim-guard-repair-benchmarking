import subprocess

import pytest

from app import converter_setup
from app.services import document_processing


def test_check_does_not_install_and_missing_renderer_is_failure(monkeypatch, capsys):
    monkeypatch.setattr(converter_setup, "find_libreoffice", lambda: None)
    monkeypatch.setattr(converter_setup.subprocess, "run", lambda *a, **k: pytest.fail("No install requested"))
    assert converter_setup.main([]) == 1
    assert "--install" in capsys.readouterr().out


def test_existing_converter_is_verified_without_install(monkeypatch, capsys):
    monkeypatch.setattr(converter_setup, "find_libreoffice", lambda: "/office/soffice")
    monkeypatch.setattr(converter_setup, "verify_conversion", lambda: 1)
    monkeypatch.setattr(converter_setup.subprocess, "run", lambda *a, **k: pytest.fail("Already installed"))
    assert converter_setup.main(["--install"]) == 0
    assert "PASS" in capsys.readouterr().out


def test_windows_install_rechecks_converter_then_runs_verification(monkeypatch):
    detections = iter([None, "C:/Program Files/LibreOffice/program/soffice.com"])
    monkeypatch.setattr(converter_setup, "find_libreoffice", lambda: next(detections))
    monkeypatch.setattr(converter_setup.sys, "platform", "win32")
    monkeypatch.setattr(converter_setup.shutil, "which", lambda name: "winget.exe")
    calls = []

    def install(command, **kwargs):
        assert command == ["winget.exe", "install", "--id", "TheDocumentFoundation.LibreOffice",
                           "--exact", "--source", "winget"]
        calls.append("install")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(converter_setup.subprocess, "run", install)
    monkeypatch.setattr(converter_setup, "verify_conversion", lambda: calls.append("verify") or 1)
    assert converter_setup.main(["--install"]) == 0
    assert calls == ["install", "verify"]


@pytest.mark.parametrize("failure", [1, subprocess.TimeoutExpired("winget", 900)])
def test_failed_install_never_reports_ready(monkeypatch, capsys, failure):
    monkeypatch.setattr(converter_setup, "find_libreoffice", lambda: None)
    monkeypatch.setattr(converter_setup.sys, "platform", "win32")
    monkeypatch.setattr(converter_setup.shutil, "which", lambda _: "winget.exe")

    def install(command, **kwargs):
        if isinstance(failure, Exception):
            raise failure
        return subprocess.CompletedProcess(command, failure)

    monkeypatch.setattr(converter_setup.subprocess, "run", install)
    assert converter_setup.main(["--install"]) == 1
    assert "PASS" not in capsys.readouterr().out


def test_installed_but_broken_converter_is_failure(monkeypatch, capsys):
    monkeypatch.setattr(converter_setup, "find_libreoffice", lambda: "/office/soffice")

    def fail():
        raise ValueError("Word document conversion timed out after 60 seconds.")

    monkeypatch.setattr(converter_setup, "verify_conversion", fail)
    assert converter_setup.main([]) == 1
    assert "timed out" in capsys.readouterr().out


def test_probe_requires_office_instead_of_dropping_visual_content(monkeypatch):
    monkeypatch.setattr(document_processing, "find_libreoffice", lambda: None)
    with pytest.raises(ValueError, match="claimguard-converter --install"):
        converter_setup.verify_conversion()
