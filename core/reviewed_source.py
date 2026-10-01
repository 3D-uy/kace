"""Match reviewed text without making its authority depend on LF versus CRLF."""
import hashlib


def matches_reviewed_source(raw, expected_sha256):
    # Historical manifests contain both LF and CRLF hashes. Retain those
    # identities for saved checkpoints; normalize only CRLF pairs, not other
    # whitespace, comments, case, trailing lines or source content.
    lf = raw.replace("\r\n", "\n")
    return any(hashlib.sha256(text.encode("utf-8")).hexdigest() == expected_sha256
               for text in (lf, lf.replace("\n", "\r\n")))
