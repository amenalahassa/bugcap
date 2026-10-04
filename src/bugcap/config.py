"""Global (per-user) config: object store settings etc. Secrets never live here."""
from typing import Any

from . import tomlio
from .paths import config_path

KNOWN_KEYS = {
    "storage.bucket": "Bucket name (S3 / R2 / any S3-compatible)",
    "storage.endpoint_url": "Custom endpoint, e.g. https://<account>.r2.cloudflarestorage.com",
    "storage.region": "Region (use 'auto' for R2)",
    "storage.prefix": "Key prefix inside the bucket, e.g. bugcap/",
    "storage.public_base_url": "Public URL base (R2 public bucket / CDN). If unset, presigned URLs are used",
}


def load() -> dict[str, Any]:
    return tomlio.load(config_path())


def get(key: str) -> Any:
    section, _, name = key.partition(".")
    return load().get(section, {}).get(name)


def set_value(key: str, value: str) -> None:
    section, _, name = key.partition(".")
    if not name:
        raise ValueError("config keys look like 'storage.bucket'")
    data = load()
    data.setdefault(section, {})[name] = value
    tomlio.save(config_path(), data)


def unset(key: str) -> None:
    section, _, name = key.partition(".")
    data = load()
    data.get(section, {}).pop(name, None)
    tomlio.save(config_path(), data)
