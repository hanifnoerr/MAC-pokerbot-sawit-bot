# Deepbot pstrat adaptation

Source: https://github.com/tamlhp/deepbot-poker/tree/515246b5fa259e7455f8169d28f89a208694dc4c

Upstream author credit: cyril (source file headers), tamlhp/deepbot-poker contributors. License: Apache-2.0, included as LICENSE. No NOTICE file exists in the pinned recursive repository tree. Original sources, license, and SHA-256 manifest are archived in public_agents/sources/deepbot.

Modified 2026-10-02: ported PyPokerEngine policy to macpoker Bot.act. main.py defines exactly one Bot subclass. Card encoding changes from suit-first to SDK rank-first. No upstream module is imported or executed, and native/numpy/PyPokerEngine dependencies are removed. No file/network access, argv access, or engine-seed access is used by these adapters.

## Policy and differences

Ports every range, position threshold, remaining-stack BB threshold, raise count, and sizing branch. Position uses macpoker's SB seat (button in heads-up, button+1 otherwise), with the original modulo table-size grouping. Counts calls and checks together because PyPokerEngine uses CALL for a free check. Requires on_match_start for the BB. Uses actual BB, whereas upstream assumes twice the SB. Short-stack strategy still runs on any street, and exactly 5 BB in early/middle position still falls through to fold. Unsuited range tests still include suited hands. The integer-rank-versus-string A/K flush-draw bug is preserved: only two suited hole cards qualify. Ace is excluded from straight draws; no requirement that hole cards contribute is introduced. Sorted integer ranks make neighbor selection explicit rather than depending on set iteration. macpoker category replaces PyPokerEngine HandEvaluator; pair ranks come from card multiplicities and two-pair tests use the highest two pairs. This is a semantic evaluator substitution, not a guarantee of identical behavior for upstream evaluator bugs or bit-packing edge cases. Trips or better still qualify even when entirely on the board. Postflop sizing uses state.pot, an aggregate of all contributions, because the SDK does not expose upstream's main-pot-only amount; side-pot situations can therefore change sizing.

API translation: upstream call amount is a street total; use street_bets[seat] + to_call. Upstream last contribution is represented by street_bets[seat], including blinds, rather than history amounts (macpoker call history contains increments). Upstream raise_in_limits maps to common.legal_raise; unavailable raises become call/check. Short all-in call targets use the SDK's capped to_call, which may differ from upstream's uncapped advertised call target. Fold-in-limits maps to check when to_call is zero. Raises are recognized only on the current street; macpoker history raise amounts are already street totals. All-in players count as active.

No Monte Carlo equity estimator is used by this policy.

Packaging: include main.py, LICENSE, ADAPTATION.md, and the main agent's common.py at ZIP root (Conservative uses only macpoker). No leaderboard registration or match evaluation performed here. Synthetic tests and static compilation are recorded in the source archive's TEST_RESULTS.md.
