# Changelog

## 0.2.0-dev — unreleased

- Split the active runtime into `runtime_v0_2.py`; immutable v0.1.0 evidence-bound code remains inactive and byte-preserved.
- Added bounded schema, explicit operative coordinate metadata, a 10,000-frame preflight limit, and strict CLI JSON/UTF-8 limits.
- Replaced orientation-dependent bearing perturbation with tangent-plane Gaussian noise mapped through the spherical exponential map.
- Made failed Monte Carlo re-solves unbounded outcomes and exposed solve accounting.
- Added a non-executing verifier pinned to the historical holdout manifest digest.
- Corrected the detection-range derivation and example.

The historical v0.1.0 tag and its artifacts are immutable. This entry describes post-release development and does not move or replace that release identity.
