# MAC Poker Bot competition

This is a summary of the organiser's documentation, checked against the live website on **9 October 2026**. It keeps the format and rules available if the website closes. The original sources are linked below; this is not an organiser-issued rulebook.

## Game format

The event used no-limit Texas hold'em. Tournament tables had four to six bots, depending on turnout, although the engine supported up to nine. The blinds stayed at 1 and 2, with no antes.

Each game lasted 100 hands. Every hand started with fresh 200-chip stacks, equivalent to 100 big blinds, and a newly shuffled deck. The button moved one seat each hand. Players were not eliminated by losing their stack; the next hand reset it. A game's chip score was the sum of each bot's gains and losses across its hands.

Source: [Game format](https://docs.poker.monashcoding.com/game-format/).

## Duplicate deals

A table played as many games per round as it had seats: four games for four bots, five for five, or six for six. The corresponding hand in each game used the same deck. Each game shifted the bots one seat, giving every bot each set of cards from each position over the round.

Every game launched a fresh bot process. Information learned during one game did not carry into the next. Duplicate deals reduced differences in card allocation between bots; they did not guarantee a particular agent would win every set.

Source: [Duplicate deals](https://docs.poker.monashcoding.com/game-format/duplicate-deals/).

## Scoring and tiebreakers

1. The first round assigned teams to tables randomly.
2. Within each game, chip totals determined ranks. At a five-player table, the ranks received 5, 4, 3, 2, and 1 game points. The scale followed the table size.
3. Each table then ranked bots by their total game points for the round. Those ranks became round placement points on the same scale.
4. Tied positions shared the average points for the places they occupied. At a five-player table, two bots tied for second each received 3.5 points.
5. Later rounds regrouped teams by accumulated placement points, using accumulated game points to break grouping ties.
6. After four rounds, accumulated placement points determined the standings. The top three received prizes. Prize ties were settled through a head-to-head set, with one game per seat.

The local dashboard implements these stages. Its exact table partitioning, fully tied regrouping, and multiway playoff choices are local implementations because the documentation did not specify every scheduler detail.

Source: [Scoring and rounds](https://docs.poker.monashcoding.com/game-format/scoring/).

## What the bot could observe

Opponents stayed the same within a round but tables could change between rounds. Bots received stable player IDs within a game, rather than opponent names or team identities. Seats changed as the button moved, so per-opponent observations needed to follow player IDs.

Bots could observe public actions and save per-game state through observer hooks. Opponents' hole cards became visible at showdown if those players remained in the hand. A pot won through folds did not reveal the folded cards. A fresh process and read-only filesystem prevented carrying learned state between games.

The dashboard's spectator replays contain more information than a bot received while playing. Saved replay files were not supplied to agents during a match.

Source: [Opponents and information](https://docs.poker.monashcoding.com/game-format/information/).

## Clocks and verdicts

Each bot started a game with 30 seconds of thinking time and received another 0.1 seconds per hand. There was no separate fixed limit for each move. Time spent waiting for the bot's action consumed this bank, and `state.clock_ms` exposed the remaining time.

| Verdict | Meaning |
| --- | --- |
| `OK` | The bot completed the game |
| `TLE` | Its time bank ran out |
| `RTE` | Its process crashed or exited unexpectedly |
| `PV` | It violated the wire protocol |

After a `TLE`, `RTE`, or `PV`, the engine used check/fold actions for that bot for the rest of the game. The game still finished and produced scores.

Source: [Clocks and verdicts](https://docs.poker.monashcoding.com/game-format/clocks/).

## Runtime and submission limits

| Resource | Competition limit |
| --- | --- |
| Python | 3.12 |
| Libraries | Python standard library, NumPy, and the provided macpoker SDK |
| CPU | One core |
| Memory | 512 MB |
| GPU / network | Unavailable |
| Filesystem | Read-only, except a 64 MB temporary directory cleared each game |
| Submission | ZIP containing `main.py` at its root |
| Unpacked size | At most 20 MB |
| File count | At most 300 |

The SDK itself supported Python 3.10 and newer. This repository recommends Python 3.12 to match the competition. Its local runner uses the SDK clock but does not impose the full competition sandbox or resource limits.

The original installation URL was `https://poker.monashcoding.com/dl/macpoker-0.1.0-py3-none-any.whl`. A copy of that wheel is kept in [vendor/](../vendor/), and the repository's requirements install that local copy. See the [dashboard installation instructions](../README.md#how-to-install-and-run-the-dashboard).

Source: [Installation](https://docs.poker.monashcoding.com/installation/).

## Event rules

Teams could have one to four members, each with an event ticket and membership in only one team. The published rules required bot code to be written during the 48-hour hackathon.

AI tools were allowed to help write, debug, and discuss code during development. Runtime decisions had to come from the submitted bot, without calling AI services or other network endpoints.

Computation was restricted to the bot's turn and SDK callbacks. Background threads, extra processes, or work scheduled during opponents' turns were prohibited. Bots had to play independently: no recognising another team to cooperate, signalling, deliberate chip transfers, or agreed collusion. Reading outside the bot's files, exhausting shared resources, and recovering hidden cards or deck order outside normal play were prohibited.

Organisers reviewed final submissions for code quality and rule compliance. They could remove noncompliant submissions and disqualify the team. Their decision was final. These are the published event rules; the public research baselines in this repository are not a blanket eligibility statement for future competitions.

Source: [Rules](https://docs.poker.monashcoding.com/rules/).
