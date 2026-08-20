# Fixture admission gate

Every **permanent** fixture must pass all six questions before the corpus
grows. v0.3 does not add fixtures.

| Gate | Requirement |
|---|---|
| Evidence | Represents a real failure/invariant worth protecting |
| Outcome | Has an independently observable success condition |
| Historical | Separates at least one known-bad from known-good revision |
| Oracle | Evaluator itself has a known-valid path |
| Frame conditions | Checks important state that must not change |
| Noise | Deterministic, or signal is larger than repeated-run variance |

The oracle requirement is borrowed from Terminal-Bench/Harbor: run the
oracle (or known-good SHA) until the *environment* is trustworthy, then
trust agent results.

This protects against: the eval failed because the eval is broken.

The three current core fixtures already satisfy Evidence, Outcome,
Historical, and (for the hermetic arms) Noise. Frame conditions are
explicit on `stale-pin-rescope` and implicit on delegate runtime identity.
Oracle is the known-good SHA path, not a separate agent solution.

Do not promote reconstructed waste episodes until they pass this gate
after real ATOF labeling (v0.6).
