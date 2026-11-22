"""Subtitles: round-trip, escaping, mux args, norm hash."""
from pathlib import Path

from dubbing import subtitles
from dubbing.config import Segment


def test_srt_round_trip(tmp_path):
    segs = [Segment(0.0, 1.5, translated="Teszt ékezés őű"),
            Segment(2.0, 3.25, translated="Második sor")]
    p = subtitles.write_srt(segs, tmp_path / "out.srt")
    back = subtitles.parse_srt(p)
    assert len(back) == 2
    assert back[0].translated == "Teszt ékezés őű"
    assert abs(back[1].start - 2.0) < 0.01


def test_burn_filter_windows_path():
    f = subtitles.build_burn_filter(Path(r"C:\My Vids\teszt srt.srt"))
    assert f[0] == "-vf"
    assert "subtitles=" in f[1]
    assert "\\:" in f[1]  # drive colon escaped


def test_mux_args_by_container(tmp_path):
    assert subtitles.soft_sub_mux_args(tmp_path / "a.srt", "mp4") == ["-c:s", "mov_text"]
    assert subtitles.soft_sub_mux_args(tmp_path / "a.srt", "mkv") == ["-c:s", "srt"]


def test_norm_hash_stable_not_bytes(tmp_path):
    a = [Segment(0.0, 1.0, translated="Hello")]
    b = [Segment(0.0, 1.0, translated="Hello ")]
    assert subtitles.srt_norm_hash(a) == subtitles.srt_norm_hash(b)
