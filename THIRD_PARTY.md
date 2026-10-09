# Sources and reuse

The dashboard and locally developed candidates are published here with their history. This repository does not apply a blanket licence to third-party code, model weights, or poker charts. Existing licence files and attribution remain with each agent. Components without an explicit licence do not gain a new licence merely by being hosted here.

## Public baseline adaptations

| Source | Pinned revision | Upstream licence |
| --- | --- | --- |
| [Fullhouse](https://github.com/mbatv/fullhouse-engine) | `a80b26957db5f5515d9273a15d1b73aadf8985db` | MIT |
| [PyPokerEngine](https://github.com/ishikota/PyPokerEngine) | `a52a048a15da276005eca4acae96fb6eeb4dc034` | MIT |
| [RLCard](https://github.com/datamllab/rlcard) | `d7d0a957baf4cc7225a50522adb0164bf130a9d0` | MIT |
| [DeepBot Poker](https://github.com/tamlhp/deepbot-poker) | `515246b5fa259e7455f8169d28f89a208694dc4c` | Apache-2.0 |

These agents are adaptations to MAC's state and action interface, not original competition submissions from those projects. Their `ADAPTATION.md`, `PUBLIC_BASELINES.md`, source notices, and licence files are included where present in the registered snapshot. The public dashboard's Download ZIP feature preserves these files.

## Data and learned models

- The BC experiments used public Pluribus hand histories from [PHH](https://github.com/uoftcprg/phh-dataset/tree/e47fbd5816372360bade4de5d712346fe1bb70f6). The full training dataset is not redistributed here. Included PPO/BC checkpoints belong to the development experiments.
- Preflop `ranges.json` derives from `Cash_100_GTO.json` in [poker-practice](https://github.com/jensbaagaard/poker-practice/tree/449993f78d995c77b72d0bcac418a8507dd6f783/data/openSourcePokerData). The upstream describes these as solver charts. That description does not establish exact solver settings, convergence, or complete GTO play by this bot. Source data documentation and provenance are in [references](references/).
- The belief-search candidates include the learned opponent-model weights supplied with that branch. Their original training pipeline is not reproduced by this release. They are not the separately trained PPO actor checkpoints and are not Pluribus weights.
- Replay-proxy agents estimate behaviours from observations. They are not the source code of the leaderboard players named in their labels.

## Runtime

The official `macpoker` 0.1.0 SDK is installed from the organiser's public download URL, rather than bundled into this repository. Its package metadata declares MIT. NumPy is installed separately. Consult the corresponding projects for their licence terms.

## Withheld agents

Six teammates' agents are intentionally absent because consent to publish their code has not been requested. Their names and historical results remain, as described in the README. There are no downloads for these agents.
