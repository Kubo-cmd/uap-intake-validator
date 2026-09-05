## Problem

Describe the bounded problem this change solves.

## Change

Explain the implementation and why it is the smallest safe change.

## Verification

- [ ] `PYTHONWARNINGS=error python3 -m compileall -q .`
- [ ] `PYTHONWARNINGS=error python3 tests/run_tests.py`
- [ ] `PYTHONWARNINGS=error python3 tests/test_uap_conditioning.py`
- [ ] Tested on each supported Python version affected by the change.
- [ ] No frozen historical evidence or preregistered artifact changed.
- [ ] No secrets, private data, or real witness records are included.
- [ ] Claim boundaries remain explicit and unchanged.

## Remaining limitations

List anything this change does not verify or solve.
