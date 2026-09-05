# Contributing

This repository is an experimental, simulation-evaluated research tool. Changes must preserve its narrow claim boundaries: it does not prove or disprove a sighting, identify an object, explain an event, or establish field accuracy.

## Before opening a change

1. Create a focused branch from `main`.
2. Keep frozen historical evidence and preregistered artifacts byte-identical.
3. Do not weaken fail-closed validation or confidence gates.
4. Avoid new runtime dependencies unless the change cannot be made safely with the Python standard library.
5. Do not include secrets, private data, or real witness records.

## Required checks

Run on Python 3.9 through 3.12 when available:

    PYTHONWARNINGS=error python3 -m compileall -q .
    PYTHONWARNINGS=error python3 tests/run_tests.py
    PYTHONWARNINGS=error python3 tests/test_uap_conditioning.py

Frozen historical evidence has separate requirements and lifecycle rules documented in `REPO_AND_LAUNCH.md`. Do not rerun, replace, reinterpret, or reseal the completed holdout.

## Pull requests

Describe the problem, the bounded change, test evidence, and any remaining limitations. Security-sensitive findings should follow `SECURITY.md` instead of a public issue.
