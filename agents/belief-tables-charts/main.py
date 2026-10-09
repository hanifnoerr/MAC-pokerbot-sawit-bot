"""Belief-search poker bot.

Architecture (no rule engine, no neural policy for our own actions):
  1. A population action model P(action | own hand, public state), fitted
     offline, is the prior for how any opponent plays a given holding.
  2. Each opponent's range is a Bayesian belief over all 1326 combos, updated
     by that model after every public action. Per-player action frequencies
     observed in this game shift the model (shrunk toward the prior).
  3. Our decision is an expectimax over our betting options: each option is
     scored by the modelled fold / call / re-raise responses, the ranges those
     responses imply, exact or enumerated showdown equity and side-pot payouts.
Only our own cards, public actions and anonymous player ids are used.
"""
import os
for _key in ('OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS'):
    os.environ[_key] = '1'
import itertools
import sys
import numpy as np
from macpoker import Bot
from macpoker.cards import parse_cards
import core

STREETS = {'preflop': 0, 'flop': 1, 'turn': 2, 'river': 3}
# Share of hands opened first-in, by number of players still to act behind us.
OPEN = {0: .48, 1: .48, 2: .46, 3: .29, 4: .22, 5: .17, 6: .145, 7: .125, 8: .11}
PARAMS = dict(
    tremble=.06,          # share of opponent actions treated as hand-independent
    prior_pre=10., prior_post=6.,   # pseudo-observations behind the population prior
    raise_reserve=.03, bluff_reserve=.05,
    call_reserve=.08, river_call_reserve=.15,   # margin, as a share of a 30+ chip call
    future=1.0,           # weight of the later-street betting adjustment
    fold_trust=.9,        # share of modelled fold equity we rely on
    bluff_cap=.7, semi_cap=1.05,    # largest pot fraction for (semi-)bluffs
    adapt=1.,             # 0 disables per-opponent adaptation (ablation)
    steal=1.,             # 1 = widen/narrow opens by how often players behind fold to raises
    flop_runs=300,        # sampled turn+river runouts on the flop
)


class Table:
    """Public betting state rebuilt from the action list."""

    def __init__(self, n, button, stacks=None):
        self.n, self.button = n, button
        self.stack = list(stacks) if stacks else [200] * n
        self.folded = [False] * n
        self.bets = [0] * n
        self.committed = [0] * n
        self.blind = [0] * n
        self.pot, self.street, self.raises, self.limpers, self.aggressor = 0, 0, 0, 0, -1
        self.acted = set()
        sb = button if n == 2 else (button + 1) % n
        bb = (button + 1) % n if n == 2 else (button + 2) % n
        for seat, amount, tag in ((sb, 1, 1), (bb, 2, 2)):
            self.pay(seat, min(amount, self.stack[seat]))
            self.blind[seat] = tag

    def pay(self, seat, chips):
        self.stack[seat] -= chips
        self.bets[seat] += chips
        self.committed[seat] += chips
        self.pot += chips

    def order(self, seat):
        if self.n == 2:
            return (seat - self.button) % 2 if self.street == 0 else (seat - self.button - 1) % 2
        return (seat - self.button - (3 if self.street == 0 else 1)) % self.n

    def to_call(self, seat):
        return min(max(self.bets) - self.bets[seat], self.stack[seat])

    def behind(self, seat):
        mine = self.order(seat)
        return sum(1 for i in range(self.n) if i != seat and not self.folded[i]
                   and self.stack[i] > 0 and self.order(i) > mine)

    def active(self):
        return sum(not f for f in self.folded)

    def enter(self, street):
        if street != self.street:
            self.street, self.bets, self.raises, self.acted = street, [0] * self.n, 0, set()

    def apply(self, seat, kind, amount):
        if kind == 'fold':
            self.folded[seat] = True
        elif kind == 'call':
            if self.street == 0 and self.raises == 0:
                self.limpers += 1
            self.pay(seat, min(amount, self.stack[seat]))
        elif kind == 'raise':
            self.pay(seat, max(0, min(amount - self.bets[seat], self.stack[seat])))
            self.raises += 1
            self.aggressor = seat
        self.acted.add(seat)

    def pre_ctx(self, seat):
        blind = self.blind[seat]
        return core.pre_context(self.pot, self.to_call(seat), max(self.bets), self.raises, self.limpers,
                                self.active(), self.behind(seat), blind, self.bets[seat] > blind)

    def post_ctx(self, seat, board, pot=None, to_call=None, raises=None, aggressor=None):
        return core.post_context(self.street, self.pot if pot is None else pot,
                                 self.to_call(seat) if to_call is None else to_call, self.stack[seat],
                                 self.active(), self.behind(seat),
                                 self.aggressor == seat if aggressor is None else aggressor,
                                 self.raises if raises is None else raises, board)


