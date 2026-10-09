# Deepbot maniac adaptation

Source: https://github.com/tamlhp/deepbot-poker/tree/515246b5fa259e7455f8169d28f89a208694dc4c

Upstream author credit: cyril (source file headers), tamlhp/deepbot-poker contributors. License: Apache-2.0, included as LICENSE. No NOTICE file exists in the pinned recursive repository tree. Original sources, license, and SHA-256 manifest are archived in public_agents/sources/deepbot.

Modified 2026-10-02: ported PyPokerEngine policy to macpoker Bot.act. main.py defines exactly one Bot subclass. Card encoding changes from suit-first to SDK rank-first. No upstream module is imported or executed, and native/numpy/PyPokerEngine dependencies are removed. No file/network access, argv access, or engine-seed access is used by these adapters.

## Policy and differences

Preserves call-total + pot on unraised streets and call-total + 2*pot after any raise on that street. No card-dependent decisions.

API translation: upstream call amount is a street total; use street_bets[seat] + to_call. Upstream last contribution is represented by street_bets[seat], including blinds, rather than history amounts (macpoker call history contains increments). Upstream raise_in_limits maps to common.legal_raise; unavailable raises become call/check. Short all-in call targets use the SDK's capped to_call, which may differ from upstream's uncapped advertised call target. Fold-in-limits maps to check when to_call is zero. Raises are recognized only on the current street; macpoker history raise amounts are already street totals. All-in players count as active.

No Monte Carlo equity estimator is used by this policy.

Packaging: include main.py, LICENSE, ADAPTATION.md, and the main agent's common.py at ZIP root (Conservative uses only macpoker). No leaderboard registration or match evaluation performed here. Synthetic tests and static compilation are recorded in the source archive's TEST_RESULTS.md.
