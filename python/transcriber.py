import os
from pathlib import Path


# ── Export helpers ────────────────────────────────────────────────────────────

def _fmt_srt(seconds: float) -> str:
    """Форматирует секунды в HH:MM:SS,mmm (формат SRT)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _fmt_vtt(seconds: float) -> str:
    """Форматирует секунды в HH:MM:SS.mmm (формат VTT)."""
    return _fmt_srt(seconds).replace(',', '.')


def write_txt(segments: list, output_dir: Path, stem: str) -> Path:
    """Чистый текст — один абзац на сегмент."""
    path = output_dir / f"{stem}.txt"
    with open(path, 'w', encoding='utf-8') as f:
        for seg in segments:
            text = seg['text'].strip()
            if text:
                f.write(text + '\n')
    return path


def write_srt(segments: list, output_dir: Path, stem: str) -> Path:
    """SubRip субтитры с таймкодами."""
    path = output_dir / f"{stem}.srt"
    with open(path, 'w', encoding='utf-8') as f:
        for i, seg in enumerate(segments, 1):
            text = seg['text'].strip()
            if not text:
                continue
            f.write(f"{i}\n")
            f.write(f"{_fmt_srt(seg['start'])} --> {_fmt_srt(seg['end'])}\n")
            f.write(f"{text}\n\n")
    return path


def write_vtt(segments: list, output_dir: Path, stem: str) -> Path:
    """WebVTT для встраивания в видеоплеер."""
    path = output_dir / f"{stem}.vtt"
    with open(path, 'w', encoding='utf-8') as f:
        f.write("WEBVTT\n\n")
        for seg in segments:
            text = seg['text'].strip()
            if not text:
                continue
            f.write(f"{_fmt_vtt(seg['start'])} --> {_fmt_vtt(seg['end'])}\n")
            f.write(f"{text}\n\n")
    return path


# ── Model dir ─────────────────────────────────────────────────────────────────

def get_model_dir() -> str:
    base = os.environ.get('APPDATA', Path.home())
    model_dir = Path(base) / 'transcriber' / 'models'
    model_dir.mkdir(parents=True, exist_ok=True)
    return str(model_dir)


def transcribe(wav_path: Path, model_name: str, language: str | None, emit) -> dict:
    emit({"type": "progress", "percent": 22, "stage": "loading_model"})

    from faster_whisper import WhisperModel
    import torch

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    compute_type = 'float16' if device == 'cuda' else 'int8'

    # Отправляем информацию о GPU/CPU один раз при первом запуске
    gpu_info: dict = {"device": device}
    if device == 'cuda':
        try:
            gpu_info["name"]  = torch.cuda.get_device_name(0)
            total = torch.cuda.get_device_properties(0).total_memory
            gpu_info["vram_gb"] = round(total / 1024**3, 1)
        except Exception:
            pass
    emit({"type": "gpu_info", **gpu_info})

    model = WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
        download_root=get_model_dir(),
    )

    emit({"type": "progress", "percent": 30, "stage": "transcribing"})

    segments_iter, info = model.transcribe(
        str(wav_path),
        language=language,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )

    segments = []
    duration = info.duration or 1

    for seg in segments_iter:
        segment = {
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text.strip(),
        }
        segments.append(segment)
        emit({"type": "segment", **segment})

        pct = 30 + int((seg.end / duration) * 65)
        emit({"type": "progress", "percent": min(pct, 95), "stage": "transcribing"})

    return {
        "source": str(wav_path),
        "language": info.language,
        "language_probability": round(info.language_probability, 3),
        "duration": round(info.duration, 3),
        "segments": segments,
    }
