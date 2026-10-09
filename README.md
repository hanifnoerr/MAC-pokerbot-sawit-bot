# MAC Pokerbot — sawit-bot

My first-place submission to the Monash Association of Coding poker bot competition, together with my local tournament dashboard, saved match history, and agent experiments.

**Official leaderboard name:** `sawit-bot`

**Local agent name:** `Belief payoff fixed v2 - all opponents`

**Submitted candidate:** [belief-payoff-fixed-v2.zip](dist/belief-payoff-fixed-v2.zip) · [source code](agents/belief-payoff-fixed-v2-all-opponents/)

The preserved submission ZIP has SHA-256 `ab972e2a31ae1f740fa5dcf12fc23ba9d30a21e183ec5a8d0b8f2f70008564b0`. A previously downloaded ZIP had different archive packaging; this is the preserved local package of the winning agent's code and weights.

## Competition information

The [MAC Poker Bot competition](https://poker.monashcoding.com/) used no-limit Texas hold'em. The following format is from the organiser's documentation, checked on 9 October 2026.

| Setting | Official format |
| --- | --- |
| Tournament tables | 4–6 bots, depending on turnout; the engine supports up to 9 |
| Blinds | 1 / 2, no antes |
| Starting stack | 200 chips, reset at the start of every hand |
| Game length | 100 hands |
| Duplicate deals | One game per seat, using the same decks with rotated seats |
| Rounds | Four; regrouping follows cumulative placement points |
| Clock | 30-second bank per game, plus 0.1 seconds per hand |

Chips determine each game's ranking. Game rankings become points, then the table's total game points become round placement points. Tied positions share their points. Final standings use cumulative placement points, with head-to-head sets for prize ties. See the official [game format](https://docs.poker.monashcoding.com/game-format/), [duplicate deals](https://docs.poker.monashcoding.com/game-format/duplicate-deals/), [scoring](https://docs.poker.monashcoding.com/game-format/scoring/), and [clocks and verdicts](https://docs.poker.monashcoding.com/game-format/clocks/).

The competition runtime provided Python 3.12, NumPy, the SDK, one CPU core, and 512 MB of memory, with no network or GPU. The ZIP limit was 20 MB unpacked and 300 files. See [installation and runtime limits](https://docs.poker.monashcoding.com/installation/) and [competition rules](https://docs.poker.monashcoding.com/rules/).

## How I developed my agent

My approach started with behavioural cloning, using example decisions that included public [Pluribus hand histories](https://github.com/uoftcprg/phh-dataset). Then I used reinforcement learning with [Proximal Policy Optimisation, or PPO](https://arxiv.org/abs/1707.06347), starting with 300,000 hands and continuing to 600,000.

Yes, I trained on two laptops! While training continued, I also ran local matches and created agent variants (I had made 69 by that point). I tried different tweaks and compared them with another training branch that I continued on the other laptop, reaching around 995,000 hands.

I tested my bot on the MAC pokerbot leaderboard, and that was when I realised it got confused against a trolling opponent, like one who always bluffed or made irrational decisions. So I thought my agent should have some “faith” of its own. I came across a paper on [Learned Belief Search](https://arxiv.org/abs/2106.09086) and asked Claude to implement it, of course with the magic prompt, “make no mistakes!”

That gave me a separate belief-search candidate. Although I spent a lot of time training RL agents, the final submission didn't use my PPO-trained policy. It combined belief search with learned opponent models and preflop charts. It estimated what other players might hold and updated those beliefs as they checked, called, bet, or raised.

After the flop, the bot considered opponents' possible hands, how they might respond, and the expected payoff of each action. We also fixed how it calculated payouts when several players stayed in the hand or shared the pot.

Then I tested it against my teammates' bots. There were three of us, and yes, we created our own tournament simulator to figure out which bot to submit. Each person proposed three agents, and this agent could hold its own against the other eight. We chose **Belief payoff fixed v2 – all opponents**, and it won first place!

Actually, I also created a [v3](agents/belief-payoff-fixed-v3-response-repair/) that fixed some bad behaviour, but we agreed to submit v2. You'll find v3 in my repo too, although whether it performs better depends on the opponents and tournament setup.

After all the training, debugging, and testing, I still only know how to code and make an agent. I don't understand poker at all, lol.

The paper above is *Learned Belief Search: Efficiently Improving Policies in Partially Observable Settings* by Hengyuan Hu, Adam Lerer, Noam Brown, and Jakob Foerster (2021). It studies Hanabi; it inspired this work, but this poker bot is an adaptation, not a reproduction of the paper's algorithm or results. Its opponent models and range-based payoff search are also separate from the PPO actor. The approximately 995k hands on the second laptop are my reported continuation count; that laptop's training logs are not included here.

## What's included

- **58 registered agents**, with source, supporting weights/data, and individually named [ZIP downloads](dist/). The [agent catalogue](AGENTS.md) lists names and hashes.
- **104 saved run records and 6,764 game histories**, including completed, cancelled, and interrupted runs, plus saved stderr logs. Failed or incomplete runs remain labelled as such.
- The dashboard, parallel game runner, scoring code, and tests.
- The exact preserved local ZIP for `sawit-bot` and the v3 candidate for comparison.

The export contains the 64 agents still registered in my dashboard on 9 October 2026, minus six teammates' agents. The 69 variants in my story refer to development history, not the number in this export. The registry also includes adapted public baselines and related checkpoints; these are not 58 independent original strategies. Dashboard evaluation does not train agents or update their weights.

**These are my teammates' bots. I haven't asked for their consent to share their code here yet, so I've removed their agent files from this repository:** `agi-m1-outcome-v1`, `agi-s2-river-v1`, `agi-f4-range-strong-v1`, `PPO_5p_600_000_v3`, `PPO_Lookup`, and `PPO_456p_600_000_v3`. Their names and results remain visible in historical matches, but their code, registry entries, and downloads are excluded. Consequently, those historical line-ups cannot be rerun exactly from this repository alone.

Local machine paths have been redacted. Private working directories, virtual environments, runtime request files, and teammates' code are not included. Scores, card histories, seeds, verdicts, and measured timings are preserved. Historical results were produced on my machines; timing can differ on yours. See [the snapshot manifest](snapshot/manifest.json) for exact counts.

## How to install and run the dashboard

Use **Python 3.12**. No GPU is needed. GitHub hosts the source and archives; run the dashboard locally to browse histories or launch matches.

```sh
git clone https://github.com/hanifnoerr/MAC-pokerbot-sawit-bot.git
cd MAC-pokerbot-sawit-bot
python -m venv .venv
```

Activate the environment in **Windows PowerShell**:

```powershell
.\.venv\Scripts\Activate.ps1
```

Or on **macOS/Linux**:

```sh
source .venv/bin/activate
```

Then install dependencies, restore the public snapshot, and start the dashboard:

```sh
python -m pip install -r requirements.txt
python restore_snapshot.py
python -m arena.server
```

Open **http://127.0.0.1:8765/**. If that port is busy, run `python -m arena.server --port 8766` and open the new port. The server binds to your own computer only.

Restoring creates `arena/data/` from the sanitised snapshot. The history expands to roughly 1 GB, so allow disk space for that plus new matches. Restore refuses to overwrite an existing data directory. Once restored, start the server directly on later visits; your new runs persist locally and are ignored by Git.

### Browsing past results

Open the run history, select a benchmark or tournament, and inspect its standings, individual games, and hand replays. The tournament leaderboard defaults to the latest completed tournament; selecting a different run changes the opponent field and may change the ranking. Historical opponent names can appear even when their source is not published. Download buttons are available only for agents included in this release.

### Benchmark versus tournament

**Benchmark** tests each selected agent separately against four simple house bots: always call, check/fold, all-in, and random. It uses five seats and one seat rotation per agent for each seed. This is useful for quick comparisons and finding crashes or obvious weaknesses. It is not a prediction of the official leaderboard.

**Tournament** pits your selected agents against one another over four rounds. It uses duplicate deals and seat rotations, converts chip rankings into game points and then placement points, and regroups tables between rounds. Prize ties use local head-to-head playoffs. Select 4, 5, or 6 agents for one competition-sized table. Larger fields are partitioned into tables of 4–6 wherever possible; seven entrants use a seven-player local table, so avoid that size when matching the final format.

The dashboard's **Placement score** is the average game placement points divided by table size, expressed as a percentage, excluding playoffs. It is not a win rate and does not replace tournament placement points. **mbb/hand** means thousandths of a big blind per hand, a chip-profit measure.

Choose agents, set hand count and seeds, and queue the run. Use 100 hands for competition-style games. **Parallel games** runs independent games concurrently; rounds still wait for all their games before regrouping. More workers can reduce elapsed time but also increase CPU contention. Use one worker when checking clock reliability. Run only trusted agent code: this local runner does not reproduce the organiser's container isolation, memory cap, or CPU restrictions.

The dashboard follows the published format, with explicit local choices for table partitioning, fully tied regrouping, and multiway playoffs. It is not the organiser's exact scheduler. Match histories are spectator records with hole cards; the runner does not pass those saved histories to agents as inputs.

### Tests

```sh
python -m unittest discover -s arena/tests -v
python -m unittest discover -s tests -v
```

This repository publishes executable candidates and evaluation history. It does not include the complete training environments or claim to reproduce every training run from scratch.

## References and credits

- [Official MAC Poker Bot documentation](https://docs.poker.monashcoding.com/).
- Hu et al., [Learned Belief Search: Efficiently Improving Policies in Partially Observable Settings](https://arxiv.org/abs/2106.09086), 2021. Inspiration for exploring belief-based search.
- Schulman et al., [Proximal Policy Optimization Algorithms](https://arxiv.org/abs/1707.06347), 2017. The RL algorithm used during development.
- [PHH dataset](https://github.com/uoftcprg/phh-dataset/tree/e47fbd5816372360bade4de5d712346fe1bb70f6). Public hand histories used in behavioural-cloning experiments; no original Pluribus model weights are included.
- [poker-practice preflop data](https://github.com/jensbaagaard/poker-practice/tree/449993f78d995c77b72d0bcac418a8507dd6f783/data/openSourcePokerData). Source-labelled solver charts used for supported preflop situations; the bot is not a complete GTO solver.
- Claude and Codex assisted with implementation, debugging, and evaluation. The final bot makes decisions locally without calling either service.
- Adapted public baselines retain their upstream notices. See [THIRD_PARTY.md](THIRD_PARTY.md) for sources and licensing scope.

P.S. My bot’s name, **Sawit**, comes from the Indonesian and Malay word for oil palm (*Elaeis guineensis*). I chose it with the forest burning associated with oil palm plantations in mind. No forests were burned in the making of this bot. Just two laptops working overtime, lol.
