# Repository metadata and launch copy for the UAP Intake Validator
# External repository creation, publication, and social posting remain USER steps.

## Repository

Name: uap-intake-validator

Tagline: Can the declared data support a range claim at all? Experimental, simulation-evaluated validator for completeness, CV-family underdetermination, and conservative two-sensor geometry.

Topics: uap, ufo, data-quality, epistemics, kinematics, open-science, validation

## Short launch copy

Built an experimental, simulation-evaluated, open-source UAP intake validator. It scores data completeness, flags CV-family geometry that cannot support a range claim, and handles two-sensor geometry without turning model assumptions into facts. It does not prove or disprove a sighting, identify an object, or claim field validation. Results are from a fixed synthetic evaluation distribution. Python 3.9+, stdlib runtime, MIT. [link]

## Thread draft

1/ A single camera measuring angles does not usually determine range. Straight-and-level geometry can be rank-deficient, so an optimizer may return a precise-looking number that the data never identified. This experimental, simulation-evaluated validator flags that failure mode first.

2/ Feed it a sighting record and it scores completeness, computes a clean-room CV-family conditioning diagnostic, and separates declared assumptions from measured geometry. A poor result means the geometry cannot support a CV-family range claim. A good result is not proof of a sighting, object identity, or event explanation.

3/ Two synchronized observers can support a geometric solve, but the claim gate is conservative: absent or nonzero synchronization uncertainty stays low-confidence because target motion is not propagated. Performance numbers come from a fixed synthetic evaluation distribution, not field or population validation. Open science, open source, MIT. Repo: [link]

4/ A frozen historical holdout is preserved exactly and remains Council-level UNDETERMINED. It was not rerun or replaced, and it is not production or field validation.

## Mandatory framing

- Every standalone repository description, launch post, thread, or release note must carry the relevant limitations directly; a link to this section is not a substitute.
- Describe it as an experimental, simulation-evaluated research tool.
- Never claim a flag or solve proves or disproves a sighting, identifies an object, or explains an event.
- Never describe the empirical-p95 construction as independently calibrated to 95%.
- Report the deterministic outer audit literally: 180/191 (94.2%) inclusion and 0/191 solvable cases both confidently reported and more than 5% wrong in 3D.
- State that those values come from a fixed synthetic distribution, not field or population validation.
- Credit the upstream methodology project, while making clear that the current conditioning implementation is clean-room and includes no upstream source code.

## Verification copy

Current runtime gate:

    python3 tests/run_tests.py

Frozen historical evidence gates:

    python3 -m pip install -r requirements-evidence.txt
    python3 evidence/test_stronger_evidence.py
    python3 evidence/stronger_evidence.py verify

## Frozen holdout disclosure

Any public mention of the crossing-angle holdout must use this status:

> A one-shot frozen holdout met its own preregistered physical-law criteria but failed its production-selection gate. The result is valid only under that preregistration and is not Council-conformant; it was not rerun or replaced post hoc. Its Council-level inferential status is UNDETERMINED.

Do not call the holdout Council-PASS, Council-FAIL, Council-conformant, or a production-output confirmation. The controlling append-only record is `evidence/results/holdout-2026080502.council-status.json`.

## Publication gate

Before public release, require all of the following:

- clean-room conditioning implementation and tests pass;
- current runtime tests pass with warnings promoted to errors;
- frozen evidence verifier and lifecycle tests pass without writing artifacts;
- the candidate release commit uses a neutral project identity and tracked files contain no personal or machine-path data; immutable published ancestry is documented rather than rewritten;
- exact committed archive passes the same gates after extraction;
- no remote publication, deployment, or social posting is automated.
