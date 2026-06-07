import argparse
import json
import sys
from pathlib import Path

from extractor import extract_audio
from downloader import download_audio
from transcriber import transcribe, write_txt, write_srt, write_vtt, download_model
from logger import log


def emit(obj: dict):
    # ensure_ascii=True: кириллица → \uXXXX → чистый ASCII-байты
    # Это защищает от cp1251-stdout когда Python запущен как subprocess из Rust
    line = json.dumps(obj, ensure_ascii=True)
    print(line, flush=True)
    log.debug("EMIT %s", line[:120])


def is_url(s: str) -> bool:
    return s.startswith('http://') or s.startswith('https://')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--action', default='transcribe',
                        choices=['transcribe', 'download-model'],
                        help='transcribe (default) или download-model — только скачать модель')
    parser.add_argument('--input', help='File path or URL (для transcribe)')
    parser.add_argument('--output', help='Output directory (для transcribe)')
    parser.add_argument('--model', default='base')
    parser.add_argument('--language', default=None, help='Language code, e.g. ru, en. None = auto')
    parser.add_argument('--diarize', action='store_true',
                        help='Включить определение спикеров (resemblyzer)')
    parser.add_argument('--speakers', type=int, default=None,
                        help='Ожидаемое число спикеров (для --diarize). None = автодетект')
    args = parser.parse_args()

    # ── Режим скачивания модели ───────────────────────────────────────────────
    if args.action == 'download-model':
        log.info("DOWNLOAD-MODEL model=%s", args.model)
        download_model(args.model, emit)
        return
    log.info("START input=%s output=%s model=%s diarize=%s",
             args.input[:80], args.output, args.model, args.diarize)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    wav_path = None
    try:
        if is_url(args.input):
            wav_path = download_audio(args.input, output_dir, emit)
            source_stem = 'downloaded'
        else:
            wav_path = extract_audio(args.input, output_dir, emit)
            source_stem = Path(args.input).stem

        # Инкрементальный вывод: каждый сегмент сразу пишется в {stem}.partial.json
        partial_path = output_dir / f'{source_stem}.partial.json'
        _inc_segs = []

        def _emit_inc(obj):
            emit(obj)
            if obj.get('type') == 'segment':
                _inc_segs.append({
                    'start': obj['start'],
                    'end':   obj['end'],
                    'text':  obj['text'],
                })
                try:
                    partial_path.write_text(
                        json.dumps(
                            {'source': args.input, 'partial': True, 'segments': _inc_segs},
                            ensure_ascii=False, indent=2,
                        ),
                        encoding='utf-8',
                    )
                except OSError:
                    pass

        result = transcribe(wav_path, args.model, args.language, _emit_inc)
        result['source'] = args.input

        # ── Диаризация (опционально) ──────────────────────────────────────────
        if args.diarize:
            emit({"type": "progress", "percent": 97, "stage": "diarizing"})
            log.info("DIARIZE start, speakers=%s", args.speakers)
            try:
                from diarizer import diarize, assign_speakers
                diar_segs = diarize(str(wav_path), num_speakers=args.speakers)
                result['segments'] = assign_speakers(result['segments'], diar_segs)
                result['diarized'] = True
                result['num_speakers'] = len({s['speaker'] for s in result['segments']})
                log.info("DIARIZE done, speakers=%d", result['num_speakers'])
            except Exception as e:
                log.warning("DIARIZE failed: %s — continuing without speaker labels", e)
                emit({"type": "warning", "message": f"Диаризация не удалась: {e}"})

        output_path = output_dir / f'{source_stem}.json'
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        txt_path = write_txt(result['segments'], output_dir, source_stem)
        srt_path = write_srt(result['segments'], output_dir, source_stem)
        vtt_path = write_vtt(result['segments'], output_dir, source_stem)

        partial_path.unlink(missing_ok=True)

        emit({
            "type": "done",
            "output": str(output_path),
            "txt":    str(txt_path),
            "srt":    str(srt_path),
            "vtt":    str(vtt_path),
        })
    finally:
        if wav_path is not None:
            wav_path.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        emit({"type": "error", "message": str(e)})
        sys.exit(1)
