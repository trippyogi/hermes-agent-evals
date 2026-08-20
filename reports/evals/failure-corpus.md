# Failure corpus

Seeded from prior Hermes investigations, not from a new issue hunt.

Classifications: `production_replay`, `fault_injected_invariant`,
`state_transition`, `agent_behavior`, `instrumentation`.

None of the v0.1 historical fixtures is a `production_replay`.

| Fixture | Classification | Type | Known bad | Known good | Success metric | Secondary metrics |
|---|---|---|---|---|---|---|
| `zero-toolset` | `agent_behavior` | Tier 2 fake-model | `13ce0c5c675e843af70d19c9e5144249cd51c8d1` | `ed5b9152ce975ada68f0b53a21c4806f29ed0852` | Control: `proof.txt` via exposed `write_file`. Fault: 0 schemas + 0 executions **and** named diagnostic | schema count, text-as-tool, warning_emitted |
| `zero-toolset-live` | `agent_behavior` | Tier 2 live model | same pair | same pair | rates over reps; BLOCKED without `HERMES_EVAL_*` | tokens, cache_read, duration |
| `delegate-fallback-runtime` | `fault_injected_invariant` | Tier 1 | `13ce0c5c675e843af70d19c9e5144249cd51c8d1` | `c6a2fb48af74e3c795015aeb6e615733a9b5bac5` | Child identity matches fallback F after **injected** split-brain | runtime_coherent, auth_failures, credential_class |
| `stale-pin-rescope` | `state_transition` | Tier 1 | `13ce0c5c675e843af70d19c9e5144249cd51c8d1` | `623b93200779d31d416eb2c5f9116106de6f5adb` | S stays unpinned after A→B→A **and** unsolicited PATCH=0 | storage keys, backend pinned, state_writes |
| wasted-turn scan | `instrumentation` | parser | n/a | n/a | candidates for human labels | W1–W6 counts |
| compression-prefix-probe | `instrumentation` | wrap | n/a | n/a | hashes on outgoing request path | prefix churn, compress events |

## Honesty notes

**zero-toolset.** Historical gate is fake-model. It distinguishes
Hermes-exposed-zero-tools (control schemas > 0) from silence vs loud
failure. It is not a production transcript replay.

**delegate-fallback-runtime.** The #90009 split-brain state is
**fault-injected**. A clean `_try_activate_fallback` on
`13ce0c5c675e843af70d19c9e5144249cd51c8d1` already rewrites parent
surface attrs atomically, so that path does **not** naturally produce
the discriminator. After a real fallback activation the fixture writes
stale Codex `base_url` / `api_key` / `_client_kwargs` while leaving live
`_anthropic_*` stores, then calls `_build_child_agent`.

**stale-pin-rescope.** Store+reconcile FSM parameterized by the SUT pin
atom policy. Not Electron clicks.

SHA provenance for `c6a2fb48` vs `465f0d48` and `623b932007` vs
`3582a128`: `reports/evals/sha-provenance.md`.
