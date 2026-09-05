#!/usr/bin/env python3
"""Offline, non-executing verifier for the immutable v0.1.0 holdout bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

TRUSTED_MANIFEST_SHA256 = "745a2f2efefd58e28eaf87803d110c5b27142d3b2ccef36f94477c149a46b3e8"
MANIFEST_PATH = "evidence/results/holdout-2026080502.manifest.json"
EXPECTED_ARTIFACTS = frozenset({
    "evidence/preregistration.json",
    "evidence/results/holdout-2026080502.json",
    "evidence/results/holdout-2026080502.rows.csv",
    "evidence/results/holdout-2026080502.rows.json",
})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(root: Path) -> list[str]:
    errors: list[str] = []
    try:
        root = root.resolve(strict=True)
        manifest_candidate = root / MANIFEST_PATH
        if manifest_candidate.is_symlink():
            return ["manifest must not be a symbolic link"]
        manifest = manifest_candidate.resolve(strict=True)
    except OSError as exc:
        return [f"manifest is missing or unreadable: {exc}"]
    if root not in manifest.parents or not manifest.is_file():
        return ["manifest is not a contained regular file"]
    if _sha256(manifest) != TRUSTED_MANIFEST_SHA256:
        return ["trusted manifest digest mismatch"]
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"manifest cannot be parsed: {exc}"]
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != EXPECTED_ARTIFACTS:
        return ["manifest artifact names do not exactly match the trusted set"]
    for relative in sorted(EXPECTED_ARTIFACTS):
        candidate = root / relative
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            errors.append(f"{relative}: missing or unreadable: {exc}")
            continue
        if root not in resolved.parents or candidate.is_symlink() or not resolved.is_file():
            errors.append(f"{relative}: not a contained regular file")
            continue
        expected = artifacts[relative]
        if not isinstance(expected, str) or len(expected) != 64:
            errors.append(f"{relative}: malformed expected SHA-256")
        elif _sha256(resolved) != expected:
            errors.append(f"{relative}: SHA-256 mismatch")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    try:
        errors = verify(args.root)
    except (OSError, ValueError) as exc:
        errors = [str(exc)]
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: immutable holdout bundle matches the source-pinned manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
