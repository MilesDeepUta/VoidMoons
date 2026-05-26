"""
Build a pastebin-ready export that is byte-for-byte indistinguishable
from a real EVE moon-survey paste.

We reuse the header bytes (and any trailer bytes) captured the first time
the user pasted real EVE data, stored in user.db meta table. Each moon's
raw_chunk bytes go in untouched, in deterministic order.

Returns bytes — caller is responsible for writing to clipboard / file in
binary mode (UI uses QClipboard.setText on a decoded copy for the textbox
display, but the bytes object is the authoritative payload).
"""
from __future__ import annotations

from typing import Iterable


def build_export(
    chunks: Iterable[tuple[int, bytes]],
    header_bytes: bytes = b"",
    trailer_bytes: bytes = b"",
) -> bytes:
    """Concatenate header + raw_chunks (in given order) + trailer.

    chunks: iterable of (moon_id, raw_chunk_bytes). moon_id is informational;
            ordering is whatever the caller chose (typically by system,
            planet, moon).
    """
    parts: list[bytes] = []
    if header_bytes:
        parts.append(header_bytes)
    for _moon_id, chunk in chunks:
        parts.append(chunk)
    if trailer_bytes:
        parts.append(trailer_bytes)
    return b"".join(parts)
