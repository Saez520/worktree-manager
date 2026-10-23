"""Composition of worktree closure commit messages.

This module owns the deterministic transformation from an optional title and
body supplied by the caller into the subject and body written to the destination
repository. The neutral (English) fallback used when no title is supplied is
defined here so that a standalone closure never produces an empty commit message.
"""
from __future__ import annotations

import re


# Neutral fallback used by the standalone manager. The consuming project may
# override the wording by supplying commit_title/commit_body.
GENERIC_SUBJECT = "Complete {work_id} (generic closure)"
GENERIC_BODY = "No delivery description was available at closure time."


def _normalize_title(value):
    if value is None:
        return ""
    text = str(value)
    # Replace line breaks and null bytes with spaces, then collapse whitespace.
    text = text.replace("\r", " ").replace("\n", " ").replace("\x00", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_body(value):
    if value is None:
        return ""
    text = str(value)
    # Normalize line endings and trim trailing whitespace per line.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip(" \t") for line in text.split("\n")]
    # Drop trailing blank lines.
    while len(lines) > 1 and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def compose_commit_message(work_id, title=None, body=None):
    """Return (subject, body) for the closure commit.

    The subject always contains the work_id: when the supplied title does not
    include it, it is appended as ' [work_id]'. An empty or whitespace-only
    title is treated as absent and replaced by the neutral fallback subject.
    """
    normalized_title = _normalize_title(title)
    normalized_body = _normalize_body(body)

    if not normalized_title:
        subject = GENERIC_SUBJECT.format(work_id=work_id)
        # No title means no delivery description: use the neutral body.
        final_body = GENERIC_BODY
    elif work_id in normalized_title:
        subject = normalized_title
        final_body = normalized_body
    else:
        subject = f"{normalized_title} [{work_id}]"
        final_body = normalized_body

    return subject, final_body
