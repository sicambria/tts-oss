"""Dubbing unit tests — no models, no network."""
from pathlib import Path


def test_job_rejects_bad_ext(tmp_path):
    from dubbing.config import DubJob
    job = DubJob(input=Path("x.txt"))
    try:
        job.validate()
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_job_rejects_hu_pocket(tmp_path):
    from dubbing.config import DubJob
    job = DubJob(input=Path("a.mp3"), target_lang="hu", engine="Pocket TTS")
    try:
        job.validate()
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_burn_in_rejected_for_audio():
    from dubbing.config import DubJob
    job = DubJob(input=Path("a.mp3"), burn_in=True)
    try:
        job.validate()
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_separation_default_off():
    from dubbing.config import DEFAULT_DUBBING_SETTINGS
    assert DEFAULT_DUBBING_SETTINGS["separation_enabled"] is False
    assert DEFAULT_DUBBING_SETTINGS["audio_output_format"] == "mp3"
    assert DEFAULT_DUBBING_SETTINGS["phase_1b_enabled"] is False


def test_phase_isolation_subprocess():
    import subprocess
    import sys
    code = "import dubbing.pipeline, sys; sys.exit(1 if 'dubbing.video' in sys.modules else 0)"
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True)
    assert proc.returncode == 0, "Phase 1a must not import dubbing.video"


def test_missing_deps_structure():
    from dubbing import missing_dependencies
    from dubbing import pip_missing_specs
    plain = missing_dependencies(False)
    assert "separator" not in [d["key"] for d in plain]
    with_sep = missing_dependencies(True)
    assert "separator" in [d["key"] for d in with_sep]
    assert all(set(d) >= {"key", "label", "ok", "pip", "needs_sudo", "hint"} for d in plain)
    assert isinstance(pip_missing_specs(False), list)
