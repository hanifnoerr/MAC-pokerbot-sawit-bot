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


class LilFruit(Bot):
    name = 'lil fruit v3.0'

    def __init__(self):
        self.rng = np.random.default_rng(391731)
        self.stats = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
        self.hand_count = 0
        self.voluntary = set()
        self.pre_acted = set()
        self.cache = {}

    def on_hand_start(self, info):
        self.hand_count += 1
        self.voluntary.clear()
        self.pre_acted.clear()
        self.cache.clear()

    def on_action(self, event):
        seat = event.get('seat', -1)
        players = event.get('players', [])
        if not 0 <= seat < len(players):
            return
        player = players[seat]
        st = self.stats[player]
        kind = event['action']
        if event['street'] == 'preflop':
            if player not in self.pre_acted:
                st[3] += 1
                self.pre_acted.add(player)
            if kind in ('raise', 'call') and player not in self.voluntary:
                st[0] += 1
                self.voluntary.add(player)
        else:
            st[4] += 1
            st[5] += kind == 'fold'
        st[1] += kind == 'raise'
        st[2] += kind == 'call'

    def tendencies(self, player):
        vp, raises, calls, opportunities, post, folds = self.stats[player]
        loose = (vp + 5) / (opportunities + 14)
        agg = (raises + 3) / (raises + calls + 10)
        return loose, agg, (folds + 3) / (post + 10)

    def features(self, hole, board):
        key = tuple(hole + board)
        if key in self.cache:
            return self.cache[key]
        visible = set(hole + board)
        deck = np.array([c for c in range(52) if c not in visible], dtype=np.int16)
        combos = np.array(list(itertools.combinations(deck, 2)), dtype=np.int16)
        feats = {'preflop': preflop(combos)}
        for street, size in [('flop', 3), ('turn', 4), ('river', 5)]:
            if len(board) < size:
                continue
            prefix = board[:size]
            v = values(np.column_stack((combos, np.tile(prefix, (len(combos), 1)))))
            # Midrank includes tie mass, so a paired board cannot manufacture value.
            ordered = np.sort(v)
            percentile = (np.searchsorted(ordered, v, 'left') + np.searchsorted(ordered, v, 'right')) / (2 * len(v))
            if size < 5:
                allcards = np.column_stack((combos, np.tile(prefix, (len(combos), 1))))
                flush_draw = np.zeros(len(combos), dtype=bool)
                for suit in range(4):
                    flush_draw |= ((allcards // 13 == suit).sum(axis=1) == 4) & (combos // 13 == suit).any(axis=1)
                ranks = allcards % 13
                straight_draw = np.zeros(len(combos), dtype=bool)
                for low in range(-1, 9):
                    window = [(low + i) % 13 for i in range(5)]
                    hits = sum((ranks == rank).any(axis=1) for rank in window)
                    straight_draw |= hits == 4
                percentile = np.maximum(percentile, .53 + .13 * flush_draw + .05 * straight_draw)
            feats[street] = percentile
        result = deck, combos, feats
        self.cache[key] = result
        return result

    def range_weights(self, s, combos, feats, seat):
        loose, agg, _ = self.tendencies(s.players[seat])
        actions = [a for a in s.history if a[1] == seat]
        if self.stats[s.players[seat]][0] >= 8 and loose > .60 and agg > .60:
            actions = []
        weights = np.ones(len(combos))
        raises = defaultdict(int)
        # Reconstruct prices from public raise-to totals and actual call deltas.
        pot = 3
        bets = [0] * s.num_players
        bets[(s.button if s.num_players == 2 else (s.button + 1) % s.num_players)] = 1
        bets[(s.button + (1 if s.num_players == 2 else 2)) % s.num_players] = 2
        current_street = 'preflop'
        ratios = {}
        for index, (street, who, kind, amount) in enumerate(s.history):
            if street != current_street:
                bets = [0] * s.num_players
                current_street = street
            if kind == 'raise':
                call = max(bets) - bets[who]
                ratios[index] = max(0, amount - max(bets)) / max(1, pot + call)
                pot += amount - bets[who]
                bets[who] = amount
            elif kind == 'call':
                ratios[index] = amount / max(1, pot + amount)
                pot += amount
                bets[who] += amount
        indexed = [(i, a) for i, a in enumerate(s.history) if a[1] == seat]
        if not actions:
            indexed = []
        for index, (street, _, kind, amount) in indexed:
            val = feats.get(street, np.full(len(combos), .5))
            if kind == 'raise':
                raises[street] += 1
                cutoff = (.62 if street == 'preflop' else .70) + .05 * (raises[street] - 1)
                cutoff += .10 * min(2., ratios.get(index, .5)) if street != 'preflop' else .04 * (amount >= 40) + .04 * (amount >= 100)
                cutoff -= .22 * max(0, loose - .35) + .24 * max(0, agg - .35)
                floor = .02 + .10 * agg
                likelihood = floor + .90 / (1 + np.exp((cutoff - val) * 18))
            elif kind == 'call':
                cutoff = (.48 if street == 'preflop' else .41 + .35 * ratios.get(index, .2)) - .28 * max(0, loose - .35)
                likelihood = .12 + .83 / (1 + np.exp((cutoff - val) * 13))
            elif kind == 'check':
                likelihood = 1 - .35 * (val > .85)
            else:
                continue
            weights *= likelihood
        weights = np.maximum(weights, 1e-12)
        return weights / weights.sum()

    def estimate(self, s, hole, board):
        deck, combos, feats = self.features(hole, board)
        opponents = [i for i in range(s.num_players) if i != s.seat and not s.folded[i]]
        probs = [self.range_weights(s, combos, feats, i) for i in opponents]
        if len(board) == 5 and len(opponents) == 1:
            own = values(np.array([hole + board]))[0]
            others = values(np.column_stack((combos, np.tile(board, (len(combos), 1)))))
            return float(np.dot(probs[0], (own > others) + .5 * (own == others)))
        count = 384 if s.clock_ms > 3000 else 96
        chosen = []
        used = np.zeros((count, 52), dtype=bool)
        used[:, hole + board] = True
        rows = np.arange(count)
        for p in probs:
            hands = combos[self.rng.choice(len(combos), count, p=p)]
            for _ in range(32):
                conflict = used[rows, hands[:, 0]] | used[rows, hands[:, 1]]
                if not conflict.any():
                    break
                hands[conflict] = combos[self.rng.choice(len(combos), conflict.sum(), p=p)]
            conflict = used[rows, hands[:, 0]] | used[rows, hands[:, 1]]
            # Bounded rejection must never evaluate duplicate cards.
            for row in np.flatnonzero(conflict):
                valid = ~used[row, combos[:, 0]] & ~used[row, combos[:, 1]]
                q = p * valid
                hands[row] = combos[self.rng.choice(len(combos), p=q / q.sum())]
            used[rows, hands[:, 0]] = True
            used[rows, hands[:, 1]] = True
            chosen.append(hands)
        if len(board) < 5:
            keys = self.rng.random((count, 52))
            keys[used] = 2
            future = np.argsort(keys, axis=1)[:, :5 - len(board)]
            final = np.column_stack((np.tile(board, (count, 1)), future))
        else:
            final = np.tile(board, (count, 1))
        own = values(np.column_stack((np.tile(hole, (count, 1)), final)))
        others = np.array([values(np.column_stack((hands, final))) for hands in chosen])
        win = (own >= others).all(axis=0)
        ties = (own == others).sum(axis=0)
        return float(np.mean(win / (1 + ties)))

    def bet(self, s, increment):
        if not s.can_raise:
            return s.call() if s.to_call else s.check()
        total = s.street_bets[s.seat] + s.to_call + int(increment)
        return s.raise_to(max(s.min_raise_to, min(s.max_raise_to, total)))

    def emergency(self, s, hole, board):
        if not s.to_call:
            return s.check()
        if not board:
            return s.call() if preflop(np.array([hole]))[0] >= .88 else s.fold()
        own = values(np.array([hole + board]))[0]
        if len(board) == 5:
            deck = [c for c in range(52) if c not in hole + board]
            combos = np.array(list(itertools.combinations(deck, 2)))
            other = values(np.column_stack((combos, np.tile(board, (len(combos), 1)))))
            if own >= other.max():
                return s.call()
        category = own // 15 ** 5
        if len(board) == 5 and own <= values(np.array([board]))[0]:
            return s.call() if s.to_call / (s.pot + s.to_call) < .07 else s.fold()
        return s.call() if category >= 4 or (category >= 1 and s.to_call / (s.pot + s.to_call) < .07) else s.fold()

    def act(self, s):
        hole, board = parse_cards(s.hole), parse_cards(s.board)
        fallback = s.check() if not s.to_call else s.fold()
        if s.clock_ms < 600:
            return self.emergency(s, hole, board)
        power = preflop(np.array([hole]))[0]
        opponents = [i for i in range(s.num_players) if i != s.seat and not s.folded[i]]
        if not opponents:
            return s.call() if s.to_call else s.check()
        own_order = (s.seat - s.button - 1) % s.num_players
        last = all((i - s.button - 1) % s.num_players < own_order for i in opponents)
        raises = [a for a in s.history if a[0] == 'preflop' and a[2] == 'raise']
        if not board and not raises:
            cutoff = .60 if s.num_players >= 5 else .56
            if s.seat == s.button:
                cutoff -= .08
            elif s.seat == (s.button - 1) % s.num_players:
                cutoff -= .035
            if s.num_players == 2:
                cutoff = .41
            limpers = sum(a[0] == 'preflop' and a[2] == 'call' for a in s.history)
            if power >= cutoff:
                return self.bet(s, 4 + 2 * limpers)
            if s.to_call <= 2 and power >= cutoff - .08 and limpers:
                return s.call() if s.to_call else s.check()
            return fallback
        eq = self.estimate(s, hole, board)
        cost = min(s.to_call, s.my_stack)
        required = cost / max(1, s.pot + cost)
        if not board:
            hi,lo=sorted([c % 13 for c in hole],reverse=True)
            premium = (hi == lo and hi >= 9) or (hi == 12 and lo == 11)
            if premium and eq > (.48 if len(opponents) == 1 else .40) and cost <= 40:
                return self.bet(s, max(s.pot, 3 * cost))
            margin = .025 + .025 * (not last) + .015 * (len(opponents) > 1)
            return s.call() if eq > required + margin else fallback
        margin = 0 if len(board) == 5 else .02 + .025 * (not last) + .015 * (len(opponents) > 1)
        if cost and eq < required + margin:
            return s.fold()
        own = values(np.array([hole + board]))[0]
        category = own // 15 ** 5
        ranks = [c % 13 for c in hole]
        pair_rank = (own // 15 ** 4) % 15 - 1
        board_high = max(c % 13 for c in board)
        real_pair = category == 1 and pair_rank in ranks
        strong = category >= 3 or (category == 2 and (ranks[0] == ranks[1] or all(r in [c % 13 for c in board] for r in ranks)))
        if len(board) == 5 and own <= values(np.array([board]))[0]:
            strong = False
            real_pair = False
        threshold = (.64 if not cost else .80) + .045 * (len(opponents) > 1)
        if eq > threshold and s.can_raise and (strong or (real_pair and pair_rank >= board_high)):
            if cost and category < 3 and s.pot > 70:
                return s.call()
            fraction = .45 if category < 3 else .70
            if eq > .93:
                fraction = 1.
            return self.bet(s, max(2, fraction * (s.pot + cost)))
        if not cost and len(opponents) == 1 and last and s.can_raise:
            _, _, fold_rate = self.tendencies(s.players[opponents[0]])
            aggressor = raises and raises[-1][1] == s.seat
            if len(board) == 3 and aggressor and eq > .30 and self.rng.random() < .20 + .20 * fold_rate:
                return self.bet(s, max(2, .33 * s.pot))
        return s.call() if cost else s.check()

import itertools
import numpy as np
from macpoker.cards import parse_cards

STREETS = ('preflop', 'flop', 'turn', 'river')
KINDS = ('fold', 'check', 'call', 'raise')

def action_table(s):
    actions = [s.fold(), s.call() if s.to_call else s.check()]
    mask = [bool(s.to_call), True]
    seen = set()
    for fraction in (0, 1/3, 2/3, 1, None):
        total = s.min_raise_to if fraction == 0 else s.max_raise_to if fraction is None else (
            s.street_bets[s.seat] + s.to_call + int(fraction * (s.pot + s.to_call)))
        total = max(s.min_raise_to, min(s.max_raise_to, total))
        valid = s.can_raise and total not in seen
        actions.append(s.raise_to(total))
        mask.append(valid)
        seen.add(total)
    return actions, np.array(mask, dtype=bool)

def teacher_index(action, actions, mask):
    if action.kind == 'fold': return 0 if mask[0] else 1
    if action.kind in ('check', 'call'): return 1
    indices = np.flatnonzero(mask & (np.arange(7) >= 2))
    return int(min(indices, key=lambda i: abs(actions[i].amount - action.amount))) if len(indices) else 1

class Policy(LilFruit):
    name = 'lil fruit BC'
    def __init__(self, weights=None, seed=881361):
        super().__init__()
        self.weights = weights
        self.action_rng = np.random.default_rng(seed)

    def encode(self, s):
        hole, board = parse_cards(s.hole), parse_cards(s.board)
        # Lexicographic suit canonicalization preserves the complete card relation.
        canonical = min((tuple(sorted((p[c // 13] * 13 + c % 13 for c in hole), reverse=True)),
                         tuple(sorted(p[c // 13] * 13 + c % 13 for c in board)), p)
                        for p in itertools.permutations(range(4)))
        h, b, permutation = canonical
        features = []
        for c in h:
            features.extend(float(c % 13 == r) for r in range(13))
            features.extend(float(c // 13 == suit) for suit in range(4))
        features.extend(float(suit * 13 + r in b) for suit in range(4) for r in range(13))
        if board:
            v = int(values(np.array([hole + board]))[0])
            category = v // 15 ** 5
            tiebreak = [(v // 15 ** i) % 15 / 14 for i in range(4, -1, -1)]
        else:
            category = 0
            tiebreak = [0.] * 5
        features.extend(float(category == c) for c in range(9))
        features.extend(tiebreak)
        features.extend(float(s.street == street) for street in STREETS)
        power = float(preflop(np.array([hole]))[0])
        canonical_board=[permutation[c // 13]*13+c % 13 for c in board]
        eq = self.estimate(s, list(h), canonical_board) if board or any(a[2]=='raise' for a in s.history) else power
        cost = s.to_call
        features.extend([power, eq, s.num_players/6, s.players_in_hand/6,
                         (s.seat-s.button) % s.num_players / s.num_players,
                         s.seat == s.button, s.pot/200, cost/200,
                         cost/max(1,s.pot+cost), s.my_stack/200,
                         s.street_bets[s.seat]/200, s.min_raise_to/200,
                         s.max_raise_to/200, s.can_raise,
                         min(10,s.my_stack/max(1,s.pot))/10])
        opponents = sorted((i for i in range(s.num_players) if i!=s.seat),
                           key=lambda i:(i-s.button) % s.num_players)
        for j in range(5):
            if j >= len(opponents):
                features.extend([0.] * 9)
            else:
                i = opponents[j]
                loose, agg, folds = self.tendencies(s.players[i])
                features.extend([1.,not s.folded[i],s.stacks[i]/200,s.street_bets[i]/200,
                                 loose,agg,folds,min(1,self.stats[s.players[i]][3]/50),
                                 (i-s.button) % s.num_players / s.num_players])
        recent=s.history[-8:]
        for j in range(8):
            if j>=len(recent):
                features.extend([0.]*11)
            else:
                street, seat, kind, amount=recent[j]
                features.extend(float(street==t) for t in STREETS)
                features.extend(float(kind==k) for k in KINDS)
                features.extend([(seat-s.button) % s.num_players / s.num_players,amount/200,1.])
        _,mask=action_table(s)
        features.extend(mask.astype(float))
        return np.asarray(features,dtype=np.float32),mask

    def forward(self,x,mask):
        w=self.weights
        hidden=np.maximum(0,x@w['w1']+w['b1'])
        hidden=np.maximum(0,hidden@w['w2']+w['b2'])
        logits=hidden@w['wa']+w['ba']
        masked=np.where(mask,logits,-1e9)
        p=np.exp(masked-masked.max(axis=-1,keepdims=True))
        p/=p.sum(axis=-1,keepdims=True)
        value=(hidden@w['wv']+w['bv']).squeeze(-1) if 'wv' in w else np.zeros(logits.shape[:-1])
        return logits,p,value

    def act(self,s):
        if s.clock_ms<600:
            return self.emergency(s,parse_cards(s.hole),parse_cards(s.board))
        x,mask=self.encode(s)
        _,p,_=self.forward(x,mask)
        cumulative=np.cumsum(p,dtype=np.float64)
        index=int(np.searchsorted(cumulative,self.action_rng.random()*cumulative[-1],side='right'))
        return action_table(s)[0][index]

Policy.name = 'lil fruit PPO 600000 all-size'
bot = Policy(dict(np.load(os.path.join(os.path.dirname(__file__), 'weights.npz'), allow_pickle=False)))
