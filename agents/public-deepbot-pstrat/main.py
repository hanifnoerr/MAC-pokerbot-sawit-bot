"""Adapted from tamlhp/deepbot-poker (cyril), Apache-2.0; see ADAPTATION.md."""
from collections import Counter
from macpoker import Bot as BaseBot
from macpoker.cards import parse_card, card_rank, card_suit
from common import category, legal_raise


class PStratBot(BaseBot):
    def on_match_start(self, info):
        self.big_blind = info['blinds'][1]

    def position(self, state, seat):
        sb = state.button if state.num_players == 2 else (state.button + 1) % state.num_players
        relative = (seat - sb) % state.num_players
        if relative <= 1:
            return 'blinds'
        if relative >= state.num_players - 2:
            return 'late'
        if relative >= state.num_players - 5:
            return 'middle'
        return 'early'

    def hand_in_range(self, highs, lows, suited=False, pocket=False):
        ranks = {r: i + 2 for i, r in enumerate('23456789TJQKA')}
        high, low = self.ranks
        if pocket:
            return high == low and ranks[lows[0]] <= high <= ranks[highs[0]]
        if suited and self.suits[0] != self.suits[1]:
            return False
        return any(high == ranks[a] and ranks[b] <= low < ranks[a] for a, b in zip(highs, lows))

    def strong_draw(self, state):
        cards = [parse_card(c) for c in state.hole + state.board]
        suits = Counter(card_suit(c) for c in cards)
        # Preserve upstream's ineffective integer-rank versus 'A'/'K' comparison.
        flush = self.suits[0] == self.suits[1] and suits[self.suits[0]] >= 4
        ranks = set(card_rank(c) + 2 for c in cards) - {14}
        middle = sorted(r for r in ranks if r - 1 in ranks and r + 1 in ranks)
        straight = len(middle) >= 2 and middle[1] - middle[0] == 1
        return flush or straight

    def strategy(self, state, raises):
        h = self.hand_in_range
        pos = self.position(state, state.seat)
        bbs = state.my_stack / self.big_blind
        if bbs > 12:
            if state.street == 'preflop':
                if h('A', 'Q', pocket=True) or h('A', 'K'):
                    return 'pre_raise'
                if h('J', 'J', pocket=True):
                    return 'pre_fold' if pos in ('early', 'middle') else 'pre_raise'
                if h('T', '8', pocket=True) or h('A', 'Q'):
                    return 'fold' if pos == 'early' else 'pre_fold'
                if h('7', '7', pocket=True) or h('AK', 'TJ'):
                    return 'fold' if pos in ('early', 'middle') else 'pre_fold'
                return 'fold'
            cat = category(state)
            counts = Counter(card_rank(parse_card(c)) + 2 for c in state.hole + state.board)
            pairs = sorted((r for r, count in counts.items() if count >= 2), reverse=True)
            if cat >= 3:
                return 'post_raise'
            if cat == 2 and all(r in pairs[:2] for r in self.ranks) and self.ranks[0] >= pairs[0]:
                return 'post_raise'
            if cat == 1 and pairs[0] in self.ranks and pairs[0] >= max(card_rank(parse_card(c)) + 2 for c in state.board):
                return 'post_raise'
            if state.street in ('flop', 'turn') and self.strong_draw(state):
                return 'post_raise'
            return 'fold'
        shove = False
        if not raises:
            if pos in ('early', 'middle'):
                if 9 < bbs <= 12:
                    shove = h('A', 'Q') or h('A', 'T', suited=True) or h('A', '6', pocket=True)
                elif 5 < bbs <= 9:
                    shove = h('AKQJ', 'TTTT') or h('AKQJT9', '248778', suited=True) or h('A', '2', pocket=True)
                elif bbs < 5:
                    shove = h('AKQJ', '28TT') or h('AKQJT9876', '246766655', suited=True) or h('A', '2', pocket=True)
            else:
                shove = h('AKQJT', '24999') or h('AKQJT9876', '222766655', suited=True) or h('A', '2', pocket=True)
        else:
            raiser = raises[-1][1]
            raiser_pos = self.position(state, raiser)
            medium = 6 < state.stacks[raiser] / self.big_blind <= 12
            if raiser_pos == 'early':
                shove = h('A', 'Q') or h('A', 'T' if medium else '8', pocket=True)
            elif raiser_pos == 'middle':
                shove = h('A', '7', pocket=True) or h('A', 'Q' if medium else 'J')
            elif raiser_pos == 'late':
                shove = h('A', '5', pocket=True) or (h('AK', 'TQ') or h('AK', '7Q', suited=True) if medium else h('AKQ', '5TJ'))
            else:
                shove = h('A', '2', pocket=True) or (h('AK', '8Q') or h('AK', '2Q', suited=True) if medium else h('AKQJ', '2TJT'))
        return 'shove' if shove else 'fold'

    def act(self, state):
        hole = sorted((parse_card(c) for c in state.hole), key=card_rank, reverse=True)
        self.ranks = [card_rank(c) + 2 for c in hole]
        self.suits = [card_suit(c) for c in hole]
        history = [a for a in state.history if a[0] == state.street]
        raises = [a for a in history if a[2] == 'raise']
        strategy = self.strategy(state, raises)
        if strategy in ('pre_raise', 'pre_fold'):
            if not raises:
                calls = sum(a[2] in ('call', 'check') for a in history)
                return legal_raise(state, (3 + calls) * self.big_blind)
            if strategy == 'pre_raise':
                return legal_raise(state, 3 * raises[-1][3])
        elif strategy == 'post_raise':
            if not raises:
                return legal_raise(state, int((2 / 3) * state.pot))
            if len(raises) == 1:
                return legal_raise(state, 3 * raises[-1][3] + state.pot)
            return legal_raise(state, state.max_raise_to)
        elif strategy == 'shove':
            return legal_raise(state, state.max_raise_to)
        return state.check() if state.to_call == 0 else state.fold()
