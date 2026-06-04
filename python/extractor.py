import os
import shutil
import subprocess
import sys
from pathlib import Path


def get_ffmpeg() -> str:
    if hasattr(sys, '_MEIPASS'):
        return str(Path(sys._MEIPASS) / 'bin' / 'ffmpeg.exe')

    import glob

    # 1. Сначала проверяем фиксированные места
    candidates = [
        os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe'),
        r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
        r'C:\ffmpeg\bin\ffmpeg.exe',
    ]

    # 2. Glob по WinGet Packages (winget может установить в версионированную папку)
    packages_dir = os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\WinGet\Packages')
    if os.path.isdir(packages_dir):
        found_list = glob.glob(
            os.path.join(packages_dir, 'Gyan.FFmpeg*', '**', 'bin', 'ffmpeg.exe'),
            recursive=True,
        )
        candidates.extend(found_list)

    for path in candidates:
        if os.path.isfile(path):
            return path

    # 3. Поиск через PATH (расширенный + системный)
    extended = ';'.join(filter(None, [
        os.environ.get('PATH', ''),
        os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\WinGet\Links'),
    ]))
    found = shutil.which('ffmpeg', path=extended)
    return found or 'ffmpeg'


def _env_with_ffmpeg() -> dict:
    """Вернуть окружение с обновлённым PATH из реестра.
    Важно: winreg отдаёт сырые строки вида %LOCALAPPDATA%\\...,
    которые Windows НЕ разворачивает автоматически в кастомном env.
    Разворачиваем вручную через os.path.expandvars перед использованием.
    """
    import winreg
    paths = []
    for hive, sub in [(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'),
                      (winreg.HKEY_CURRENT_USER, r'Environment')]:
        try:
            key = winreg.OpenKey(hive, sub)
            val, _ = winreg.QueryValueEx(key, 'Path')
            paths.append(os.path.expandvars(val))   # ← разворачиваем %VAR%
        except Exception:
            pass
    env = os.environ.copy()
    if paths:
        env['PATH'] = ';'.join(paths) + ';' + env.get('PATH', '')
    return env


def extract_audio(input_path: str, output_dir: Path, emit) -> Path:
    emit({"type": "progress", "percent": 8, "stage": "extracting"})

    stem = Path(input_path).stem
    wav_path = output_dir / f"{stem}_audio.wav"

    cmd = [
        get_ffmpeg(),
        '-i', input_path,
        '-ar', '16000',
        '-ac', '1',
        '-c:a', 'pcm_s16le',
        '-y',
        str(wav_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, env=_env_with_ffmpeg())
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg: {result.stderr[-500:]}")

    emit({"type": "progress", "percent": 18, "stage": "extracted"})
    return wav_path
