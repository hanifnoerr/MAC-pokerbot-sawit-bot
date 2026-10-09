"""Public-information repairs; exported unchanged into candidate archives."""
import numpy as np
from macpoker.cards import parse_cards
from base import Policy, action_table, values

EXTRA_DIM = 101


class RepairPolicy(Policy):
    def __init__(self, weights, seed=881361, *, risk=True, extended=False, temperature=1.):
        super().__init__(weights, seed)
        self.risk = risk
        self.extended = extended
        self.temperature = temperature
        self.last_equity = None
        self.prospective_rng = np.random.default_rng(seed ^ 728091)

    def known_shover(self, s, seat):
        loose, agg, _ = self.tendencies(s.players[seat])
        return self.stats[s.players[seat]][3] >= 8 and loose > .65 and agg > .60

    def continuation(self, s, seat):
        if s.folded[seat]:
            return 0.
        if s.stacks[seat] == 0:
            return 1.
        if s.street != 'preflop':
            return 1.
        maximum = max(s.street_bets)
        if s.street_bets[seat] >= maximum:
            return 1.
        if self.known_shover(s, seat):
            return .98
        if s.street_bets[seat] >= 40:
            return .95
        loose, _, _ = self.tendencies(s.players[seat])
        price = maximum - s.street_bets[seat]
        # Only prospective preflop participation is uncertain. Never remove an all-in.
        return float(np.clip(loose * (1. - .35 * min(1., price / 100)), .05, .90))

    def prospective_equity(self, s, hole, board):
        """Check-down equity with sampled participation, not a resolved poker search."""
        active = [i for i in range(s.num_players) if i != s.seat and not s.folded[i]]
        continuation = [self.continuation(s, i) for i in active]
        deck, combos, feats = self.features(hole, board)
        count = 256 if s.clock_ms > 5000 else 96
        rng = self.prospective_rng
        rows = np.arange(count)
        used = np.zeros((count, 52), bool)
        used[:, hole + board] = True
        chosen, participates = [], []
        for seat, chance in zip(active, continuation):
            p = self.range_weights(s, combos, feats, seat)
            hands = combos[rng.choice(len(combos), count, p=p)]
            for _ in range(32):
                conflict = used[rows, hands[:, 0]] | used[rows, hands[:, 1]]
                if not conflict.any():
                    break
                hands[conflict] = combos[rng.choice(len(combos), conflict.sum(), p=p)]
            for row in np.flatnonzero(used[rows, hands[:, 0]] | used[rows, hands[:, 1]]):
                valid = ~used[row, combos[:, 0]] & ~used[row, combos[:, 1]]
                q = p * valid
                hands[row] = combos[rng.choice(len(combos), p=q/q.sum())]
            used[rows, hands[:, 0]] = True
            used[rows, hands[:, 1]] = True
            chosen.append(hands)
            participates.append(rng.random(count) < chance)
        keys = rng.random((count, 52))
        keys[used] = 2
        future = np.argsort(keys, axis=1)[:, :5-len(board)]
        final = np.column_stack((np.tile(board, (count, 1)), future))
        own = values(np.column_stack((np.tile(hole, (count, 1)), final)))
        win = np.ones(count, bool)
        ties = np.zeros(count, int)
        for hands, present in zip(chosen, participates):
            other = values(np.column_stack((hands, final)))
            win &= ~present | (own >= other)
            ties += present & (own == other)
        return float(np.mean(win / (1 + ties)))

    def encode(self, s):
        x, mask = super().encode(s)
        hole, board = parse_cards(s.hole), parse_cards(s.board)
        active = [i for i in range(s.num_players) if i != s.seat and not s.folded[i]]
        pending = any(self.continuation(s, i) < .999 for i in active)
        raised = any(a[2] == 'raise' for a in s.history)
        # Preserve legacy inputs and their suit/RNG behavior at initialization.
        eq = float(x[105])
        if s.street == 'preflop' and raised and pending and (self.extended or self.risk):
            eq = self.prospective_equity(s, hole, board)
        self.last_equity = eq
        if not self.extended:
            return x, mask
        extra = []
        opponents = sorted((i for i in range(s.num_players) if i != s.seat),
                           key=lambda i: (i-s.button) % s.num_players)
        for j in range(8):
            if j >= len(opponents):
                extra.extend([0.] * 12)
                continue
            i = opponents[j]
            loose, agg, folds = self.tendencies(s.players[i])
            acted = any(a[0] == 'preflop' and a[1] == i for a in s.history)
            extra.extend([1., not s.folded[i], s.stacks[i]/200, s.street_bets[i]/200,
                          loose, agg, folds, min(1., self.stats[s.players[i]][3]/50),
                          (i-s.button) % s.num_players/s.num_players,
                          self.continuation(s, i), acted, s.stacks[i] == 0])
        extra.extend([eq, sum(self.continuation(s, i) for i in active)/8,
                      s.num_players/9, s.players_in_hand/9,
                      sum(self.known_shover(s, i) for i in active)/8])
        assert len(extra) == EXTRA_DIM
        return np.concatenate((x, np.asarray(extra, np.float32))), mask

    def risk_mask(self, s, x, mask):
        if not self.risk:
            return mask
        mask = mask.copy()
        eq = self.last_equity
        active = [i for i in range(s.num_players) if i != s.seat and not s.folded[i]]
        has_price = bool(s.to_call or s.board or any(a[2] == 'raise' for a in s.history))
        # An optimistic uncertainty margin limits intervention to clear estimated losses.
        upper = min(1., eq + .07)
        if s.to_call >= 40 and (s.to_call >= 80 or s.to_call >= .60*s.my_stack):
            odds = min(s.to_call, s.my_stack) / max(1, s.pot + min(s.to_call, s.my_stack))
            # Side-pot-specific pricing needs a separate estimator; leave unequal all-ins alone.
            unequal = any(s.stacks[i] == 0 and s.street_bets[i] < s.street_bets[s.seat]+s.to_call
                          for i in active)
            if not unequal and upper < odds and mask[0]:
                mask[1:] = False
                return mask
        if not has_price:
            # Preflop power is not calibrated equity: never use it to veto an unopened raise.
            return mask
        actions, _ = action_table(s)
        for j in np.flatnonzero(mask & (np.arange(7) >= 2)):
            total = actions[j].amount
            paid = total - s.street_bets[s.seat]
            if paid < 40 or (paid < .5*s.my_stack and paid < .7*s.pot):
                continue
            folds = []
            matching = 0.
            for i in active:
                loose, agg, fold_rate = self.tendencies(s.players[i])
                confidence = min(1., self.stats[s.players[i]][4]/20)
                chance_fold = min(.70, fold_rate*confidence + .20*(1-confidence))
                if self.known_shover(s, i) or s.stacks[i] == 0:
                    chance_fold = 0.
                folds.append(chance_fold)
                matching += (1-chance_fold)*min(s.stacks[i], max(0, total-s.street_bets[i]))
            fold_all = float(np.prod(folds)) if folds else 1.
            optimistic_ev = fold_all*s.pot + (1-fold_all)*(upper*(s.pot+paid+matching)-paid)
            if optimistic_ev < -.03*paid:
                mask[j] = False
        assert mask.any()
        return mask

    def forward(self, x, mask):
        logits, p, value = super().forward(x, mask)
        if self.temperature != 1.:
            scores = np.where(mask, logits/self.temperature, -1e9)
            p = np.exp(scores-scores.max(axis=-1, keepdims=True))
            p /= p.sum(axis=-1, keepdims=True)
        return logits, p, value

    def act(self, s):
        if s.clock_ms < 600:
            return self.emergency(s, parse_cards(s.hole), parse_cards(s.board))
        x, mask = self.encode(s)
        mask = self.risk_mask(s, x, mask)
        _, p, _ = self.forward(x, mask)
        cumulative = np.cumsum(p, dtype=np.float64)
        index = int(np.searchsorted(cumulative, self.action_rng.random()*cumulative[-1], side='right'))
        return action_table(s)[0][index]
