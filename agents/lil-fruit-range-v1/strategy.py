"""Public-information risk layer; standard library and NumPy only."""
import numpy as np
from macpoker.cards import parse_cards
from core import LilFruit, Policy, values, preflop


class RiskLayer:
    def on_hand_start(self, info):
        super().on_hand_start(info)
        self.starting_stacks = list(info.get('stacks', []))
        self.equity_cache = {}

    def contributions(self, s):
        start = getattr(self, 'starting_stacks', [])
        if len(start) == s.num_players:
            return [max(0, a-b) for a,b in zip(start,s.stacks)]
        # Reconstruct from public deltas if no hand-start callback is available.
        bets = [0]*s.num_players
        totals = [0]*s.num_players
        sb = s.button if s.num_players == 2 else (s.button+1)%s.num_players
        bb = (s.button+(1 if s.num_players == 2 else 2))%s.num_players
        totals[sb] = bets[sb] = 1
        totals[bb] = bets[bb] = 2
        street = 'preflop'
        for st,seat,kind,amount in s.history:
            if st != street:
                street = st
                bets = [0]*s.num_players
            delta = max(0,amount-bets[seat]) if kind == 'raise' else amount if kind == 'call' else 0
            totals[seat] += delta
            bets[seat] += delta
        return totals

    def layers(self, s):
        contributions = self.contributions(s)
        contributions[s.seat] += min(s.to_call,s.my_stack)
        cap = contributions[s.seat]
        clipped = [min(c,cap) for c in contributions]
        previous = 0
        layers = []
        for level in sorted(set(clipped)-{0}):
            amount = sum(min(c,level)-min(c,previous) for c in clipped)
            opponents = [i for i,c in enumerate(contributions)
                         if i != s.seat and not s.folded[i] and c >= level]
            layers.append((amount,opponents))
            previous = level
        return layers

    def eligible_pot(self, s):
        return sum(amount for amount,_ in self.layers(s))

    def maniac(self, s):
        # Requires observations; an unseen shove is not automatically a bluff.
        raisers = {a[1] for a in s.history if a[2] == 'raise' and a[1] != s.seat and not s.folded[a[1]]}
        return bool(raisers) and all(
            self.stats[s.players[i]][3] >= 12 and
            self.tendencies(s.players[i])[0] > .55 and
            self.tendencies(s.players[i])[1] > .50 for i in raisers)

    def preflop_allowed(self, s, hole):
        if not s.to_call:
            return True
        hi,lo = sorted((c%13 for c in hole),reverse=True)
        suited = hole[0]//13 == hole[1]//13
        pair = hi == lo
        power = float(preflop(np.array([hole]))[0])
        raises = sum(st == 'preflop' and kind == 'raise' for st,_,kind,_ in s.history)
        cost = min(s.to_call,s.my_stack)
        if self.maniac(s):
            return True  # Still subject to range equity and the call-price check.
        if cost >= 40 or (cost >= 12 and cost >= .5*s.my_stack):
            return (pair and hi >= 8) or (hi == 12 and lo >= 10) or (suited and hi == 12 and lo >= 9)
        if raises >= 2 and cost >= 8:
            return power >= .67 or (pair and hi >= 6)
        if raises and cost >= 5:
            return power >= (.55 if s.num_players <= 3 else .59) or (pair and cost <= 10)
        return True

    def estimate(self, s, hole, board):
        # Equity is expected payout / eligible pot, including unequal side pots.
        # Policy.encode may ask using suit-canonical cards. Always sample in the
        # actual visible-card coordinates so its call and guard share one cache.
        hole,board = parse_cards(s.hole),parse_cards(s.board)
        key = (tuple(hole),tuple(board),tuple(tuple(a) for a in s.history),
               tuple(s.folded),tuple(s.stacks),s.to_call)
        cache = getattr(self,'equity_cache',None)
        if cache is None:
            cache = self.equity_cache = {}
        if key in cache:
            return cache[key]
        layers = self.layers(s)
        total = sum(amount for amount,_ in layers)
        opponents = [i for i in range(s.num_players) if i != s.seat and not s.folded[i]]
        if not opponents:
            return 1.
        deck,combos,feats = self.features(hole,board)
        probs = [self.range_weights(s,combos,feats,i) for i in opponents]
        if len(board) == 5 and len(opponents) == 1:
            own = values(np.array([hole+board]))[0]
            other = values(np.column_stack((combos,np.tile(board,(len(combos),1)))))
            share = float(np.dot(probs[0],(own > other)+.5*(own == other)))
            result = sum(amount*(share if rivals else 1.) for amount,rivals in layers)/max(1,total)
            cache[key] = result
            return result
        count = 384 if s.clock_ms >= 3000 else 96
        used = np.zeros((count,52),dtype=bool)
        used[:,hole+board] = True
        rows = np.arange(count)
        chosen = []
        for p in probs:
            hands = combos[self.rng.choice(len(combos),count,p=p)]
            for _ in range(24):
                conflict = used[rows,hands[:,0]] | used[rows,hands[:,1]]
                if not conflict.any():
                    break
                hands[conflict] = combos[self.rng.choice(len(combos),int(conflict.sum()),p=p)]
            conflict = used[rows,hands[:,0]] | used[rows,hands[:,1]]
            for row in np.flatnonzero(conflict):
                valid = ~used[row,combos[:,0]] & ~used[row,combos[:,1]]
                weights = p*valid
                hands[row] = combos[self.rng.choice(len(combos),p=weights/weights.sum())]
            used[rows,hands[:,0]] = used[rows,hands[:,1]] = True
            chosen.append(hands)
        if len(board) < 5:
            keys = self.rng.random((count,52))
            keys[used] = 2
            future = np.argsort(keys,axis=1)[:,:5-len(board)]
            final = np.column_stack((np.tile(board,(count,1)),future))
        else:
            final = np.tile(board,(count,1))
        own = values(np.column_stack((np.tile(hole,(count,1)),final)))
        others = {seat:values(np.column_stack((hands,final))) for seat,hands in zip(opponents,chosen)}
        payout = 0.
        for amount,rivals in layers:
            if not rivals:
                share = 1.
            else:
                scores = np.array([others[i] for i in rivals])
                share = float(np.mean((own >= scores).all(axis=0)/(1+(own == scores).sum(axis=0))))
            payout += amount*share
        result = payout/max(1,total)
        cache[key] = result
        return result

    def guard(self, s, action):
        if action.kind in ('fold','check'):
            return action
        hole,board = parse_cards(s.hole),parse_cards(s.board)
        fallback = s.fold() if s.to_call else s.check()
        if not board and not self.preflop_allowed(s,hole):
            return fallback
        if not board and not any(a[2] == 'raise' for a in s.history):
            late = (s.seat-s.button)%s.num_players in (0,s.num_players-1)
            threshold = .41 if s.num_players == 2 else .52 if late else .58
            if float(preflop(np.array([hole]))[0]) < threshold:
                return fallback
        eq = self.estimate(s,hole,board)
        cost = min(s.to_call,s.my_stack)
        required = cost/max(1,self.eligible_pot(s))
        active = s.players_in_hand-1
        # A modest sampling/range margin; cheap draws can still call.
        margin = 0 if len(board) == 5 else .035 + .01*(active > 1)
        category = int(values(np.array([hole+board]))[0]//15**5) if board else 0
        if board and cost >= 40 and category <= 1 and not self.maniac(s):
            # Large one-pair bluff catches need room for range-model error, not
            # just enough raw equity against a permissive bluff likelihood.
            margin = max(margin,.10 + .02*(active > 1))
        if cost and eq < required+margin:
            return fallback
        if action.kind != 'raise':
            return action
        if not s.can_raise:
            return s.call() if cost else s.check()
        if board:
            # Betting second pair into multiple callers requires exceptional
            # range equity. Board-only strength and counterfeit pairs get no pass.
            threshold = (.68 if active == 1 else .76) if not cost else .83
            if eq < threshold or (active > 1 and category <= 1 and eq < .86):
                return s.call() if cost else s.check()
            if category <= 2:
                amount = s.street_bets[s.seat]+cost+int(.45*(s.pot+cost))
                # When the minimum legal raise exceeds the risk budget, don't
                # clamp upward into an unintended oversized bet.
                if amount < s.min_raise_to:
                    return s.call() if cost else s.check()
                return s.raise_to(min(action.amount,amount,s.max_raise_to))
        return s.raise_to(max(s.min_raise_to,min(action.amount,s.max_raise_to)))

    def safe_emergency(self, s):
        if not s.to_call:
            return s.check()
        hole,board = parse_cards(s.hole),parse_cards(s.board)
        if not board:
            return s.call() if self.preflop_allowed(s,hole) and float(preflop(np.array([hole]))[0]) >= .88 else s.fold()
        # Preserve exact river board ties and unbeatable hands within the clock.
        if len(board) == 5:
            own = values(np.array([hole+board]))[0]
            deck = [c for c in range(52) if c not in hole+board]
            combos = np.array([(a,b) for j,a in enumerate(deck) for b in deck[j+1:]])
            other = values(np.column_stack((combos,np.tile(board,(len(combos),1)))))
            if own >= other.max():
                ties_possible = bool(np.any(other == own))
                payout = sum(amount/(1+len(rivals)) if ties_possible else amount
                             for amount,rivals in self.layers(s))
                if min(s.to_call,s.my_stack) <= payout:
                    return s.call()
        return s.fold()


class RangeBot(RiskLayer,LilFruit):
    name = 'lil fruit range risk v1'

    def act(self,s):
        if s.clock_ms < 600:
            return self.safe_emergency(s)
        hole = parse_cards(s.hole)
        if not s.board and not self.preflop_allowed(s,hole):
            return s.fold() if s.to_call else s.check()
        return self.guard(s,LilFruit.act(self,s))


class HybridBot(RiskLayer,Policy):
    name = 'lil fruit guarded 956k v1'

    def act(self,s):
        if s.clock_ms < 600:
            return self.safe_emergency(s)
        # Never feed an unsupported table into the five-opponent encoder.
        if s.num_players > 6:
            return RangeBot.act(self,s)
        hole = parse_cards(s.hole)
        if not s.board and not self.preflop_allowed(s,hole):
            return s.fold() if s.to_call else s.check()
        return self.guard(s,Policy.act(self,s))
