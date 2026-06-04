import os
import shutil
import subprocess
import sys
from pathlib import Path

from extractor import _env_with_ffmpeg


def get_ytdlp() -> str:
    if hasattr(sys, '_MEIPASS'):
        return str(Path(sys._MEIPASS) / 'bin' / 'yt-dlp.exe')
    return shutil.which('yt-dlp') or 'yt-dlp'


def get_ffmpeg_dir() -> str:
    """Папка с ffmpeg.exe для передачи в --ffmpeg-location."""
    if hasattr(sys, '_MEIPASS'):
        return str(Path(sys._MEIPASS) / 'bin')
    env = _env_with_ffmpeg()
    found = shutil.which('ffmpeg', path=env.get('PATH', ''))
    if found:
        return str(Path(found).parent)
    return ''


def download_audio(url: str, output_dir: Path, emit) -> Path:
    emit({"type": "progress", "percent": 5, "stage": "downloading"})

    wav_path = output_dir / 'downloaded_audio.wav'
    ffmpeg_dir = get_ffmpeg_dir()

    cmd = [
        get_ytdlp(),
        '--extract-audio',
        '--audio-format', 'wav',
        '--postprocessor-args', 'ffmpeg:-ar 16000 -ac 1',
        '--no-playlist',
        '-o', str(wav_path.with_suffix('')),
    ]
    if ffmpeg_dir:
        cmd += ['--ffmpeg-location', ffmpeg_dir]
    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True, env=_env_with_ffmpeg())
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp: {result.stderr[-500:]}")

    emit({"type": "progress", "percent": 18, "stage": "downloaded"})
    return wav_path
