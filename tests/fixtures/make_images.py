"""Write minimal valid sample images (and a non-image) for ingestion tests."""
import base64
import struct
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent


def png_bytes() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    raw = b"\x00\xff\x00\x00"  # filter byte + one RGB pixel
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def jpeg_bytes() -> bytes:
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"


def gif_bytes() -> bytes:
    return base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


def webp_bytes() -> bytes:
    payload = b"WEBPVP8 " + struct.pack("<I", 2) + b"\x00\x00"
    return b"RIFF" + struct.pack("<I", len(payload)) + payload


SAMPLES = {
    "sample.png": png_bytes,
    "sample.jpg": jpeg_bytes,
    "sample.gif": gif_bytes,
    "sample.webp": webp_bytes,
}


def write_all(directory: Path = HERE) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, make in SAMPLES.items():
        (directory / name).write_bytes(make())
    (directory / "not-image.txt").write_text("this is not an image\n")


if __name__ == "__main__":
    write_all()