class BeliefSearch(Bot):
    name = 'belief search'

    def __init__(self, **overrides):
        self.p = dict(PARAMS, **overrides)
        data = np.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'model.npz'))
        self.net = {k: [data[f'{k}_{part}'].astype(np.float64) for part in ('w1', 'b1', 'w2', 'b2')]
                    for k in ('pre', 'unbet', 'facing')}
        self.rates = {k: data[f'{k}_rates'].astype(np.float64) for k in self.net}
        self.equity = data['equity'].astype(np.float64)
        self.pre_feat = core.preflop_features(data['eq_random'].astype(np.float64))
        self.hand_sd = float(data['hand_sd'][0])
        self.bet_sizes = [float(x) for x in data['unbet_sizes']]
        self.raise_size = float(np.mean(data['raise_sizes']))
        # Opening order: all-in equity plus playability of suited/connected hands.
        hi, lo, suited = core.CHI, core.CLO, core.CSUITED
        gap = hi - lo
        score = (data['eq_random'].astype(np.float64)[core.CLS] + .035 * suited
                 + .012 * np.clip(4 - gap, 0, 3) * (gap > 0) * (lo >= 2) - .012 * (~suited) * (gap >= 4))
        cls_score = np.zeros(169)
        cls_score[core.CLS] = score
        order = np.argsort(-cls_score)
        better = np.zeros(169)
        better[order] = np.cumsum(core.CLS_COUNT[order]) - core.CLS_COUNT[order]
        self.open_pct = better / core.NC
        self.rng = np.random.default_rng(7919)
        self.stats = {}
        self.totals = {}
        self.pub = None
        self.tb = None
        self.feat, self.belief, self.done = {}, {}, 0
        self.hand_no = None
        self.hands_total, self.hands_seen = 100, 0
        self.errors = 0
        self.start = None

    # ------------------------------------------------------------ observers
    def on_match_start(self, info):
        self.hands_total = int(info.get('num_hands', 100) or 100)

    def on_hand_start(self, info):
        stacks = info.get('stacks') or []
        self.start = list(stacks)
        self.pub = Table(len(stacks), info.get('button', 0), stacks) if len(stacks) >= 2 else None
        self.pub_board = []

    def on_street(self, event):
        self.pub_board = parse_cards(event.get('board', []))

    def counts(self, player):
        if player not in self.stats:
            self.stats[player] = {k: np.zeros((3, 4)) for k in self.net}
        return self.stats[player]

    def on_action(self, event):
        tb, players = self.pub, event.get('players') or []
        seat = event.get('seat', -1)
        if tb is None or not 0 <= seat < tb.n or len(players) != tb.n:
            return
        street, kind, amount = STREETS.get(event.get('street'), 0), event.get('action'), event.get('amount', 0)
        tb.enter(street)
        to_call = tb.to_call(seat)
        if street == 0:
            self.counts(players[seat])['pre'][min(tb.raises, 2), core.pre_class(kind, amount)] += 1
        else:
            fraction = (amount - max(tb.bets)) / max(1, tb.pot + to_call) if kind == 'raise' else 0.
            name = 'facing' if to_call > 0 else 'unbet'
            self.counts(players[seat])[name][street - 1, core.post_class(kind, fraction, to_call > 0)] += 1
        tb.apply(seat, kind, amount)

    def on_hand_end(self, info):
        players = info.get('players') or []
        for seat, delta in enumerate(info.get('deltas') or []):
            if seat < len(players):
                self.totals[players[seat]] = self.totals.get(players[seat], 0) + delta
        self.hands_seen += 1

    # ------------------------------------------------------------ opponent model
    def adapt(self, player, name, bucket):
        table = self.counts(player)[name]
        if name == 'pre':
            n, rate = table[bucket], self.rates[name][bucket]
        else:       # few postflop decisions per game: pool the three streets
            n, rate = table.sum(0), self.rates[name].mean(0)
        total = n.sum()
        if not self.p['adapt']:
            return None, 0., rate
        prior = self.p['prior_pre'] if name == 'pre' else self.p['prior_post']
        shift = np.clip(np.log((n + prior * rate) / ((total + prior) * rate)), -2.5, 2.5)
        if total < 5:
            return shift, 0., rate
        freq = (n + rate) / (total + 1.)
        top = int(np.argmax(freq))
        # A near-deterministic action that the population rarely takes carries
        # little information about the hand (always-call, always-shove bots).
        weight = (min(1., max(0., (freq[top] - .8) / .15)) * min(1., max(0., (freq[top] - rate[top] - .25) / .2))
                  * total / (total + 8.))
        return shift, weight, freq

    def probs(self, name, bucket, player, x):
        shift, weight, freq = self.adapt(player, name, bucket)
        p = core.mlp(self.net[name], x, shift)
        if weight > 0:
            p = (1 - weight) * p + weight * freq
        tremble = self.p['tremble']
        return (1 - tremble) * p + tremble * self.rates[name][bucket]

    def features(self, board):
        key = len(board)
        if key not in self.feat:
            self.feat[key] = core.board_features(board)
        return self.feat[key]

    def sync(self, s, hole, board):
        """Replay unseen actions of this hand and update every opponent's range."""
        if self.hand_no != s.hand or self.tb is None or self.tb.n != s.num_players:
            self.hand_no = s.hand
            start = self.start if self.start and len(self.start) == s.num_players else None
            self.tb = Table(s.num_players, s.button, start)
            self.done = 0
            self.feat = {}
            base = (~(core.HAS[hole[0]] | core.HAS[hole[1]])).astype(np.float64)
            self.belief = {i: base.copy() for i in range(s.num_players) if i != s.seat}
        tb = self.tb
        for street_name, seat, kind, amount in s.history[self.done:]:
            street = STREETS[street_name]
            tb.enter(street)
            if seat != s.seat and seat in self.belief:
                player = s.players[seat]
                if street == 0:
                    p = self.probs('pre', min(tb.raises, 2), player, core.pre_inputs(self.pre_feat, tb.pre_ctx(seat)))
                    like = p[:, core.pre_class(kind, amount)]
                else:
                    cards = board[:street + 2]
                    now, ahead, alive = self.features(cards)
                    to_call = tb.to_call(seat)
                    fraction = (amount - max(tb.bets)) / max(1, tb.pot + to_call) if kind == 'raise' else 0.
                    name = 'facing' if to_call > 0 else 'unbet'
                    p = self.probs(name, street - 1, player, core.post_inputs(now, ahead, tb.post_ctx(seat, cards)))
                    like = p[:, core.post_class(kind, fraction, to_call > 0)] * alive
                b = self.belief[seat] * like
                total = b.sum()
                if total > 1e-200:
                    self.belief[seat] = b / total
            tb.apply(seat, kind, amount)
        self.done = len(s.history)
        tb.enter(STREETS[s.street])
        if board:
            alive = self.features(board)[2]
            for seat in self.belief:
                b = self.belief[seat] * alive
                total = b.sum()
                self.belief[seat] = b / total if total > 0 else alive / alive.sum()

    # ------------------------------------------------------------ utilities
    @staticmethod
    def legal(s, action):
        """Last line of defence: never hand the engine an illegal action."""
        if action.kind == 'raise':
            if not s.can_raise:
                return s.call() if s.to_call else s.check()
            return s.raise_to(int(max(s.min_raise_to, min(s.max_raise_to, action.amount))))
        if action.kind in ('call', 'fold') and not s.to_call:
            return s.check()
        if action.kind == 'check' and s.to_call:
            return s.fold()
        return action

    @staticmethod
    def legal_raise(s, target):
        return s.raise_to(int(max(s.min_raise_to, min(s.max_raise_to, target))))

    # ------------------------------------------------------------ preflop
    def preflop(self, s, hole):
        tb, seat, n = self.tb, s.seat, s.num_players
        combo = int(core.CIDX[hole[0], hole[1]])
        cls = int(core.CLS[combo])
        pct = float(self.open_pct[cls])
        hi, lo, suited = int(core.CHI[combo]), int(core.CLO[combo]), bool(core.CSUITED[combo])
        pair = hi == lo
        stack = s.my_stack
        t = min(s.to_call, stack)
        check_or_fold = s.fold() if t else s.check()
        opps = [i for i in range(n) if i != seat and not s.folded[i]]
        if not opps:
            return s.check() if not t else s.call()
        if tb.raises == 0:
            limpers = tb.limpers
            behind = tb.behind(seat)
            # Players still to act who fold to raises more (less) than the field
            # make a wider (narrower) opening range correct.
            steal = 1.
            if self.p['steal'] and self.p['adapt']:
                base = float(self.rates['pre'][1][0])
                for i in opps:
                    if tb.stack[i] > 0 and (n == 2 or tb.order(i) > tb.order(seat)):
                        seen = self.counts(s.players[i])['pre'][1]
                        steal *= (seen[0] + 10. * base) / (seen.sum() + 10.) / base
                steal = min(1.5, max(.7, steal ** .75))
            if n == 2:
                if t == 0:      # big blind after a limp
                    return self.legal_raise(s, 6) if pct <= .35 and s.can_raise else s.check()
                if pct <= min(.95, .80 * steal) and s.can_raise:
                    return self.legal_raise(s, 5)
                return s.call() if pct <= .95 else s.fold()
            threshold = min(.85, OPEN[min(behind, 8)] * (1. if not limpers else .8 if limpers == 1 else .65) * steal)
            if tb.blind[seat] == 2 and t == 0:
                if pct <= min(.30, threshold + .12) and s.can_raise:
                    return self.legal_raise(s, 7 + 2 * limpers)
                return s.check()
            if pct <= threshold and s.can_raise:
                return self.legal_raise(s, 5 + 2 * limpers + (1 if tb.blind[seat] else 0))
            if limpers and tb.blind[seat] == 1 and pct <= .60:
                return s.call()
            if limpers and t <= 2 and pct <= .55 and (pair or (suited and (hi - lo <= 2 or hi == 12))):
                return s.call()
            return check_or_fold
        # ---- facing at least one raise
        villain = tb.aggressor if tb.aggressor in self.belief and not s.folded[tb.aggressor] else opps[0]
        level = max(tb.bets)

        def versus(i):
            w = np.bincount(core.CLS, weights=self.belief[i], minlength=169)
            return float(self.equity[cls] @ w / max(w.sum(), 1e-12))

        eq = versus(villain)
        callers = [i for i in opps if i != villain and (tb.bets[i] >= level or tb.stack[i] == 0) and tb.bets[i] > 2]
        eq_all = eq
        for i in callers:
            eq_all *= min(1., versus(i) * 1.25)
        pending = [i for i in opps if tb.stack[i] > 0 and tb.bets[i] < level]
        price = t / max(1., s.pot + t)
        if t >= .35 * stack or tb.stack[villain] == 0 or level >= 60:
            if eq_all >= price + .02 + .015 * len(pending):
                if s.can_raise and t < stack and eq_all >= .60:
                    return s.raise_to(s.max_raise_to)
                return s.call()
            return check_or_fold
        ip = tb.order(seat) > tb.order(villain) if n > 2 else seat == s.button
        realise = (.93 if ip else .80) + (.05 if suited or pair else 0.) - (.08 if not suited and hi - lo >= 4 else 0.)
        value = .58 if tb.raises == 1 else .62 if tb.raises == 2 else .66
        if eq >= value and s.can_raise and (not callers or eq_all >= .42):
            target = int((3.0 if ip else 3.6) * level if tb.raises == 1 else 2.4 * level) + level * len(callers)
            if target >= .4 * (stack + tb.bets[seat]):
                target = s.max_raise_to
            return self.legal_raise(s, target)
        if t == 0:
            return s.check()
        if eq_all * realise >= price + .03 + .01 * len(pending) and (t <= 24 or eq >= .5):
            return s.call()
        return s.fold()

    # ------------------------------------------------------------ postflop search
    def wins(self, b):
        """Per-runout probability that we beat a hand drawn from range b."""
        den = self.A @ b
        return (self.W @ b) / np.maximum(den, 1e-12)

    def settle(self, hero_total, entries, dead):
        """Expected showdown payout per runout with layered side pots."""
        levels = sorted({min(t, hero_total) for t, _ in entries} | {hero_total})
        everyone = [hero_total] + [t for t, _ in entries] + dead
        out, previous = 0., 0.
        for level in levels:
            if level <= previous:
                continue
            amount = sum(min(c, level) - min(c, previous) for c in everyone)
            p = 1.
            for total, w in entries:
                if total >= level:
                    p = p * w
            out = out + amount * p
            previous = level
        return out

    def branch(self, hero_total, must, optional, dead, room):
        """Expected payout over which optional opponents continue.

        must: [(total committed, win vector)]; optional: [(probability in,
        total if in, win vector if in, total if folded)]. `room` is the stack we
        still hold after this action, for the later-street adjustment.
        """
        value = 0.
        for mask in itertools.product((0, 1), repeat=len(optional)):
            p, entries, d = 1., list(must), list(dead)
            for bit, (q, tin, win, tout) in zip(mask, optional):
                if bit:
                    p *= q
                    entries.append((tin, win))
                else:
                    p *= 1. - q
                    d.append(tout)
            if p < 1e-4:
                continue
            pay = self.settle(hero_total, entries, d)
            ev = float(np.mean(pay))
            if self.streets_left and entries and room > 0:
                beat = 1.
                for _, w in entries:
                    beat = beat * w
                pot = sum(min(c, hero_total) for c in [hero_total] + [t for t, _ in entries] + d)
                theirs = max(self.start_total - t for t, _ in entries)
                size = min(room, theirs, .7 * self.streets_left * pot)
                if size > 0:
                    gain = np.mean(.7 * np.maximum(beat - .5, 0.) * self.pos_gain - .3 * np.maximum(.5 - beat, 0.) * self.pos_loss)
                    ev += self.p['future'] * size * float(gain)
            value += p * ev
        return value

    def postflop(self, s, hole, board):
        tb, seat, n = self.tb, s.seat, s.num_players
        street = tb.street
        opps = [i for i in range(n) if i != seat and not s.folded[i]]
        stack = s.my_stack
        t = min(s.to_call, stack)
        if not opps:
            return s.call() if t else s.check()
        dead_cards = set(hole + board)
        if street == 3:
            runs = None
        elif street == 2:
            runs = np.array([[c] for c in range(52) if c not in dead_cards])
        else:
            rest = [c for c in range(52) if c not in dead_cards]
            runs = np.array(list(itertools.combinations(rest, 2)))
            count = self.p['flop_runs'] if s.clock_ms > 12000 else 120
            if len(runs) > count:
                runs = runs[self.rng.choice(len(runs), count, replace=False)]
        v, alive = core.grid(board, runs)
        alive &= ~(core.HAS[hole[0]] | core.HAS[hole[1]])
        mine = v[:, int(core.CIDX[hole[0], hole[1]])][:, None]
        self.A = alive.astype(np.float64)
        self.W = ((mine > v) + .5 * (mine == v)) * self.A
        self.streets_left = 3 - street
        reserve = self.p['river_call_reserve'] if street == 3 else self.p['call_reserve']
        # A river hand no holding can beat needs no margin and is never folded.
        nuts = street == 3 and bool((self.W[0] >= .5 * self.A[0]).all())
        if nuts:
            reserve = 0.
        self.start_total = float(self.start[seat]) if self.start and len(self.start) == n else 200.
        last = all(tb.order(seat) > tb.order(i) for i in opps)
        self.pos_gain, self.pos_loss = (1., 1.) if last else (.8, 1.2)
        now, ahead, _ = self.features(board)
        pot = s.pot
        committed = [float(c) for c in tb.committed]
        dead = [committed[i] for i in range(n) if s.folded[i]]
        belief = self.belief
        win_now = {i: self.wins(belief[i]) for i in opps}
        level = max(s.street_bets)

        def respond(i, new_pot, to_call, raises, aggressor=None):
            ctx = tb.post_ctx(i, board, pot=new_pot, to_call=to_call, raises=raises, aggressor=aggressor)
            return self.probs('facing', street - 1, s.players[i], core.post_inputs(now, ahead, ctx))

        # ---- check or call
        hero_total = committed[seat] + t
        must, optional = [], []
        waiting = [i for i in opps if tb.stack[i] > 0 and (s.street_bets[i] < level or (t == 0 and i not in tb.acted))]
        for i in opps:
            if i in waiting and t > 0:
                y = min(tb.stack[i], level - s.street_bets[i])
                p = respond(i, pot + t, y, tb.raises)
                stay = belief[i] * (1. - p[:, 0])
                q = float(stay.sum())
                optional.append((q, committed[i] + y, self.wins(stay), committed[i]))
            elif i not in waiting:
                must.append((committed[i], win_now[i]))
        optional = optional[:3] if len(optional) <= 3 else sorted(optional, key=lambda o: -o[0])[:3]
        if t > 0 or not waiting:
            passive = self.branch(hero_total, must, optional, dead, stack - t) - t
        else:
            # Players behind may bet after our check; we then call or fold.
            keep, entries, bets_ev = 1., list(must), 0.
            for j in sorted(waiting, key=tb.order):
                ctx = tb.post_ctx(j, board, pot=pot, to_call=0, raises=0)
                p = self.probs('unbet', street - 1, s.players[j], core.post_inputs(now, ahead, ctx))
                marginal = belief[j] @ p
                for k in (1, 2, 3):
                    weight = keep * float(marginal[k])
                    if weight < 2e-3:
                        continue
                    bet = max(2., min(self.bet_sizes[k - 1] * pot, tb.stack[j]))
                    cost = min(bet, stack)
                    others = [(.4, committed[i] + min(bet, tb.stack[i]), win_now[i], committed[i])
                              for i in opps if i != j and tb.stack[i] > 0][:2]
                    fixed = [(committed[i], win_now[i]) for i in opps if i != j and tb.stack[i] == 0]
                    called = self.branch(hero_total + cost, fixed + [(committed[j] + bet, self.wins(belief[j] * p[:, k]))],
                                         others, dead, stack - cost) - cost
                    bets_ev += weight * max(0., called - reserve * cost * (cost >= 30))
                keep *= float(marginal[0])
                entries.append((committed[j], self.wins(belief[j] * p[:, 0])))
            passive = keep * self.branch(hero_total, entries, [], dead, stack) + bets_ev
        # ---- bets and raises
        best_raise, best_ev, best_called = None, -1e9, 1.
        strength = float(np.mean(np.prod([win_now[i] for i in opps], axis=0)))
        if s.can_raise:
            base = pot + t
            fractions = (.33, .6, 1., 1.6) if t == 0 else (.6, 1.)
            targets = set()
            for f in fractions:
                target = int(s.street_bets[seat] + t + max(2, round(f * base)))
                target = max(s.min_raise_to, min(s.max_raise_to, target))
                if target >= .75 * s.max_raise_to:
                    target = s.max_raise_to
                targets.add(target)
            if s.max_raise_to - s.street_bets[seat] - t <= 2.5 * base:
                targets.add(s.max_raise_to)
            for target in sorted(targets):
                x = target - s.street_bets[seat]
                total = committed[seat] + x
                fixed = [(committed[i], win_now[i]) for i in opps if tb.stack[i] == 0]
                responders = [i for i in opps if tb.stack[i] > 0]
                can_reraise = x < stack or len(responders) > 1
                options, raisers, no_raise = [], [], 1.
                for i in responders:
                    y = min(tb.stack[i], target - s.street_bets[i])
                    p = respond(i, pot + x, y, tb.raises + 1, False)
                    b = belief[i]
                    if can_reraise and y < tb.stack[i]:
                        stay, up = b * p[:, 1], b * (p[:, 2] + p[:, 3])
                    else:
                        stay, up = b * (p[:, 1] + p[:, 2] + p[:, 3]), None
                    fold_mass, stay_mass = float(b @ p[:, 0]), float(stay.sum())
                    up_mass = float(up.sum()) if up is not None else 0.
                    stays = 1. - self.p['fold_trust'] * fold_mass / max(1e-9, stay_mass + fold_mass)
                    options.append((stays, committed[i] + y, self.wins(stay), committed[i]))
                    no_raise *= 1. - up_mass
                    if up_mass > 1e-3:
                        raisers.append((up_mass, i, up, y))
                if len(options) > 3:
                    options = sorted(options, key=lambda o: -o[0])[:3]
                quiet = self.branch(total, fixed, options, dead, stack - x) - x
                ev = quiet
                if raisers:
                    _, j, up, y = max(raisers, key=lambda r: r[0])
                    their_bet = min(tb.stack[j] - y, round(self.raise_size * (pot + x + y)))
                    extra = min(their_bet, stack - x)
                    others = [committed[i] for i in opps if i != j and tb.stack[i] > 0]
                    called = self.branch(total + extra, fixed + [(committed[j] + y + their_bet, self.wins(up))], [],
                                         dead + others, stack - x - extra) - x - extra
                    ev = no_raise * quiet + (1. - no_raise) * max(-float(x), called)
                called_eq = float(np.mean(np.prod([o[2] for o in options], axis=0))) if options else 1.
                size = (x - t) / max(1., base)
                # Model error is largest for big bets: large sizes need real strength.
                if size > self.p['semi_cap'] and strength < .8 and stack > 1.2 * base:
                    continue
                if called_eq < .3 and (size > self.p['bluff_cap'] or len(responders) > 1):
                    continue
                reserve = self.p['raise_reserve'] * x + .5 + (self.p['bluff_reserve'] * x if called_eq < .4 else 0.)
                if ev - reserve > best_ev:
                    best_raise, best_ev, best_called = target, ev - reserve, called_eq
        fold_ev = 0. if t else -1e9
        call_ev = passive - (reserve * t if t >= 30 else 0.)
        self.debug = dict(passive=passive, raise_ev=best_ev, target=best_raise, called=best_called)
        if best_raise is not None and best_ev > max(call_ev, fold_ev):
            return s.raise_to(int(best_raise))
        if t == 0:
            return s.check()
        return s.call() if call_ev > 0. or nuts else s.fold()

    # ------------------------------------------------------------ entry point
    def lite(self, s, hole, board):
        """Clock-starved fallback: no model inference."""
        t = min(s.to_call, s.my_stack)
        if not t:
            return s.check()
        if not board:
            hi, lo = sorted((c % 13 for c in hole), reverse=True)
            return s.call() if (hi == lo and hi >= 10) or (hi == 12 and lo >= 11) else s.fold()
        if s.clock_ms < 150:
            return s.fold()
        v, alive = core.grid(board)
        alive = alive[0] & ~(core.HAS[hole[0]] | core.HAS[hole[1]])
        mine = v[0, int(core.CIDX[hole[0], hole[1]])]
        share = float((((mine > v[0]) + .5 * (mine == v[0])) * alive).sum() / alive.sum())
        share **= max(1, s.players_in_hand - 1)
        return s.call() if share > .8 and share > t / max(1, s.pot + t) + .2 else s.fold()

    def act(self, s):
        try:
            hole, board = parse_cards(s.hole), parse_cards(s.board)
            if s.clock_ms < 2500:
                return self.legal(s, self.lite(s, hole, board))
            self.sync(s, hole, board)
            return self.legal(s, self.preflop(s, hole) if not board else self.postflop(s, hole, board))
        except Exception as error:   # never crash a game: a crash check-folds the rest
            self.errors += 1
            print('belief-search error:', repr(error), file=sys.stderr)
            return s.check() if not s.to_call else s.fold()



class TableCandidate(BeliefSearch):
    def __init__(self):
        super().__init__()
        self.chart = np.load(os.path.join(os.path.dirname(__file__), 'open_chart.npz'), allow_pickle=False)['chart']

    def preflop(self, s, hole):
        tb = self.tb
        # Limit this ablation to first-in full-stack 4/5/6-player opens.
        if (4 <= s.num_players <= 6 and tb.raises == 0 and tb.limpers == 0
                and sum(tb.committed) == 3 and s.my_stack + tb.committed[s.seat] == 200
                and tb.blind[s.seat] != 2 and s.can_raise):
            cls = int(core.CLS[core.CIDX[hole[0], hole[1]]])
            behind = max(1, min(4, tb.behind(s.seat) - 1))
            if self.chart[behind, cls]:
                return self.legal_raise(s, 6 if tb.blind[s.seat] == 1 else 5)
            return s.fold() if s.to_call else s.check()
        return super().preflop(s, hole)

bot = TableCandidate()

