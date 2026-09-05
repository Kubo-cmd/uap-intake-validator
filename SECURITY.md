# Security policy

## Supported version

Security fixes target the current `main` branch. Historical release artifacts and frozen evidence remain immutable; a correction must be applied in current code with explicit provenance rather than rewriting those artifacts.

## Reporting a vulnerability

Use the repository's private vulnerability-reporting channel when it is available. If it is unavailable, contact the repository owner privately through the account contact method. Do not publish witness records, location histories, credentials, or exploit details in an issue.

Include:

- the affected file and revision;
- a minimal reproduction using synthetic data;
- the expected fail-closed behavior;
- the observed impact;
- a proposed mitigation, if known.

## Scope

High-priority reports include malformed-input crashes, confidence-gate bypasses, non-finite-number handling errors, resource-exhaustion paths, artifact-integrity failures, and workflows that execute untrusted code with excess permissions.

This software is experimental and simulation-evaluated. A validator result must not be treated as proof of a sighting, object identity, event explanation, field accuracy, or safety-critical suitability.
