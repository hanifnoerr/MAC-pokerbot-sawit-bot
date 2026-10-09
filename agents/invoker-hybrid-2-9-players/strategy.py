import os
for _key in ('OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS'):
    os.environ[_key] = '1'
import itertools
from collections import defaultdict
import numpy as np
from macpoker import Bot
from macpoker.cards import parse_cards


def values(cards):
    cards = np.asarray(cards, dtype=np.int16)
    n = len(cards)
    ranks = cards % 13
    suits = cards // 13
    rs = np.arange(13, dtype=np.int16)
    counts = (ranks[:, :, None] == rs).sum(axis=1)
    present = counts > 0
    masks = (present * (1 << rs.astype(np.int32))).sum(axis=1)

    def straight(mask):
        result = np.full(n, -1, dtype=np.int64)
        result[(mask & 4111) == 4111] = 3
        for high in range(4, 13):
            pat = 31 << (high - 4)
            result[(mask & pat) == pat] = high
        return result

    def pack(cat, *digits):
        result = np.full(n, cat, dtype=np.int64)
        for i in range(5):
            result = result * 15 + (digits[i] + 1 if i < len(digits) else 0)
        return result

    def top(mask, k):
        return np.sort(np.where(mask, rs, -1), axis=1)[:, -k:][:, ::-1].T

    high = top(present, 5)
    result = pack(0, *high)
    pair = top(counts >= 2, 2)
    trip = top(counts >= 3, 1)[0]
    quad = top(counts >= 4, 1)[0]
    kick = top(present & (rs != pair[0, :, None]), 3)
    result = np.where(pair[0] >= 0, pack(1, pair[0], *kick), result)
    kick = top(present & (rs != pair[0, :, None]) & (rs != pair[1, :, None]), 1)[0]
    result = np.where(pair[1] >= 0, pack(2, pair[0], pair[1], kick), result)
    kick = top(present & (rs != trip[:, None]), 2)
    result = np.where(trip >= 0, pack(3, trip, *kick), result)
    st = straight(masks)
    result = np.where(st >= 0, pack(4, st), result)
    sf = np.full(n, -1, dtype=np.int64)
    for suit in range(4):
        fc = ((suits == suit)[:, :, None] & (ranks[:, :, None] == rs)).any(axis=1)
        flush = fc.sum(axis=1) >= 5
        result = np.where(flush, np.maximum(result, pack(5, *top(fc, 5))), result)
        mask = (fc * (1 << rs.astype(np.int32))).sum(axis=1)
        sf = np.maximum(sf, straight(mask))
    other_pair = top((counts >= 2) & (rs != trip[:, None]), 1)[0]
    result = np.where((trip >= 0) & (other_pair >= 0), pack(6, trip, other_pair), result)
    kick = top(present & (rs != quad[:, None]), 1)[0]
    result = np.where(quad >= 0, pack(7, quad, kick), result)
    return np.where(sf >= 0, pack(8, sf), result)


def preflop(cards):
    cards = np.asarray(cards)
    a, b = cards[:, 0] % 13, cards[:, 1] % 13
    hi, lo = np.maximum(a, b), np.minimum(a, b)
    suited = cards[:, 0] // 13 == cards[:, 1] // 13
    return np.where(hi == lo, .50 + .035 * hi,
                    .24 + .024 * hi + .014 * lo + .04 * suited
                    + .025 * (hi - lo == 1) - .01 * np.maximum(0, hi - lo - 2) + .04 * (hi == 12))


