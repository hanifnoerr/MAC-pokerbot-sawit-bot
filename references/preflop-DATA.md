# Poker Trainer built-in preflop ranges

(lazy chunks `7698.*.js` and `7155.*.js`). The app ships all built-in ranges inline as
`JSON.parse('...')` blobs; there is no API. Firebase is only used for user-saved ranges.

## Files

| File | App name | Notes |
|---|---|---|
| `Cash_100_PTO.json` | Cash - 100 bb PTO | Recommended default. Pure strategy (0/1 only). |
| `Cash_100_Simple.json` | Cash - 100 bb Simple | Older simplified ranges, pure. |
| `Cash_100_PRO.json` | Cash - 100 bb Pro | Pure plus 50/50 mixes where useful. |
| `Cash_100_GTO.json` | Cash - 100 bb GTO | Full solver output, mixed frequencies. 2.5bb open. |
| `Cash_100_GTO_2bb.json` | Cash - 100 bb GTO 2bb | Solver output, 2bb open (SB 2.5bb). |
| `Cash_100_GTO_3bb.json` | Cash - 100 bb GTO 3bb | Solver output, 3bb open (SB 3.5bb). |
| `MTT_{100,40,20,10,5}_PTO.json` | MTT - N bb PTO | Pure. |
| `MTT_{100,40,20,10,5}_GTO.json` | MTT - N bb GTO | Mixed frequencies. |
| `all.json` | | All of the above keyed by file stem. |

## Schema

```
{ "<scenarioKey>": { "<hand>": <frequency 0..1>, ... 169 hands }, ... 271 keys }
```

Hands use standard notation (`AA`, `AKs`, `AKo`). Frequency is the fraction of the time the
hand takes the action named by the key. PTO/Simple sets only contain 0 and 1.

All sets list all 169 hands per key except `MTT_100_GTO.json`, which is sparse: hands
with frequency 0 are omitted. Treat a missing hand as 0.

## Scenario keys

Positions: `EP1 EP2 EP3 LJ HJ CO BTN SB BB`. 6-max uses `LJ..BB`, 8-max adds `EP2 EP3`,
9-max adds `EP1`. Every set contains all 271 keys; unused positions are all-zero.

| Key pattern | Meaning |
|---|---|
| `Open<pos>` | Raise first in from `pos` |
| `Limp<pos>` | Open-limp from `pos` (used in MTT, e.g. SB at 100bb) |
| `3Bet<hero>vs<villain>` | Hero 3-bets villain's open |
| `Call<hero>vs<villain>` | Hero calls villain's open |
| `4Bet<hero>vs<villain>` | Hero 4-bets villain's 3-bet (hero was the opener) |
| `Call 3Bet<hero>vs<villain>` | Hero calls villain's 3-bet |
| `5Bet<hero>vs<villain>` | Hero 5-bets (all-in) villain's 4-bet |
| `Call 4Bet<hero>vs<villain>` | Hero calls villain's 4-bet |
| `Call 5Bet<hero>vs<villain>` | Hero calls villain's all-in 5-bet |
| `EmptyRange`, `WideRange` | Helpers: all 0 / all 1 |

Fold frequency = 1 - raise - call. The Range Viewer composes a spot like this:

| UI scenario | Raise range | Call range |
|---|---|---|
| Open | `Open<hero>` | `Limp<hero>` |
| vs raise | `3Bet<hero>vs<villain>` | `Call<hero>vs<villain>` |
| vs 3bet | `4Bet<hero>vs<villain>` | `Call 3Bet<hero>vs<villain>` |
| vs 4bet | `5Bet<hero>vs<villain>` | `Call 4Bet<hero>vs<villain>` |
| vs 5bet | (none) | `Call 5Bet<hero>vs<villain>` |

For "vs 3bet" and later, the app scales the grid by the previous node
(`Open<hero>`, then `3Bet<hero>vs<villain>`, then `4Bet<hero>vs<villain>`) so
frequencies are conditional on having reached that node.

Combo weighting for range percentages: pairs 6, suited 4, offsuit 12 (1326 total).

## Bet sizing profiles (from the app's sizing service)

3-bet = multiplier x open size, floored at `threeBetMin`, capped at `threeBet*Max`.
4-bet = round(multiplier x 3-bet). 5-bet = `maxBetSize` (all-in). "IP" = later position.

| Profile | Open IP / SB | 3-bet IP / OOP | 3-bet min / max | 4-bet IP / OOP | Stack | Ante |
|---|---|---|---|---|---|---|
| cash_default | 2.5 / 3 | 3x / 5x | 7 / - | 2x / 2.5x | 100 | 0 |
| cash_2bb | 2 / 2.5 | 3x / 5x | 7 / - | 2x / 2.5x | 100 | 0 |
| cash_3bb | 3 / 3.5 | 3x / 5x | 7 / - | 2x / 2.5x | 100 | 0 |
| mtt_100bb | 2.3 / 4 | 3.5x / 4.5x | - | 2.2x / 2.5x | 100 | 1 |
| mtt_40bb | 2.3 / 3.5 | 3x / 4x | - / 9 IP, 10 OOP | all-in | 40 | 1 |
| mtt_20bb | 2 / 3 | all-in | | all-in | 20 | 1 |
| mtt_10bb | 10 (shove) | all-in | | all-in | 10 | 1 |
| mtt_5bb | 5 (shove) | all-in | | all-in | 5 | 1 |
