# Ten public poker baselines for local research

These are adaptations of ten distinct public decision policies, not ten pretrained neural networks or ten original competition entries. Imported code is for the local research leaderboard. Check organiser permission before using inherited code in an event that requires all bot code to be written during the hackathon.

## Sources and adaptations

| Local agent | Pinned source | Policy and adaptation |
|---|---|---|
| Fullhouse Aggressor | [Fullhouse](https://github.com/mbatv/fullhouse-engine/tree/a80b26957db5f5515d9273a15d1b73aadf8985db/bots/aggressor) | Unchanged upstream decision function: raises 70% of the time at 2–4 times minimum. MAC state adapter and legal-action clamping. |
| Fullhouse Mathematician | [Fullhouse](https://github.com/mbatv/fullhouse-engine/tree/a80b26957db5f5515d9273a15d1b73aadf8985db/bots/mathematician) | Unchanged pot-odds caller: requires pot/call >= 3. The duplicate ref_bot_2 policy is deliberately excluded. |
| Fullhouse Shark | [Fullhouse](https://github.com/mbatv/fullhouse-engine/tree/a80b26957db5f5515d9273a15d1b73aadf8985db/bots/shark) | Unchanged preflop/position strategy, including the upstream lexicographic rank sorting and absolute-seat heuristic. No silent strategy repairs. |
| PyPokerEngine Honest | [PyPokerEngine](https://github.com/ishikota/PyPokerEngine/blob/a52a048a15da276005eca4acae96fb6eeb4dc034/examples/players/honest_player.py) | Call when estimated win probability >= 1/table size, otherwise fold. Keeps table-size opponent count and counts ties as wins like the original. Its 1,000 simulations are capped at 128 for clock feasibility. |
| RLCard Rule V1 | [RLCard](https://github.com/datamllab/rlcard/blob/d7d0a957baf4cc7225a50522adb0164bf130a9d0/rlcard/models/limitholdem_rule_models.py) | Original rule class retained unchanged. Suit/rank strings and legal actions translated. Fixed-limit raise becomes minimum legal no-limit raise. This is a cross-variant experiment, not the original limit game's performance. |
| DeepBot Conservative | [DeepBot Poker](https://github.com/tamlhp/deepbot-poker/tree/515246b5fa259e7455f8169d28f89a208694dc4c/code/bots) | See the agent's ADAPTATION.md for exact source conditions and MAC translation. |
| DeepBot Maniac | Same pinned DeepBot repository | See ADAPTATION.md. |
| DeepBot Equity | Same pinned DeepBot repository | See ADAPTATION.md. |
| DeepBot Candid | Same pinned DeepBot repository | See ADAPTATION.md. |
| DeepBot PStrat | Same pinned DeepBot repository | See ADAPTATION.md. |

Fullhouse, PyPokerEngine and RLCard use MIT licences. DeepBot uses Apache-2.0. The published agents retain their upstream licence files and source notices; see the repository THIRD_PARTY.md for pinned sources. Every published baseline package retains its applicable licence. The adapters/common helper were written locally on 2 October 2026. No neural weights, pickle files, external APIs, or training frameworks are loaded.

## Shared equity implementation

`common.py` samples unknown opponent hands and missing community cards using only the agent's observed cards/hand number. The direct 5–7-card evaluator is validated against the supplied SDK evaluator. Samples are capped at 128 per decision to respect the available clock. This changes numerical estimates relative to sources that use many more samples or native evaluators. None of these policies reads process arguments, engine seeds, saved histories, another agent's files, or hidden game state.

The source strategies and their original weaknesses are preserved where possible. This is a comparison of the documented MAC adaptations, not a claim to reproduce each project's original published performance.

## Evaluation protocol

All ten frozen ZIPs are registered through the local arena API. A short shared smoke profile checks runtime compatibility. The comparison profile uses 100 hands per game, five seat rotations, and the same three seeds against call/checkfold/allin/random house opponents (1,500 hands per candidate). The existing starter bot has the same profile when using arena-1, arena-2 and arena-3. An additional one-seed four-round tournament compares the ten adapted policies directly. Benchmark chips and tournament placement points answer different questions.

Do not tune on the comparison results and then describe them as held-out validation. Three seeds give a useful local estimate, not a reliable proof that one policy is strongest against all opponents.

The current published agent catalogue and ZIPs are linked from the repository README. This archived note describes the original ten-policy experiment; the public export contains only agents still registered at publication time.
