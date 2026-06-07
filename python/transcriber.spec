# transcriber.spec — PyInstaller spec для transcriber-core.exe
#
# Сборка:
#   cd Транскрибатор\python
#   .\fetch_bins.ps1          # один раз — скачать ffmpeg.exe + yt-dlp.exe
#   pyinstaller transcriber.spec
#   # Результат: dist\transcriber-core.exe
#
# Требования перед сборкой:
#   pip install pyinstaller
#   python/bin/ffmpeg.exe    — из fetch_bins.ps1
#   python/bin/yt-dlp.exe   — из fetch_bins.ps1

import os
import site
from pathlib import Path

block_cipher = None

# Путь к папке python/
HERE = Path(SPECPATH)
BIN_DIR = HERE / 'bin'

# Папка site-packages текущего Python
# getsitepackages() возвращает несколько путей — берём тот, где есть pip
site_packages = next(p for p in site.getsitepackages() if Path(p, 'pip').exists())

a = Analysis(
    ['main.py'],
    pathex=[str(HERE)],
    binaries=[
        # ffmpeg.exe и yt-dlp.exe — попадают в sys._MEIPASS/bin/
        (str(BIN_DIR / 'ffmpeg.exe'),  'bin'),
        (str(BIN_DIR / 'yt-dlp.exe'),  'bin'),
    ],
    datas=[
        # Предобученная модель resemblyzer (голосовые эмбеддинги)
        (str(Path(site_packages) / 'resemblyzer' / 'pretrained.pt'), 'resemblyzer'),
        # Silero VAD ONNX-модель для faster-whisper
        (str(Path(site_packages) / 'faster_whisper' / 'assets' / 'silero_vad_v6.onnx'),
         'faster_whisper/assets'),
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # --collect-all для пакетов с C-расширениями и динамическими импортами
    # ctranslate2: C-бэкенд faster-whisper; без этого краш на чистой машине
    # faster_whisper, tokenizers, huggingface_hub, tqdm: динамические импорты
    # resemblyzer/librosa/sklearn: диаризация спикеров
    hiddenimports=[
        # resemblyzer использует динамические импорты
        'resemblyzer',
        'webrtcvad',
        # scikit-learn кластеризация
        'sklearn.cluster._agglomerative',
        'sklearn.metrics.pairwise',
        'sklearn.utils._typedefs',
        'sklearn.neighbors._partition_nodes',
        # numba (зависимость resemblyzer через librosa)
        'numba',
        'numba.core',
        'llvmlite',
    ],
    collect_all=[
        'ctranslate2',
        'faster_whisper',
        'tokenizers',
        'huggingface_hub',
        'tqdm',
        # Диаризация спикеров
        'resemblyzer',
        'librosa',
        'sklearn',
        'numba',
        'llvmlite',
    ],
    excludes=[
        # НЕ исключаем torch.cuda — нужен для torch.cuda.is_available()
        # (даже на CPU-машинах модуль должен импортироваться без ошибок)
        'caffe2',
        'tensorboard',
        'PIL',
        'tkinter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='transcriber-core',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,           # UPX-сжатие уменьшает размер exe
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,       # консольный режим — stdout нужен для JSON-событий
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Иконка опциональна — раскомментировать если появится icon.ico
    # icon='../src-tauri/icons/icon.ico',
)
