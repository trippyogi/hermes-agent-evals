# GitWorthy advisory bridge alpha

These contracts are output-only advisory evidence. This repository does not
import GitWorthy, read or write its state, compute ACT/VERIFY/SKIP, or change
ranking v1. `EvalOpportunityV1` contains T0 information only.
`EvalEvidenceV1` is a physically separate post-investigation artifact and must
never be accepted as opportunity input.

`recommended_contribution_mode: PASS` is advice about how to contribute; it is
not a GitWorthy `SKIP` verdict and cannot create a hard skip.
