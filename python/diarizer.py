"""
Диаризация спикеров: resemblyzer + webrtcvad.

Публичный API:
    diarize(audio_path, num_speakers=None) → list[dict]
    assign_speakers(whisper_segments, diar_segments) → list[dict]
"""

import struct
import collections
import numpy as np


# ──────────────────────────────────────────────────────────────────────────────
# Низкоуровневые утилиты для работы с PCM
# ──────────────────────────────────────────────────────────────────────────────

def _read_wave_mono16(path: str) -> tuple:
    """
    Читает WAV-файл и возвращает (pcm_bytes_16bit_mono, sample_rate).
    Стерео → моно усреднением каналов.
    """
    import wave
    with wave.open(path, 'rb') as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        rate = wf.getframerate()
        pcm = wf.readframes(wf.getnframes())

    # 8-bit → 16-bit
    if sample_width == 1:
        u8 = np.frombuffer(pcm, dtype=np.uint8).astype(np.int16)
        pcm = ((u8 - 128) * 256).astype(np.int16).tobytes()

    # Стерео → моно
    if n_channels == 2:
        samples = np.frombuffer(pcm, dtype=np.int16)
        mono = ((samples[0::2].astype(np.int32) + samples[1::2].astype(np.int32)) // 2).astype(np.int16)
        pcm = mono.tobytes()

    return pcm, rate


def _resample_to_16k(pcm: bytes, src_rate: int) -> bytes:
    """Ресемплирует 16-bit моно PCM → 16 000 Hz через librosa."""
    if src_rate == 16000:
        return pcm
    import librosa
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    resampled = librosa.resample(samples, orig_sr=src_rate, target_sr=16000)
    out = (resampled * 32768.0).clip(-32768, 32767).astype(np.int16)
    return out.tobytes()


# ──────────────────────────────────────────────────────────────────────────────
# VAD (Voice Activity Detection) через webrtcvad
# ──────────────────────────────────────────────────────────────────────────────

def _vad_segments(pcm_16k: bytes, sr: int = 16000,
                  aggressiveness: int = 2, frame_ms: int = 30) -> list:
    """
    Выделяет речевые сегменты из 16-kHz 16-bit моно PCM.

    Возвращает список (start_sec, end_sec, pcm_chunk).
    Сегменты короче 0.5 сек отбрасываются.
    """
    import webrtcvad
    vad = webrtcvad.Vad(aggressiveness)

    frame_len = int(sr * frame_ms / 1000) * 2   # байт на фрейм
    num_frames = len(pcm_16k) // frame_len

    RING = 10       # скользящее окно для сглаживания
    THRESH = 0.75   # порог перехода

    ring = collections.deque(maxlen=RING)
    triggered = False
    start_frame = 0
    segments = []

    for i in range(num_frames):
        frame = pcm_16k[i * frame_len: (i + 1) * frame_len]
        try:
            is_speech = vad.is_speech(frame, sr)
        except Exception:
            is_speech = False
        ring.append(1 if is_speech else 0)

        if not triggered:
            if len(ring) == RING and sum(ring) / RING >= THRESH:
                triggered = True
                start_frame = max(0, i - RING)
        else:
            if len(ring) == RING and sum(ring) / RING < (1 - THRESH):
                triggered = False
                end_frame = i
                seg_pcm = pcm_16k[start_frame * frame_len: end_frame * frame_len]
                if len(seg_pcm) / 2 / sr >= 0.5:
                    segments.append((
                        start_frame * frame_ms / 1000,
                        end_frame * frame_ms / 1000,
                        seg_pcm,
                    ))

    # Последний открытый сегмент
    if triggered:
        seg_pcm = pcm_16k[start_frame * frame_len:]
        if len(seg_pcm) / 2 / sr >= 0.5:
            segments.append((
                start_frame * frame_ms / 1000,
                num_frames * frame_ms / 1000,
                seg_pcm,
            ))

    return segments


# ──────────────────────────────────────────────────────────────────────────────
# Основная диаризация
# ──────────────────────────────────────────────────────────────────────────────

def diarize(audio_path: str, num_speakers: int | None = None) -> list:
    """
    Определяет спикеров в аудиофайле.

    Параметры:
        audio_path   — путь к WAV-файлу (любая частота/каналы)
        num_speakers — ожидаемое число спикеров; None = автодетект (2..6)

    Возвращает:
        [{"start": float, "end": float, "speaker": "SPEAKER_0"}, ...]
    """
    from resemblyzer import VoiceEncoder
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.preprocessing import normalize

    pcm, sr = _read_wave_mono16(audio_path)
    pcm16 = _resample_to_16k(pcm, sr)
    segs = _vad_segments(pcm16)

    if not segs:
        return []

    encoder = VoiceEncoder(device="cpu")
    embeddings = []
    valid_segs = []

    for start, end, seg_pcm in segs:
        samples = np.frombuffer(seg_pcm, dtype=np.int16).astype(np.float32) / 32768.0
        try:
            emb = encoder.embed_utterance(samples)
            embeddings.append(emb)
            valid_segs.append((start, end))
        except Exception:
            pass  # слишком короткий сегмент — пропускаем

    if len(embeddings) < 2:
        # Мало сегментов — весь файл один спикер
        return [{"start": s, "end": e, "speaker": "SPEAKER_0"} for s, e in valid_segs]

    X = normalize(np.array(embeddings))

    # Автодетект числа спикеров по силуэтному коэффициенту
    if num_speakers is None:
        from sklearn.metrics import silhouette_score
        best_k, best_score = 2, -1.0
        max_k = min(6, len(X) - 1)  # silhouette требует n_labels < n_samples
        for k in range(2, max_k + 1):
            labels = AgglomerativeClustering(n_clusters=k).fit_predict(X)
            if len(set(labels)) < 2:
                continue
            sc = silhouette_score(X, labels)
            if sc > best_score:
                best_score, best_k = sc, k
        num_speakers = best_k

    labels = AgglomerativeClustering(n_clusters=num_speakers).fit_predict(X)

    result = [
        {"start": start, "end": end, "speaker": f"SPEAKER_{lbl}"}
        for (start, end), lbl in zip(valid_segs, labels)
    ]
    result.sort(key=lambda x: x["start"])
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Слияние транскрипции и диаризации
# ──────────────────────────────────────────────────────────────────────────────

def assign_speakers(whisper_segments: list, diar_segments: list) -> list:
    """
    Добавляет поле 'speaker' к каждому сегменту Whisper.

    Для каждого сегмента находит спикера с максимальным перекрытием
    по времени с сегментами диаризации.

    Параметры:
        whisper_segments — список {"start", "end", "text"}
        diar_segments    — список {"start", "end", "speaker"} из diarize()

    Возвращает:
        список {"start", "end", "text", "speaker"}
    """
    if not diar_segments:
        return [{**seg, "speaker": "SPEAKER_0"} for seg in whisper_segments]

    result = []
    for seg in whisper_segments:
        ws, we = seg["start"], seg["end"]
        best_speaker = "SPEAKER_0"
        best_overlap = 0.0

        for ds in diar_segments:
            overlap = max(0.0, min(we, ds["end"]) - max(ws, ds["start"]))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = ds["speaker"]

        result.append({**seg, "speaker": best_speaker})

    return result
