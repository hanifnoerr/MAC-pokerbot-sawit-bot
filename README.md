# MAC Pokerbot: sawit-bot

Our team's submission to the Monash Association of Coding poker bot competition, together with our local tournament dashboard, match history, and agent experiments.

**Official leaderboard name:** `sawit-bot`

**Local agent name:** `Belief payoff fixed v2 - all opponents`

**Submitted agent:** [belief-payoff-fixed-v2.zip](dist/belief-payoff-fixed-v2.zip) · [source code](agents/belief-payoff-fixed-v2-all-opponents/)

## Competition information

The [MAC Poker Bot competition](https://poker.monashcoding.com/) used no-limit Texas hold'em.

| Setting | Official format |
| --- | --- |
| Tournament tables | 4–6 bots, depending on turnout; the engine supports up to 9 |
| Blinds | 1 / 2, no antes |
| Starting stack | 200 chips, reset at the start of every hand |
| Game length | 100 hands |
| Duplicate deals | One game per seat, using the same decks with rotated seats |
| Rounds | Four; regrouping follows cumulative placement points |
| Clock | 30-second bank per game, plus 0.1 seconds per hand |

I've saved the [competition rules, scoring, and runtime details](docs/competition.md) here in case the official website goes offline.

## How I developed my agent

My approach started with behavioural cloning, using example decisions that included public [Pluribus hand histories](https://github.com/uoftcprg/phh-dataset). Then I used reinforcement learning with [Proximal Policy Optimisation, or PPO](https://arxiv.org/abs/1707.06347), starting with 300,000 hands and continuing to 600,000.

I used two laptops while developing the bot, so I could keep training on one while running local matches and testing different agent variants on the other. I had made 69 variants by that point. I tried different tweaks and compared them with another training branch that I continued on the other laptop, reaching around 995,000 hands.

I trained the model at tables of two to six players, just in case, so I felt confident it could handle different table sizes.

I tested my bot on the MAC pokerbot leaderboard, and that was when I realised it got confused against a trolling opponent, like one who always bluffed or made irrational decisions. So I thought my agent should have some “faith” of its own. I came across a paper on [Learned Belief Search](https://arxiv.org/abs/2106.09086) and asked Claude to implement it, of course with the magic prompt, “make no mistakes!”

That gave me a separate belief-search candidate. Although I spent a lot of time training RL agents, the final submission didn't use my PPO-trained policy. It combined belief search with learned opponent models and preflop charts. It estimated what other players might hold and updated those beliefs as they checked, called, bet, or raised.

After the flop, the bot considered opponents' possible hands, how they might respond, and the expected payoff of each action. We also fixed how it calculated payouts when several players stayed in the hand or shared the pot.

Then I tested it against my teammates' bots. There were three of us, and yes, we created our own tournament simulator to figure out which bot to submit. Each person proposed three agents, and this agent could hold its own against the other eight. We chose **Belief payoff fixed v2 – all opponents**, and it won first place!

Then we actually got a tie in the final, and our agent won the 1v1 tiebreaker! So the extra preparation paid off!

Actually, I also created a [v3](agents/belief-payoff-fixed-v3-response-repair/) that fixed some bad behaviour, but we agreed to submit v2. You'll find v3 in my repo too, although whether it performs better depends on the opponents and tournament setup.

After all the training, debugging, and testing, I still only know how to code and make an agent. I don't understand poker at all, lol.

## What's included

- **58 agents**, with source, weights, and [ZIP downloads](dist/). See the [agent catalogue](AGENTS.md).
- **104 runs and 6,764 game histories**.
- The dashboard, parallel game runner, scoring code, and tests.
- The submitted `sawit-bot` ZIP and v3 for comparison.

These are my teammates' bots: `agi-m1-outcome-v1`, `agi-s2-river-v1`, `agi-f4-range-strong-v1`, `PPO_5p_600_000_v3`, `PPO_Lookup`, and `PPO_456p_600_000_v3`. I haven't asked for their consent to share their code here yet, so I've removed their agent files. Their names and results remain in the match history.

## How to install and run the dashboard

Use **Python 3.12**.

The official SDK is saved in [vendor/](vendor/) in case the competition website closes.

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

Install dependencies, load the saved history, and start the dashboard:

```sh
python -m pip install -r requirements.txt
python restore_snapshot.py
python -m arena.server
```

### Benchmark versus tournament

**Benchmark** tests each agent against four house bots: always call, check/fold, all-in, and random. Each agent plays from every seat for each seed.

**Tournament** runs the selected agents against each other over four rounds, using duplicate deals, rotating seats, and placement points. Select 4–6 agents for a table matching the competition format.

**Placement score** averages each game's placement points divided by table size, excluding playoffs. **mbb/hand** measures profit in thousandths of a big blind per hand.

Use 100 hands per game. **Parallel games** controls how many games run at once; use one for isolated clock checks.

### Tests

```sh
python -m unittest discover -s arena/tests -v
python -m unittest discover -s tests -v
```

## References and credits

- [Official MAC Poker Bot documentation](https://docs.poker.monashcoding.com/).
- Hu et al., [Learned Belief Search: Efficiently Improving Policies in Partially Observable Settings](https://arxiv.org/abs/2106.09086), 2021.
- Schulman et al., [Proximal Policy Optimization Algorithms](https://arxiv.org/abs/1707.06347), 2017.
- [PHH dataset](https://github.com/uoftcprg/phh-dataset/tree/e47fbd5816372360bade4de5d712346fe1bb70f6) (public Pluribus hand histories).
- [poker-practice](https://github.com/jensbaagaard/poker-practice/tree/449993f78d995c77b72d0bcac418a8507dd6f783/data/openSourcePokerData) (preflop charts).
- [Third-party sources and licences](THIRD_PARTY.md).

P.S. My bot’s name, **Sawit**, comes from the Indonesian and Malay word for oil palm (*Elaeis guineensis*). I chose it with the forest burning associated with oil palm plantations in mind. The fires were still happening at the time, and the haze was affecting three neighbouring countries. No forests were burned in the making of this bot. Just two laptops working overtime, lol.