class InvokerStrategy(Bot):
    name = 'Invoker strategy candidate'

    def __init__(self, seed=902173, caution=1.):
        self.rng = np.random.default_rng(seed)
        self.caution = caution
        self.stats = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
        self.cache = {}
        self.seen = set()
        self.voluntary = set()
        self.start = None

    def on_hand_start(self, info):
        self.cache.clear()
        self.seen.clear()
        self.voluntary.clear()
        self.start = info.get('stacks')

    def on_action(self, event):
        seat, players = event.get('seat', -1), event.get('players', [])
        if not 0 <= seat < len(players):
            return
        who, kind = players[seat], event['action']
        st = self.stats[who]
        if event['street'] == 'preflop':
            if who not in self.seen:
                st[0] += 1
                self.seen.add(who)
            if kind in ('call', 'raise') and who not in self.voluntary:
                st[1] += 1
                self.voluntary.add(who)
            st[2] += kind == 'raise'
        else:
            st[3] += kind in ('call', 'raise')
            st[4] += kind == 'raise'
            st[5] += kind == 'fold'

    def tendencies(self, s, seat):
        hands, vp, raises, post, aggression, folds = self.stats[s.players[seat]]
        return ((vp + 5) / (hands + 16), (raises + 2) / (hands + 14),
                (aggression + 2) / (post + 8), (folds + 3) / (post + folds + 10))

    @staticmethod
    def late(s):
        order = lambda seat: (seat - s.button - 1) % s.num_players
        return all(order(i) < order(s.seat) for i in range(s.num_players)
                   if i != s.seat and not s.folded[i] and s.stacks[i] > 0)

    @staticmethod
    def raise_by(s, extra):
        if not s.can_raise:
            return s.call() if s.to_call else s.check()
        total = s.street_bets[s.seat] + s.to_call + int(extra)
        return s.raise_to(int(max(s.min_raise_to, min(s.max_raise_to, total))))

    def open_cutoff(self, s):
        if s.num_players == 2:
            return .40
        remaining = sum(not s.folded[i] and i != s.seat for i in range(s.num_players))
        if s.seat == s.button:
            return .49 if remaining <= 3 else .55
        if s.seat == (s.button + 1) % s.num_players:
            return .46 if remaining == 1 else .59
        distance = (s.button - s.seat) % s.num_players
        return .55 if distance == 1 else .60 if distance == 2 else .64

    @staticmethod
    def draws(hands, board):
        cards = np.column_stack((hands, np.tile(board, (len(hands), 1))))
        flush = np.zeros(len(hands), bool)
        for suit in range(4):
            flush |= ((cards // 13 == suit).sum(axis=1) == 4) & (hands // 13 == suit).any(axis=1)
        ranks = cards % 13
        straight = np.zeros(len(hands), bool)
        for low in range(-1, 9):
            window = [(low + j) % 13 for j in range(5)]
            hits = sum((ranks == r).any(axis=1) for r in window)
            personal = np.isin(hands % 13, window).any(axis=1)
            straight |= (hits == 4) & personal
        return flush, straight

    def features(self, hole, board):
        key = tuple(hole + board)
        if key in self.cache:
            return self.cache[key]
        deck = [c for c in range(52) if c not in hole + board]
        combos = np.array(list(itertools.combinations(deck, 2)), dtype=np.int16)
        feats = {'preflop': preflop(combos)}
        for street, size in (('flop', 3), ('turn', 4), ('river', 5)):
            if len(board) < size:
                continue
            prefix = board[:size]
            v = values(np.column_stack((combos, np.tile(prefix, (len(combos), 1)))))
            ordered = np.sort(v)
            strength = (np.searchsorted(ordered, v, 'left') + np.searchsorted(ordered, v, 'right')) / (2 * len(v))
            if size < 5:
                flush, straight = self.draws(combos, prefix)
                # A floor applies only to a real draw; air keeps its actual rank.
                strength = np.maximum(strength, np.where(flush, .66, np.where(straight, .52, 0.)))
            feats[street] = strength
        self.cache[key] = combos, feats
        return combos, feats

    def ranges(self, s, combos, feats, seat):
        loose, pfr, aggression, _ = self.tendencies(s, seat)
        hands = self.stats[s.players[seat]][0]
        maniac = hands >= 8 and loose > .65 and pfr > .50
        w = np.ones(len(combos))
        bets = [0] * s.num_players
        bets[s.button if s.num_players == 2 else (s.button + 1) % s.num_players] = 1
        bets[(s.button + (1 if s.num_players == 2 else 2)) % s.num_players] = 2
        pot, street, raises = 3, 'preflop', 0
        own_raise = defaultdict(int)
        for st, who, kind, amount in s.history:
            if st != street:
                street, bets, raises = st, [0] * s.num_players, 0
            call = max(bets) - bets[who]
            ratio = max(0, amount - max(bets)) / max(1, pot + call) if kind == 'raise' else amount / max(1, pot + amount)
            if kind == 'raise':
                raises += 1
            if who == seat and not maniac:
                val = feats[st]
                if kind == 'raise':
                    own_raise[st] += 1
                    if st == 'preflop':
                        cutoff = .60 + .085 * min(2, raises - 1) + .035 * (amount >= 40)
                        cutoff -= .20 * max(0., loose - .32) + .25 * max(0., pfr - .15)
                        slope, floor = 24., .025
                    else:
                        cutoff = .69 + .08 * min(2., ratio) + .065 * (own_raise[st] - 1)
                        cutoff += .025 * max(0, s.players_in_hand - 2)
                        cutoff -= .30 * max(0., aggression - .30)
                        slope, floor = 22., .025 + .13 * aggression
                    w *= floor + (1 - floor) / (1 + np.exp((cutoff - val) * slope))
                elif kind == 'call':
                    cutoff = (.48 + .045 * min(3, raises) if st == 'preflop' else .32 + .70 * min(.5, ratio))
                    cutoff -= .24 * max(0., loose - .32)
                    w *= .10 + .90 / (1 + np.exp((cutoff - val) * 17))
                elif kind == 'check':
                    w *= np.where(val > .90, .78, 1.)
            if kind == 'raise':
                pot += amount - bets[who]
                bets[who] = amount
            elif kind == 'call':
                pot += amount
                bets[who] += amount
        w = np.maximum(w, 1e-10)
        return w / w.sum()

    def sample(self, s, hole, board):
        combos, feats = self.features(hole, board)
        opponents = [i for i in range(s.num_players) if i != s.seat and not s.folded[i]]
        count = 192 if s.clock_ms > 12000 else 96
        rows = np.arange(count)
        used = np.zeros((count, 52), bool)
        used[:, hole + board] = True
        chosen, strength, participation = {}, {}, {}
        for i in opponents:
            prob = self.ranges(s, combos, feats, i)
            idx = self.rng.choice(len(combos), count, p=prob)
            for _ in range(16):
                hand = combos[idx]
                conflict = used[rows, hand[:, 0]] | used[rows, hand[:, 1]]
                if not conflict.any():
                    break
                idx[conflict] = self.rng.choice(len(combos), int(conflict.sum()), p=prob)
            hand = combos[idx]
            for row in np.flatnonzero(used[rows, hand[:, 0]] | used[rows, hand[:, 1]]):
                q = prob * (~used[row, combos[:, 0]] & ~used[row, combos[:, 1]])
                idx[row] = self.rng.choice(len(combos), p=q/q.sum())
            hand = combos[idx]
            used[rows, hand[:, 0]] = True
            used[rows, hand[:, 1]] = True
            chosen[i] = hand
            strength[i] = feats[s.street][idx]
            probability = np.ones(count)
            # Only uncommitted players yet to answer a preflop raise may drop out.
            # Their continuation is conditional on their sampled hand, not independent of it.
            if not board and s.stacks[i] > 0 and s.street_bets[i] < max(s.street_bets):
                loose, pfr, _, _ = self.tendencies(s, i)
                price = max(s.street_bets) - s.street_bets[i]
                cutoff = .54 + .12 * min(1., price / 100) - .25 * max(0., loose - .32)
                probability = .03 + .94 / (1 + np.exp((cutoff - strength[i]) * 22))
                if s.street_bets[i] >= 40 or (loose > .65 and pfr > .50):
                    probability[:] = .98
            participation[i] = self.rng.random(count) < probability
        keys = self.rng.random((count, 52))
        keys[used] = 2
        future = np.argsort(keys, axis=1)[:, :5-len(board)]
        final = np.column_stack((np.tile(board, (count, 1)), future))
        scores = {s.seat: values(np.column_stack((np.tile(hole, (count, 1)), final)))}
        for i, hand in chosen.items():
            scores[i] = values(np.column_stack((hand, final)))
        return scores, strength, participation

    def commitments(self, s):
        start = self.start if self.start is not None and len(self.start) == s.num_players else [200] * s.num_players
        return np.asarray(start, float) - np.asarray(s.stacks, float)

    def payout(self, s, scores, commitments, present):
        """Hero share of each eligible pot layer; existing chips are sunk costs."""
        count = len(scores[s.seat])
        c = np.asarray(commitments)
        if c.ndim == 1:
            c = np.tile(c[:, None], (1, count))
        result = np.zeros(count)
        levels = np.sort(c, axis=0)
        previous = np.zeros(count)
        own = scores[s.seat]
        for cap in levels:
            amount = np.clip(c - previous, 0, cap - previous).sum(axis=0)
            eligible = c[s.seat] >= cap
            win = eligible.copy()
            ties = np.ones(count)
            for i, other in scores.items():
                if i == s.seat:
                    continue
                active = present[i] & (c[i] >= cap)
                win &= ~active | (own >= other)
                ties += active & (own == other)
            result += amount * win / ties
            previous = cap
        return result

    def fallback(self, s, hole, board):
        if not s.to_call:
            return s.check()
        if not board:
            pair = hole[0] % 13 == hole[1] % 13
            return s.call() if pair and hole[0] % 13 >= 11 else s.fold()
        own = values(np.array([hole + board]))[0]
        # Exact current nuts check remains cheap and preserves shared-board ties.
        deck = [c for c in range(52) if c not in hole + board]
        combos = np.array(list(itertools.combinations(deck, 2)))
        other = values(np.column_stack((combos, np.tile(board, (len(combos), 1)))))
        if own >= other.max():
            return s.call()
        cost = min(s.to_call, s.my_stack)
        share = np.mean((own > other) + .5 * (own == other)) ** max(1, s.players_in_hand - 1)
        return s.call() if share > cost / max(1, s.pot + cost) + .18 and cost <= 10 else s.fold()

    def act(self, s):
        hole, board = parse_cards(s.hole), parse_cards(s.board)
        call = s.call() if s.to_call else s.check()
        fold = s.fold() if s.to_call else s.check()
        if s.clock_ms < 2500:
            return self.fallback(s, hole, board)
        opponents = [i for i in range(s.num_players) if i != s.seat and not s.folded[i]]
        if not opponents:
            return call
        pre_raises = [a for a in s.history if a[0] == 'preflop' and a[2] == 'raise']
        power = float(preflop(np.array([hole]))[0])
        hi, lo = sorted([c % 13 for c in hole], reverse=True)
        pair, suited = hi == lo, hole[0] // 13 == hole[1] // 13
        late = self.late(s)
        if not board and not pre_raises:
            limpers = sum(a[0] == 'preflop' and a[2] == 'call' for a in s.history)
            cutoff = self.open_cutoff(s) + .02 * min(2, limpers) + .015 * (self.caution - 1)
            if power >= cutoff:
                return self.raise_by(s, 3 + 2 * limpers)
            if limpers and s.to_call <= 2 and ((pair or suited) and power >= cutoff - .10):
                return call
            return fold
        if not board:
            # Cheap rejection avoids spending the clock on clearly dominated large defenses.
            if power < .43 and s.to_call > 8:
                return fold
            if pair and hi == 12 and s.can_raise:
                return self.raise_by(s, max(6, s.pot + s.to_call))
        scores, strength, present = self.sample(s, hole, board)
        count = len(scores[s.seat])
        committed = self.commitments(s)
        cost = min(s.to_call, s.my_stack)
        after_call = committed.copy()
        after_call[s.seat] += cost
        # Include prospective matching chips only for players who actually continue.
        call_c = np.tile(after_call[:, None], (1, count))
        if not board:
            target = s.street_bets[s.seat] + cost
            for i in opponents:
                matching = min(s.stacks[i], max(0, target - s.street_bets[i]))
                call_c[i] += present[i] * matching
        payouts = self.payout(s, scores, call_c, present)
        call_ev = float(payouts.mean()) - cost
        win = np.ones(count, bool)
        ties = np.ones(count)
        for i in opponents:
            win &= ~present[i] | (scores[s.seat] >= scores[i])
            ties += present[i] & (scores[s.seat] == scores[i])
        equity = float(np.mean(win / ties))
        margin = 0. if len(board) == 5 else (.018 + .015 * (not late) + .008 * min(3, len(opponents)-1))
        margin *= self.caution
        if cost and call_ev < margin * max(1, s.pot + cost):
            return fold
        if not board:
            premium = (pair and hi >= 10) or (hi == 12 and lo == 11)
            if s.can_raise and premium and len(pre_raises) == 1 and cost <= 18 and equity > (.53 if len(opponents) == 1 else .42):
                return self.raise_by(s, max(10, 2 * max(s.street_bets)))
            return call
        own = values(np.array([hole + board]))[0]
        category = int(own // 15**5)
        shared = len(board) == 5 and own == values(np.array([board]))[0]
        threshold = (.60 if cost == 0 else .77) + .035 * min(3, len(opponents)-1)
        threshold += .025 * (self.caution - 1)
        if not s.can_raise or shared:
            return call
        if equity >= threshold:
            fractions = (.40, .70, 1.) if equity > .88 else (.40, .65)
            best, best_ev = None, call_ev
            uniforms = {i: self.rng.random(count) for i in opponents}
            for fraction in fractions:
                action = self.raise_by(s, max(2, fraction * (s.pot + cost)))
                paid = action.amount - s.street_bets[s.seat]
                c = np.tile(committed[:, None], (1, count))
                c[s.seat] += paid
                continues = {}
                for i in opponents:
                    price = min(s.stacks[i], max(0, action.amount - s.street_bets[i]))
                    loose, _, aggression, _ = self.tendencies(s, i)
                    cutoff = .48 + .22 * min(1., price / max(1, s.pot + paid)) - .25 * max(0., loose - .32)
                    probability = .06 + .91 / (1 + np.exp((cutoff - strength[i]) * 18))
                    if s.stacks[i] == 0:
                        probability[:] = 1.
                    continues[i] = uniforms[i] < probability
                    c[i] += continues[i] * price
                ev = float(self.payout(s, scores, c, continues).mean()) - paid
                # Check-down EV omits future betting; require a reserve before increasing risk.
                if ev > best_ev + .025 * paid + .5:
                    best, best_ev = action, ev
            if best is not None:
                if cost and category < 2 and best.amount - s.street_bets[s.seat] > 70:
                    return call
                return best
        # Restrained heads-up continuation bets with equity; never random multiway river shoves.
        if cost == 0 and len(opponents) == 1 and late and len(board) == 3:
            aggressor = pre_raises and pre_raises[-1][1] == s.seat
            loose, _, _, folds = self.tendencies(s, opponents[0])
            if aggressor and equity > .30 and loose < .60 and self.rng.random() < .16 + .20 * folds:
                return self.raise_by(s, max(2, .33 * s.pot))
        return call


bot = InvokerStrategy()
