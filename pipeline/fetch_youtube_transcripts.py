"""Fetch auto-generated captions from YouTube videos and convert to clean text.

Usage:
    python -m pipeline.fetch_youtube_transcripts <output_dir> <video_id1> [video_id2 ...]

Requires yt-dlp: pip install yt-dlp
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def _strip_vtt(vtt_content: str) -> str:
    """Parse a VTT captions file into clean running text."""
    lines = vtt_content.split("\n")
    text_lines: list[str] = []
    for line in lines:
        line = line.strip()
        if (not line
                or line.startswith("WEBVTT")
                or line.startswith("Kind:")
                or line.startswith("Language:")
                or "-->" in line
                or line.isdigit()):
            continue
        # Strip HTML tags (auto-captions have <c> tags)
        clean = re.sub(r"<[^>]+>", "", line)
        if clean:
            text_lines.append(clean)

    # Deduplicate consecutive repeats (VTT repeats lines for timing)
    deduped: list[str] = []
    for line in text_lines:
        if not deduped or line != deduped[-1]:
            deduped.append(line)

    return " ".join(deduped)


def fetch(video_id: str, output_dir: Path) -> Path | None:
    """Download + convert one video's captions. Returns path to .txt file or None."""
    output_dir.mkdir(parents=True, exist_ok=True)
    vtt_out = output_dir / f"{video_id}"

    result = subprocess.run(
        [
            "python", "-m", "yt_dlp",
            "--write-auto-sub",
            "--sub-lang", "en",
            "--skip-download",
            "--sub-format", "vtt",
            "-o", str(vtt_out),
            f"https://www.youtube.com/watch?v={video_id}",
        ],
        capture_output=True,
        text=True,
    )

    vtt_file = output_dir / f"{video_id}.en.vtt"
    if not vtt_file.exists():
        print(f"  [{video_id}] no captions available")
        print(result.stderr[-300:] if result.stderr else "")
        return None

    text = _strip_vtt(vtt_file.read_text(encoding="utf-8"))
    txt_file = output_dir / f"{video_id}.txt"
    txt_file.write_text(
        f"# Video: https://youtube.com/watch?v={video_id}\n\n{text}",
        encoding="utf-8",
    )
    print(f"  [{video_id}] {len(text)} chars -> {txt_file.name}")
    return txt_file


def main():
    if len(sys.argv) < 3:
        print("Usage: python -m pipeline.fetch_youtube_transcripts <output_dir> <video_id1> [video_id2 ...]")
        sys.exit(1)

    output_dir = Path(sys.argv[1])
    video_ids = sys.argv[2:]

    print(f"Fetching {len(video_ids)} videos to {output_dir}\n")
    for vid in video_ids:
        fetch(vid, output_dir)


if __name__ == "__main__":
    main()
