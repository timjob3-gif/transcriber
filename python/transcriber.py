import os
import threading
import time
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
    """Чистый текст — один абзац на сегмент. Если есть speaker — группирует по спикеру."""
    path = output_dir / f"{stem}.txt"
    has_speakers = any('speaker' in seg for seg in segments)
    with open(path, 'w', encoding='utf-8') as f:
        prev_speaker = None
        for seg in segments:
            text = seg['text'].strip()
            if not text:
                continue
            if has_speakers:
                speaker = seg.get('speaker', 'SPEAKER_0')
                if speaker != prev_speaker:
                    if prev_speaker is not None:
                        f.write('\n')
                    f.write(f"[{speaker}]\n")
                    prev_speaker = speaker
            f.write(text + '\n')
    return path


def write_srt(segments: list, output_dir: Path, stem: str) -> Path:
    """SubRip субтитры с таймкодами. Если есть speaker — добавляет метку в текст."""
    path = output_dir / f"{stem}.srt"
    has_speakers = any('speaker' in seg for seg in segments)
    with open(path, 'w', encoding='utf-8') as f:
        idx = 1
        for seg in segments:
            text = seg['text'].strip()
            if not text:
                continue
            if has_speakers:
                speaker = seg.get('speaker', 'SPEAKER_0')
                # Коротко: "S0: текст", "S1: текст"
                label = speaker.replace('SPEAKER_', 'S')
                text = f"{label}: {text}"
            f.write(f"{idx}\n")
            f.write(f"{_fmt_srt(seg['start'])} --> {_fmt_srt(seg['end'])}\n")
            f.write(f"{text}\n\n")
            idx += 1
    return path


def write_vtt(segments: list, output_dir: Path, stem: str) -> Path:
    """WebVTT для встраивания в видеоплеер. Если есть speaker — добавляет метку."""
    path = output_dir / f"{stem}.vtt"
    has_speakers = any('speaker' in seg for seg in segments)
    with open(path, 'w', encoding='utf-8') as f:
        f.write("WEBVTT\n\n")
        for seg in segments:
            text = seg['text'].strip()
            if not text:
                continue
            if has_speakers:
                speaker = seg.get('speaker', 'SPEAKER_0')
                label = speaker.replace('SPEAKER_', 'S')
                text = f"{label}: {text}"
            f.write(f"{_fmt_vtt(seg['start'])} --> {_fmt_vtt(seg['end'])}\n")
            f.write(f"{text}\n\n")
    return path


# ── Model dir ─────────────────────────────────────────────────────────────────

def get_model_dir() -> str:
    base = os.environ.get('APPDATA', Path.home())
    model_dir = Path(base) / 'Transcriber' / 'models'
    model_dir.mkdir(parents=True, exist_ok=True)
    return str(model_dir)


# ── Model download with progress ──────────────────────────────────────────────

# Примерный размер модели на диске (сжатый кэш HuggingFace)
_MODEL_SIZE_BYTES = {
    'tiny':     80 * 1024 * 1024,
    'tiny.en':  80 * 1024 * 1024,
    'base':    150 * 1024 * 1024,
    'base.en': 150 * 1024 * 1024,
    'small':   500 * 1024 * 1024,
    'small.en':500 * 1024 * 1024,
    'medium': 1550 * 1024 * 1024,
    'large-v2':3200 * 1024 * 1024,
    'large-v3':3200 * 1024 * 1024,
}


def _model_is_cached(model_name: str, model_dir: Path) -> bool:
    """Проверяет, скачана ли модель в HuggingFace-кэш."""
    safe_name = model_name.replace('/', '--')
    cache_root = model_dir / f'models--Systran--faster-whisper-{safe_name}'
    if not cache_root.exists():
        return False
    # Считаем модель скачанной если есть model.bin в snapshots
    for blob in cache_root.rglob('model.bin'):
        if blob.stat().st_size > 1024 * 1024:  # > 1 МБ
            return True
    return False


def download_model(model_name: str, emit) -> None:
    """Скачивает модель faster-whisper через HuggingFace Hub с прогрессом.

    События:
        {"type": "download_progress", "percent": 0..100, "status": "downloading"|"cached"|"complete"}
        {"type": "download_error",    "message": "..."}
    """
    model_dir = Path(get_model_dir())
    emit({"type": "download_progress", "percent": 0, "status": "downloading"})

    if _model_is_cached(model_name, model_dir):
        emit({"type": "download_progress", "percent": 100, "status": "cached"})
        return

    expected_bytes = _MODEL_SIZE_BYTES.get(model_name, 300 * 1024 * 1024)

    # Фоновый поток: следит за ростом размера кэш-папки и шлёт прогресс
    stop_event = threading.Event()
    last_pct = [0]

    def _track():
        while not stop_event.is_set():
            try:
                current = sum(
                    f.stat().st_size
                    for f in model_dir.rglob('*')
                    if f.is_file()
                )
                pct = min(90, max(2, int(current / expected_bytes * 90)))
                if pct != last_pct[0]:
                    last_pct[0] = pct
                    emit({"type": "download_progress", "percent": pct, "status": "downloading"})
            except Exception:
                pass
            time.sleep(1.5)

    tracker = threading.Thread(target=_track, daemon=True)
    tracker.start()

    try:
        from huggingface_hub import snapshot_download
        snapshot_download(
            repo_id=f'Systran/faster-whisper-{model_name}',
            cache_dir=str(model_dir),
            ignore_patterns=['*.msgpack', 'flax_model*', 'tf_model*', 'rust_model*'],
        )
        emit({"type": "download_progress", "percent": 100, "status": "complete"})
    except Exception as e:
        emit({"type": "download_error", "message": str(e)})
        raise
    finally:
        stop_event.set()


def transcribe(wav_path: Path, model_name: str, language: str | None, emit) -> dict:
    emit({"type": "progress", "percent": 22, "stage": "loading_model"})

    from faster_whisper import WhisperModel

    # torch.cuda может быть исключён PyInstaller при сборке exe —
    # оборачиваем в try/except, чтобы не падало на машинах без CUDA
    device = 'cpu'
    compute_type = 'int8'
    try:
        import torch
        if torch.cuda.is_available():
            device = 'cuda'
            compute_type = 'float16'
    except Exception:
        pass  # torch.cuda недоступен — остаёмся на CPU

    # Отправляем информацию о GPU/CPU один раз при первом запуске
    gpu_info: dict = {"device": device}
    if device == 'cuda':
        try:
            import torch
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
