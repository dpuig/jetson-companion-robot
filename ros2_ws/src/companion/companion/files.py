"""Turns an uploaded file into something the model can take: text, an image, or a transcript."""
import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path

import requests

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
AUDIO_EXT = {".wav", ".mp3", ".ogg", ".flac", ".m4a"}


@dataclass
class Extracted:
    name: str
    text: str = ""          # extracted or transcribed text
    image_b64: str = ""     # data for an image_url part, when the file is an image
    mime: str = ""


def extract(path: str, max_chars: int, whisper_url: str) -> Extracted:
    p = Path(path).expanduser()
    ext = p.suffix.lower()
    out = Extracted(name=p.name)

    if ext in IMAGE_EXT:
        out.mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
        out.image_b64 = base64.b64encode(p.read_bytes()).decode()
        return out

    if ext == ".pdf":
        from pypdf import PdfReader

        pages = [page.extract_text() or "" for page in PdfReader(str(p)).pages]
        out.text = "\n\n".join(f"[page {i + 1}]\n{t}" for i, t in enumerate(pages) if t.strip())
    elif ext in AUDIO_EXT:
        # whisper-server only reads 16 kHz WAV unless started with --convert, so send WAV as-is.
        with p.open("rb") as f:
            r = requests.post(whisper_url, files={"file": f}, data={"response_format": "json"}, timeout=120)
        r.raise_for_status()
        out.text = "[transcript] " + r.json().get("text", "").strip()
    else:
        out.text = p.read_text(errors="replace")

    if len(out.text) > max_chars:
        out.text = out.text[:max_chars] + f"\n…[truncated, {len(out.text) - max_chars} more characters]"
    return out
