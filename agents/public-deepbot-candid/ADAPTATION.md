# Deepbot candid adaptation

Source: https://github.com/tamlhp/deepbot-poker/tree/515246b5fa259e7455f8169d28f89a208694dc4c

Upstream author credit: cyril (source file headers), tamlhp/deepbot-poker contributors. License: Apache-2.0, included as LICENSE. No NOTICE file exists in the pinned recursive repository tree. Original sources, license, and SHA-256 manifest are archived in public_agents/sources/deepbot.

Modified 2026-10-02: ported PyPokerEngine policy to macpoker Bot.act. main.py defines exactly one Bot subclass. Card encoding changes from suit-first to SDK rank-first. No upstream module is imported or executed, and native/numpy/PyPokerEngine dependencies are removed. No file/network access, argv access, or engine-seed access is used by these adapters.

## Policy and differences

Preserves equity**7, y = output * initial_stack + current street contribution, default decision_algo branch order, two-raise gate, strict two-thirds-stack shove threshold, and Python round-to-BB sizing. Reads initial stack and actual BB from on_match_start's stack/blinds fields. Requires that normal lifecycle hook before act. No 6max_full variant is used upstream by CandidBot, so none is added.

API translation: upstream call amount is a street total; use street_bets[seat] + to_call. Upstream last contribution is represented by street_bets[seat], including blinds, rather than history amounts (macpoker call history contains increments). Upstream raise_in_limits maps to common.legal_raise; unavailable raises become call/check. Short all-in call targets use the SDK's capped to_call, which may differ from upstream's uncapped advertised call target. Fold-in-limits maps to check when to_call is zero. Raises are recognized only on the current street; macpoker history raise amounts are already street totals. All-in players count as active.

Equity substitution: common.equity(state, simulations=100) replaces u_bot.comp_hand_equity and native libhandequity.so/OMPEval. It samples uniformly random opponent hands and remaining board cards, computes multiway showdown split-pot share, and uses 100 trials rather than OMPEval's stopping criterion. Its deterministic seed is derived only from visible state, not an engine seed. Sampling error and evaluator replacement can change threshold decisions. No tie-as-full-win option is enabled. This is an estimator approximation, not an exact reproduction of native outputs.

Packaging: include main.py, LICENSE, ADAPTATION.md, and the main agent's common.py at ZIP root (Conservative uses only macpoker). No leaderboard registration or match evaluation performed here. Synthetic tests and static compilation are recorded in the source archive's TEST_RESULTS.md.
