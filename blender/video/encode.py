import subprocess
from pathlib import Path


class VideoEncodeError(Exception):
    pass


def encodeFrames(frameDir, outPath, fps, pattern="frame_%05d.png"):
    """Encodes a numbered PNG sequence into an h264 mp4 by shelling out to ffmpeg (must be on PATH)."""
    outPath = Path(outPath).resolve()
    outPath.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", str(Path(frameDir) / pattern),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", str(outPath)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except FileNotFoundError as e:
        raise VideoEncodeError("ffmpeg is not on PATH; install it to encode video output") from e
    except subprocess.TimeoutExpired as e:
        raise VideoEncodeError(f"ffmpeg timed out encoding {frameDir}") from e
    if r.returncode != 0 or not outPath.is_file():
        raise VideoEncodeError(f"ffmpeg exited {r.returncode}: {r.stderr[-1500:]}")
    return {"outPath": str(outPath), "bytes": outPath.stat().st_size}
