# SHA provenance

Machine-readable source of truth: `evals/provenance/manifest.json`.

Moving labels (`origin/main`, branch names, PR numbers) are **not** stored
in result JSON. They may appear in this note as historical context.

## c6a2fb48 vs 465f0d48

Both commits have the same subject:

`fix(delegate): inherit coherent parent runtime after provider fallback`

| SHA | Parent | Role |
|---|---|---|
| `465f0d4872cf616ff0a095b7b48b506fd377876a` | `87e32b6b30f3e5113e26ac7468319d000a3affac` | PR-open SHA for #90209 (gitworthy outcome: opened on main 87e32b6b) |
| `c6a2fb48af74e3c795015aeb6e615733a9b5bac5` | `49cc3708e50d146fbfce90d4e733712f16cbbda0` | Replayed onto later main after CI slice 6/12 (kanban) and 9/12 (MoA). This is the reviewed PR head and the eval `known_good`. |

Product delta between the two SHAs is test-only
(`tests/tools/test_delegate_kanban_isolation.py` +6). The eval pins
`c6a2fb48af` because that is the worktree HEAD used for historical
validation, not because the runtime inherit logic differs.

## 623b932007 vs 3582a128

Both commits have the same subject:

`fix(desktop): keep pin list identity gateway-wide`

| SHA | Parent | Role |
|---|---|---|
| `3582a128c767a206713cdd4ae1cc6b770144539b` | `87e32b6b30f3e5113e26ac7468319d000a3affac` | SHA recorded in `hermes-agent/reports/90021-pin-scope.md` |
| `623b93200779d31d416eb2c5f9116106de6f5adb` | `657550716f370bd5d1e848a57fc24b9c404cf982` | Same fix replayed onto later main. Eval `known_good`. |

`git diff 3582a128 623b932007 -- apps/desktop/src/lib/connection-scoped.ts apps/desktop/src/store/layout.ts` is empty.

## 13ce0c5c is not live origin/main

`13ce0c5c675e843af70d19c9e5144249cd51c8d1` was `origin/main` at capture
time (2026-08-19, subject `fmt(js): npm run fix on merge (#89914)`).
`origin/main` moves. The eval treats this SHA as an immutable known-bad.
