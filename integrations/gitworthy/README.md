# GitWorthy advisory bridge alpha

These contracts are output-only advisory evidence. This repository does not
import GitWorthy, read or write its state, compute ACT/VERIFY/SKIP, or change
ranking v1. `EvalOpportunityV1` contains T0 information only.
`EvalEvidenceV1` is a physically separate post-investigation artifact and must
never be accepted as opportunity input.

The schemas carry a required phase discriminator: opportunity records are
strictly `information_phase: T0`; evidence records are strictly
`information_phase: T1`. Their closed object shapes reject fields from the
other phase. The pinned, read-only boundary manifest records the authoritative
GitWorthy SHA, ranking version, frozen verdict vector, and frozen-case checksum.
`python -m unittest tests.test_gitworthy_boundary` recomputes that evidence
from Git objects without checking out or executing GitWorthy.

`recommended_contribution_mode: PASS` is advice about how to contribute; it is
not a GitWorthy `SKIP` verdict and cannot create a hard skip.
