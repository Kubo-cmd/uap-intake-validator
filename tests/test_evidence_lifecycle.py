#!/usr/bin/env python3
"""Lifecycle checks for immutable evidence and active-runtime separation."""
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_frozen_verifier_accepts_bound_bundle():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "verify_frozen_bundle.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS:" in proc.stdout


def test_manifest_identity_is_bound_in_verifier_source():
    spec = importlib.util.spec_from_file_location("frozen_verifier", ROOT / "verify_frozen_bundle.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert sha256(ROOT / module.MANIFEST_PATH) == module.TRUSTED_MANIFEST_SHA256


def test_active_manifest_cannot_claim_historical_release():
    manifest = json.loads((ROOT / "runtime-manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "unreleased-development"
    assert manifest["frozen_release"]["version"] == "0.1.0"
    assert manifest["frozen_release"]["mutable"] is False
    assert manifest["implementation"] != "intake.py"


def test_public_entrypoint_imports_versioned_runtime():
    text = (ROOT / "validator.py").read_text(encoding="utf-8")
    assert "import runtime_v0_2 as _runtime" in text
    assert "from intake import" not in text


def test_frozen_verifier_rejects_missing_root_without_exception():
    spec = importlib.util.spec_from_file_location("frozen_verifier_missing", ROOT / "verify_frozen_bundle.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as folder:
        assert module.verify(Path(folder))


def test_frozen_verifier_rejects_symlinked_manifest():
    spec = importlib.util.spec_from_file_location("frozen_verifier_symlink", ROOT / "verify_frozen_bundle.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as folder:
        fake = Path(folder)
        target = fake / module.MANIFEST_PATH
        target.parent.mkdir(parents=True)
        target.symlink_to(ROOT / module.MANIFEST_PATH)
        errors = module.verify(fake)
        assert errors == ["manifest must not be a symbolic link"]
