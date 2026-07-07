"""Diagnostyka czasu analizy audio — uruchom z aktywnym venv:
    .venv\\Scripts\\python diag_audio.py <ścieżka do pliku wideo/LRF>
lub:
    python diag_audio.py <plik>   (jeśli aktywny venv z numpy/imageio-ffmpeg)
"""
import sys, time, subprocess, io, shutil, struct, tempfile
from pathlib import Path

if len(sys.argv) < 2:
    print("Użycie: python diag_audio.py <ścieżka do pliku wideo/LRF>")
    sys.exit(2)
LRF = sys.argv[1]
if not Path(LRF).exists():
    print(f"BŁĄD: plik nie istnieje: {LRF}")
    sys.exit(2)

try:
    import imageio_ffmpeg
    FF = imageio_ffmpeg.get_ffmpeg_exe()
    FF_SOURCE = "imageio-ffmpeg"
except Exception:
    FF = shutil.which("ffmpeg") or "ffmpeg"
    FF_SOURCE = "PATH"

# Sprawdź czy system ma ffmpeg na PATH (preferowane przez aplikację)
sys_ff = shutil.which("ffmpeg")
if sys_ff and sys_ff != FF:
    print(f"UWAGA: Systemowy ffmpeg z PATH różni się od imageio-ffmpeg!")
    print(f"  PATH:         {sys_ff}")
    print(f"  imageio:      {FF}")
    print(f"  Aplikacja użyje: PATH (po poprawce _resolve_ffmpeg)")
    FF_APP = sys_ff
else:
    FF_APP = FF

print(f"FFmpeg (diag):  {FF}  [{FF_SOURCE}]")
print(f"FFmpeg (app):   {FF_APP}")
print(f"LRF istnieje: {Path(LRF).exists()}, rozmiar: {Path(LRF).stat().st_size // 1_000_000} MB")
print()

CREATE_NO_WINDOW = 0x08000000

def step(label, fn):
    t = time.perf_counter()
    result = fn()
    print(f"  {time.perf_counter()-t:6.2f}s  {label}")
    return result

print("=== KROKI ===")

# 1. probe LRF
step("probe LRF (ffmpeg -i)", lambda: subprocess.run(
    [FF_APP, "-i", LRF], capture_output=True, creationflags=CREATE_NO_WINDOW))

# 2. ekstrakcja → plik tmp
def do_extract_file():
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        subprocess.run([FF_APP, "-y", "-i", LRF, "-vn", "-ac", "1", "-ar", "16000",
                        "-f", "wav", str(wav)], capture_output=True, creationflags=CREATE_NO_WINDOW)
        return wav.stat().st_size if wav.exists() else 0
size = step("ekstrakcja audio → plik tmp", do_extract_file)
print(f"         (rozmiar WAV: {size // 1024} KB)")

# 3. ekstrakcja → pipe
def do_pipe():
    cmd = [FF_APP, "-y", "-i", LRF, "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       creationflags=CREATE_NO_WINDOW)
    return r.stdout
wav_bytes = step("ekstrakcja audio → pipe", do_pipe)
print(f"         (bajty: {len(wav_bytes) // 1024} KB)")

# 4. numpy WAV parse (bez soundfile/libsndfile)
try:
    import numpy as np
except ImportError:
    print()
    print("BŁĄD: Brak modułu 'numpy'.")
    print("Uruchom skrypt z venv aplikacji:")
    print("  .venv\\Scripts\\python diag_audio.py")
    sys.exit(1)

def parse_wav(data):
    i = 12
    sr_found = 16000
    while i + 8 <= len(data):
        cid = data[i:i+4]
        csz = struct.unpack_from('<I', data, i + 4)[0]
        if cid == b'fmt ':
            sr_found = struct.unpack_from('<I', data, i + 12)[0]
        elif cid == b'data':
            raw = np.frombuffer(data[i+8:i+8+csz], dtype=np.int16)
            return raw.astype(np.float64) / 32768.0, sr_found
        i += 8 + csz
    raise ValueError("brak chunka data")

samples, sr = step("numpy WAV parse (bez soundfile)", lambda: parse_wav(wav_bytes))
print(f"         ({samples.size} próbek, sr={sr})")

# 5. soundfile (jeśli dostępne)
try:
    import soundfile as sf
    def do_sf():
        cmd = [FF_APP, "-y", "-i", LRF, "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"]
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           creationflags=CREATE_NO_WINDOW)
        s, sr2 = sf.read(io.BytesIO(r.stdout))
        return s.size, sr2
    n, sr2 = step("soundfile decode z pipe (dla porównania)", do_sf)
    print(f"         ({n} próbek, sr={sr2})")
except ImportError:
    print("  (soundfile niedostępne — OK, aplikacja używa numpy)")

# 6. pełny pipeline (pipe + numpy + waveform + onsety)
def do_full():
    cmd = [FF_APP, "-y", "-i", LRF, "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       creationflags=CREATE_NO_WINDOW)
    smp, sr2 = parse_wav(r.stdout)
    dur = smp.size / sr2
    n_b = min(20000, max(2000, int(dur * 200)))
    n = min(n_b, smp.size)
    bucket = smp.size // n
    trimmed = np.abs(smp[:n*bucket]).reshape(n, bucket)
    env = (trimmed.max(axis=1) / (trimmed.max() or 1)).tolist()
    # onsety
    win = max(1, int(sr2 * 0.02))
    nw = smp.size // win
    chunk = smp[:nw*win].reshape(nw, win)
    energy = np.sqrt((chunk.astype(np.float64)**2).mean(axis=1))
    med = np.median(energy)
    mad = np.median(np.abs(energy - med)) + 1e-9
    thr = med + 6.0 * mad
    onsets = [round(i * win / sr2, 3) for i in range(1, nw)
              if energy[i] >= thr and energy[i] > energy[i-1]]
    return len(env), len(onsets)
ne, no = step("PEŁNY PIPELINE (pipe + numpy + waveform + onsety)", do_full)
print(f"         (buckety={ne}, onsety={no})")

print()
print("Gotowe.")
