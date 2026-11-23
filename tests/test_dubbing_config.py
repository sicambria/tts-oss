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


def test_job_rejects_pocket_without_voice(tmp_path):
    from dubbing.config import DubJob
    job = DubJob(input=Path("a.mp3"), target_lang="ja", engine="Pocket TTS")
    try:
        job.validate()
    except ValueError as exc:
        assert "Pocket TTS" in str(exc)
        return
    raise AssertionError("expected ValueError")


def test_job_allows_pocket_supported_language(tmp_path):
    from dubbing.config import DubJob
    DubJob(input=Path("a.mp3"), target_lang="fr", engine="Pocket TTS").validate()


def test_dub_language_labels_round_trip():
    from dubbing import DUBBING_LANGUAGES
    from dubbing import dub_language_code
    from dubbing import dub_language_label
    assert len(DUBBING_LANGUAGES) >= 10
    for code in DUBBING_LANGUAGES:
        assert dub_language_code(dub_language_label(code)) == code
    assert dub_language_code("Hungarian (hu)") == "hu"


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
    # Music kept by default: auto-install handles the isolated dep (2026-11:
    # opt-in default produced music-less dubs and went unnoticed).
    assert DEFAULT_DUBBING_SETTINGS["separation_enabled"] is True
    assert DEFAULT_DUBBING_SETTINGS["audio_output_format"] == "mp3"
    assert DEFAULT_DUBBING_SETTINGS["target_lang"] == "hu"
    assert DEFAULT_DUBBING_SETTINGS["source_lang"] == "en"


def test_phase_isolation_audio_path():
    import subprocess
    import sys
    code = "import dubbing.pipeline, sys; sys.exit(1 if 'dubbing.video' in sys.modules else 0)"
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True)
    assert proc.returncode == 0, "audio-only pipeline path must not import dubbing.video"


def test_missing_deps_structure():
    from dubbing import missing_dependencies
    from dubbing import pip_missing_specs
    plain = missing_dependencies(False)
    assert "separator" not in [d["key"] for d in plain]
    with_sep = missing_dependencies(True)
    assert "separator" in [d["key"] for d in with_sep]
    assert all(set(d) >= {"key", "label", "ok", "pip", "needs_sudo", "hint"} for d in plain)
    assert isinstance(pip_missing_specs(False), list)
