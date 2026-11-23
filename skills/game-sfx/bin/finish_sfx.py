#!/usr/bin/env python3
"""Make raw takes game-ready with FFmpeg: mono, trimmed, faded, loudness-matched, exported.

    python finish_sfx.py takes/ game_ready/                   # WAV out, -20 LUFS for clips >= 1 s
    python finish_sfx.py takes/ game_ready/ --format ogg --lufs -18
    python finish_sfx.py takes/ game_ready/ --stereo          # keep stereo (ambience, music stings)
    python finish_sfx.py takes/ game_ready/ --dry-run         # print the ffmpeg commands only

Per file: high-pass at 20 Hz (DC and rumble), trim silence at both ends, 3 ms fade in and up to 50 ms fade out,
then loudness. EBU R128 loudness (LUFS) is unreliable below about 1 s, so short clips are peak-normalised to
-1 dBFS instead and long ones get two-pass loudnorm. Set per-category volume in the game, not here.
Needs ffmpeg and ffprobe on PATH (or FFMPEG / FFPROBE set). Writes a manifest.json listing every output.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
FFPROBE = os.environ.get("FFPROBE") or shutil.which("ffprobe")
EXTS = (".wav", ".flac", ".mp3", ".ogg", ".aif", ".aiff")


def run(cmd, dry):
    if dry:
        print(" ".join('"%s"' % c if " " in c else c for c in cmd))
        return ""
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit("ffmpeg failed:\n" + out.stderr[-2000:])
    return out.stderr


def duration(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True)
    return float(out.stdout.strip() or 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--lufs", type=float, default=-20.0)
    ap.add_argument("--format", choices=["wav", "ogg", "mp3"], default="wav")
    ap.add_argument("--stereo", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not FFMPEG or not FFPROBE:
        raise SystemExit("ffmpeg/ffprobe not found: install FFmpeg or set FFMPEG and FFPROBE")
    os.makedirs(a.dst, exist_ok=True)
    codec = {"wav": ["-c:a", "pcm_s16le"], "ogg": ["-c:a", "libvorbis", "-q:a", "5"], "mp3": ["-c:a", "libmp3lame", "-b:a", "128k"]}[a.format]
    ch = ["-ac", "2" if a.stereo else "1", "-ar", "44100"]
    trim = ("highpass=f=20,silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.01,"
            "areverse,silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.03,areverse")
    manifest = []
    for name in sorted(os.listdir(a.src)):
        if not name.lower().endswith(EXTS):
            continue
        src = os.path.join(a.src, name)
        stem = os.path.splitext(name)[0]
        tmp = os.path.join(a.dst, stem + ".trim.wav")
        out = os.path.join(a.dst, "%s.%s" % (stem, a.format))
        run([FFMPEG, "-hide_banner", "-y", "-i", src, *ch, "-af", trim, tmp], a.dry_run)
        dur = 1.0 if a.dry_run else duration(tmp)
        fo = min(0.05, dur / 4)
        fades = "afade=t=in:d=0.003,afade=t=out:st=%.4f:d=%.4f" % (max(0.0, dur - fo), fo)
        if dur >= 1.0:
            meas = run([FFMPEG, "-hide_banner", "-y", "-i", tmp, "-af", "loudnorm=I=%s:TP=-1.5:LRA=11:print_format=json" % a.lufs, "-f", "null", "-"], a.dry_run)
            m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", meas or "", re.S)
            if m:
                j = json.loads(m.group(0))
                norm = ("loudnorm=I={I}:TP=-1.5:LRA=11:measured_I={input_i}:measured_TP={input_tp}:measured_LRA={input_lra}:"
                        "measured_thresh={input_thresh}:offset={target_offset}:linear=true").format(I=a.lufs, **j)
            else:
                norm = "loudnorm=I=%s:TP=-1.5:LRA=11" % a.lufs
            chain, mode = fades + "," + norm, "loudnorm %s LUFS" % a.lufs
        else:
            vol = run([FFMPEG, "-hide_banner", "-y", "-i", tmp, "-af", "volumedetect", "-f", "null", "-"], a.dry_run)
            m = re.search(r"max_volume:\s*(-?[\d.]+) dB", vol or "")
            gain = -1.0 - float(m.group(1)) if m else 0.0
            chain, mode = fades + ",volume=%.2fdB" % gain, "peak -1 dBFS"
        run([FFMPEG, "-hide_banner", "-y", "-i", tmp, "-af", chain, *ch, *codec, out], a.dry_run)
        if not a.dry_run:
            os.remove(tmp)
        manifest.append({"source": src.replace(os.sep, "/"), "output": out.replace(os.sep, "/"), "seconds": round(dur, 3), "level": mode})
        print("%-40s %.2f s  %s" % (out, dur, mode))
    if not a.dry_run:
        with open(os.path.join(a.dst, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)


if __name__ == "__main__":
    main()
