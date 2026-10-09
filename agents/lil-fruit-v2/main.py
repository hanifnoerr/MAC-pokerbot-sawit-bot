import bisect
import itertools
import math
import random
import time
from collections import Counter, defaultdict
from macpoker import Bot
from macpoker.cards import parse_cards


def rank(cards):
    counts = Counter(c % 13 for c in cards)
    groups = sorted(((n, r) for r, n in counts.items()), reverse=True)
    suits = [[] for _ in range(4)]
    for c in cards:
        suits[c // 13].append(c % 13)

    def straight(rs):
        mask = sum(1 << r for r in set(rs))
        for h in range(12, 3, -1):
            if mask & (31 << (h - 4)) == 31 << (h - 4):
                return h
        return 3 if mask & 4111 == 4111 else -1

    flush = next((sorted(rs, reverse=True) for rs in suits if len(rs) >= 5), None)
    if flush:
        high = straight(flush)
        if high >= 0:
            return (8, high)
    if groups[0][0] == 4:
        q = groups[0][1]
        return (7, q, max(r for r in counts if r != q))
    trips = sorted((r for r, n in counts.items() if n >= 3), reverse=True)
    if trips:
        pairs = sorted((r for r, n in counts.items() if n >= 2 and r != trips[0]), reverse=True)
        if pairs:
            return (6, trips[0], pairs[0])
    if flush:
        return (5, *flush[:5])
    high = straight(counts)
    if high >= 0:
        return (4, high)
    if trips:
        return (3, trips[0], *sorted((r for r in counts if r != trips[0]), reverse=True)[:2])
    pairs = sorted((r for r, n in counts.items() if n >= 2), reverse=True)
    if len(pairs) >= 2:
        return (2, *pairs[:2], max(r for r in counts if r not in pairs[:2]))
    if pairs:
        return (1, pairs[0], *sorted((r for r in counts if r != pairs[0]), reverse=True)[:3])
    return (0, *sorted(counts, reverse=True)[:5])


def preflop(cards):
    hi, lo = sorted((c % 13 for c in cards), reverse=True)
    if hi == lo:
        return .50 + .035 * hi
    return (.24 + .024 * hi + .014 * lo + .04 * (cards[0] // 13 == cards[1] // 13)
            + .025 * (hi - lo == 1) - .01 * max(0, hi - lo - 2) + .04 * (hi == 12))


def strength(hole, board):
    value = rank(hole + board)
    cat = value[0]
    board_counts = Counter(c % 13 for c in board)
    own = [c % 13 for c in hole]
    if cat >= 4:
        result = .91 + .012 * cat
    elif cat == 3:
        result = .89 if value[1] in own else .47
    elif cat == 2:
        result = .84 if sum(r in own for r, n in board_counts.items() if n >= 2) or len([r for r in own if r in board_counts]) == 2 else .50
        if own[0] == own[1] and own[0] > max(board_counts):
            result = .73
    elif cat == 1:
        pair = value[1]
        if pair not in own:
            result = .24 + .018 * max(own)
        elif pair >= max(board_counts):
            result = .69 + .006 * max(own)
        else:
            result = .40 + .018 * pair
    else:
        result = .15 + .02 * max(own)
    if len(board) < 5:
        suits = Counter(c // 13 for c in hole + board)
        flush_draw = any(n == 4 and any(c // 13 == suit for c in hole) for suit, n in suits.items())
        ranks = set(own + list(board_counts))
        if 12 in ranks:
            ranks.add(-1)
        draw = max(sum(r in ranks for r in range(low, low + 5)) for low in range(-1, 9)) >= 4
        result = max(result, .48 + .08 * flush_draw + .04 * draw) if flush_draw or draw else result
    return min(.99, result)


class LilFruit(Bot):
    name = 'lil fruit v2'

    def __init__(self):
        self.rng = random.Random(731905)
        self.stats = defaultdict(lambda: [0, 0, 0])
        self.hand_count = 0
        self.voluntary = set()
        self.cache = {}

    def on_hand_start(self, info):
        self.hand_count += 1
        self.voluntary.clear()
        self.cache.clear()

    def on_action(self, event):
        players = event.get('players', [])
        seat = event.get('seat', -1)
        if not 0 <= seat < len(players):
            return
        player = players[seat]
        action = event.get('action')
        if event.get('street') == 'preflop' and action in ('raise', 'call') and player not in self.voluntary:
            self.stats[player][0] += 1
            self.voluntary.add(player)
        if action == 'raise':
            self.stats[player][1] += 1
        elif action == 'call':
            self.stats[player][2] += 1

    def loose(self, player):
        return (self.stats[player][0] + 5) / (self.hand_count + 14)

    def aggressive(self, player):
        _, raises, calls = self.stats[player]
        return (raises + 3) / (raises + calls + 10)

    def estimate(self, s, deadline):
        hole, board = parse_cards(s.hole), parse_cards(s.board)
        visible = set(hole + board)
        deck = [c for c in range(52) if c not in visible]
        opponents = [i for i in range(s.num_players) if i != s.seat and not s.folded[i]]
        combos = list(itertools.combinations(deck, 2))
        candidates = self.rng.sample(combos, min(220, len(combos)))
        features = {}
        for h in candidates:
            features[h] = {'preflop': preflop(h)}
            for street, size in [('flop', 3), ('turn', 4), ('river', 5)]:
                if len(board) >= size:
                    features[h][street] = strength(list(h), board[:size])
        ranges = []
        for seat in opponents:
            player = s.players[seat]
            loose = self.loose(player)
            agg = self.aggressive(player)
            actions = [a for a in s.history if a[1] == seat and a[2] in ('raise', 'call', 'check')]
            weights = []
            for h in candidates:
                weight = 1.
                raises = defaultdict(int)
                for street, _, kind, amount in actions:
                    value = features[h].get(street, .5)
                    if kind == 'raise':
                        raises[street] += 1
                        cutoff = (.60 if street == 'preflop' else .66) + .06 * (raises[street] - 1)
                        cutoff += .06 * (amount >= 40) + .04 * (amount >= 100)
                        cutoff -= .18 * max(0, loose - .35) + .16 * max(0, agg - .35)
                        likelihood = .025 + .09 * agg + .90 / (1 + math.exp((cutoff - value) * 17))
                    elif kind == 'call':
                        cutoff = (.48 if street == 'preflop' else .44) - .24 * max(0, loose - .35)
                        likelihood = .15 + .80 / (1 + math.exp((cutoff - value) * 13))
                    else:
                        likelihood = .95 - .30 * (value > .8)
                    weight *= likelihood
                weights.append(max(1e-8, weight))
            ranges.append(list(itertools.accumulate(weights)))
        score = 0.
        count = 0
        target = 240 if len(board) == 5 else 160
        while count < target and (count < 24 or time.perf_counter() < deadline):
            used = set(visible)
            hands = []
            for cumulative in ranges:
                chosen = None
                for attempt in range(40):
                    h = candidates[bisect.bisect_left(cumulative, self.rng.random() * cumulative[-1])]
                    if h[0] not in used and h[1] not in used:
                        chosen = h
                        break
                if chosen is None:
                    chosen = self.rng.sample([c for c in deck if c not in used], 2)
                hands.append(list(chosen))
                used.update(chosen)
            future = board + self.rng.sample([c for c in deck if c not in used], 5 - len(board))
            hero = rank(hole + future)
            others = [rank(h + future) for h in hands]
            if all(hero >= other for other in others):
                score += 1 / (1 + sum(hero == other for other in others))
            count += 1
        return score / count

    def bet(self, s, increment):
        if not s.can_raise:
            return s.call() if s.to_call else s.check()
        total = s.street_bets[s.seat] + s.to_call + int(increment)
        return s.raise_to(max(s.min_raise_to, min(s.max_raise_to, total)))

    def act(self, s):
        fallback = s.check() if s.to_call == 0 else s.fold()
        hole = parse_cards(s.hole)
        power = preflop(hole)
        opponents = [i for i in range(s.num_players) if i != s.seat and not s.folded[i]]
        if not opponents:
            return s.check() if not s.to_call else s.call()
        if s.clock_ms < 250:
            return s.call() if power > .86 else fallback
        own_order = (s.seat - s.button - 1) % s.num_players
        last = all((i - s.button - 1) % s.num_players < own_order for i in opponents)
        pre_raises = [a for a in s.history if a[0] == 'preflop' and a[2] == 'raise']
        if s.street == 'preflop' and not pre_raises:
            cutoff = .59 if s.num_players >= 5 else .55
            if s.seat == s.button:
                cutoff -= .07
            if s.num_players == 2:
                cutoff = .43
            if power >= cutoff:
                limpers = sum(a[0] == 'preflop' and a[2] == 'call' for a in s.history)
                return self.bet(s, 4 + 2 * limpers)
            if s.to_call <= 1 and power >= cutoff - .07:
                return s.call()
            return fallback
        remaining = max(10, 100 - s.hand)
        budget = min(.11, max(.012, (s.clock_ms / 1000 - 1) / (remaining * 4)))
        eq = self.estimate(s, time.perf_counter() + budget)
        cost = min(s.to_call, s.my_stack)
        required = cost / max(1, s.pot + cost)
        if s.street == 'preflop':
            if power >= .85 and eq >= .48:
                return self.bet(s, max(s.pot, 3 * cost))
            margin = .025 + .025 * (not last) + .015 * (len(opponents) > 1)
            if cost > 30 and power < .70:
                margin += .05
            return s.call() if eq >= required + margin else fallback
        board = parse_cards(s.board)
        made = strength(hole, board)
        pot_ratio = cost / max(1, s.pot - cost)
        margin = 0 if s.street == 'river' else .025 + .02 * (not last)
        if cost and eq < required + margin:
            return s.fold()
        value_threshold = .70 + .035 * (len(opponents) > 1) + .04 * bool(cost)
        if eq > value_threshold and made >= .69 and s.can_raise:
            if made < .84 and (pot_ratio > .7 or s.pot > 100):
                return s.call() if cost else s.check()
            fraction = .50 if made < .84 else .75
            if made > .94 and eq > .90:
                fraction = 1.
            return self.bet(s, max(2, fraction * (s.pot + cost)))
        if not cost and len(opponents) == 1 and last and s.can_raise:
            prior_aggressor = pre_raises and pre_raises[-1][1] == s.seat
            if s.street == 'flop' and prior_aggressor and eq > .30 and self.rng.random() < .24:
                return self.bet(s, max(2, .33 * s.pot))
        return s.call() if cost else s.check()
