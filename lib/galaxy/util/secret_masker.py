"""Hide known secret values in text, the way CI systems mask secrets in build logs.

This is best effort, as it is for GitHub Actions, GitLab and Jenkins: it finds exact copies of
known values and a few common encodings of them. A tool that changes a value in another way can
still print it, so a leaked secret should be rotated.
"""

import base64
import json
from collections.abc import (
    Iterable,
    Iterator,
)
from urllib.parse import quote

MASK = "***"
# Shorter values, and these placeholder words, would hide ordinary text (CircleCI and Travis skip them too).
MIN_SECRET_LENGTH = 4
NOT_SECRETS = {"true", "false", "none", "null"}
# Shorter encoded forms could match unrelated text.
MIN_ENCODED_LENGTH = 8


def secret_forms(values: Iterable[str]) -> list[str]:
    """Every form of ``values`` to look for, longest first."""
    forms: set[str] = set()
    for value in values:
        # A multi-line value is also masked line by line, since output can split or re-wrap it.
        for candidate in {value.strip(), *(line.strip() for line in value.splitlines())}:
            if len(candidate) < MIN_SECRET_LENGTH or candidate.lower() in NOT_SECRETS:
                continue
            forms.add(candidate)
            forms.update(encoded for encoded in _encoded_forms(candidate) if len(encoded) >= MIN_ENCODED_LENGTH)
    return sorted(forms, key=len, reverse=True)


def _encoded_forms(value: str) -> Iterator[str]:
    yield quote(value, safe="")
    yield json.dumps(value)[1:-1]
    data = value.encode("utf-8")
    # A value inside a longer base64 text, such as an HTTP basic auth header, encodes differently
    # depending on its position, so look for all three alignments, as Jenkins does.
    for offset in range(3):
        for encode in (base64.b64encode, base64.urlsafe_b64encode):
            encoded = encode(b"\0" * offset + data).decode("ascii").rstrip("=")
            # Drop the characters that also depend on the bytes around the value.
            start = (0, 2, 3)[offset]
            end = len(encoded) - (1 if (offset + len(data)) % 3 else 0)
            yield encoded[start:end]


def mask_secrets(text: str | None, forms: list[str], keep_length: bool = False) -> str | None:
    """Replace every place in ``text`` where one of ``forms`` occurs.

    Overlapping and adjacent matches are merged and replaced once, so no part of a value is left
    showing. With ``keep_length`` each hidden character becomes ``*``, so positions in the text do
    not change; otherwise each hidden part becomes ``***``.
    """
    if not text or not forms:
        return text
    ranges = []
    for form in forms:
        start = text.find(form)
        while start != -1:
            ranges.append((start, start + len(form)))
            start = text.find(form, start + 1)
    if not ranges:
        return text
    ranges.sort()
    merged = [list(ranges[0])]
    for start, end in ranges[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    pieces = []
    last = 0
    for start, end in merged:
        pieces.append(text[last:start])
        pieces.append("*" * (end - start) if keep_length else MASK)
        last = end
    pieces.append(text[last:])
    return "".join(pieces)


def read_masked_chunk(path: str, position: int, length: int, forms: list[str]) -> str:
    """Read ``length`` characters of a growing file from ``position``, with secrets masked.

    The text around the chunk is read too, so a secret cut by the chunk's edges is still found.
    Masking keeps the length, so a reader can keep counting positions by what it received. A value
    that may still be being written at the end of the file is held back until it is complete.
    """
    with open(path) as file:
        file.seek(position)
        chunk = file.read(length)
        if not forms:
            return chunk
        margin = max(len(form) for form in forms) - 1
        tail = file.read(margin)
    with open(path, "rb") as file:
        start = max(position - margin, 0)
        file.seek(start)
        head = file.read(position - start).decode("utf-8", errors="replace")
    window = head + chunk + tail
    end = len(head) + len(chunk)
    if len(tail) < margin:
        # The end of the file may hold the start of a value whose rest is not written yet.
        for size in range(min(margin, len(window)), 0, -1):
            suffix = window[-size:]
            if any(len(form) > size and form.startswith(suffix) for form in forms):
                end = max(min(end, len(window) - size), len(head))
                break
    masked = mask_secrets(window, forms, keep_length=True)
    assert masked is not None
    return masked[len(head) : end]
