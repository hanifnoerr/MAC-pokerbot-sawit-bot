import random
from macpoker import Bot
from macpoker.cards import parse_cards
from macpoker.evaluator import evaluate

STYLE = 'value'

class Opponent(Bot):
    def __init__(self):
        self.rng = random.Random(1703)

    def act(self, s):
        h = parse_cards(s.hole)
        ranks = sorted((c % 13 for c in h), reverse=True)
        pair = ranks[0] == ranks[1]
        suited = h[0] // 13 == h[1] // 13
        price = s.to_call / max(1, s.pot + s.to_call)
        free = s.check() if s.to_call == 0 else s.fold()
        def bet(fraction):
            if not s.can_raise:
                return s.call()
            total = s.street_bets[s.seat] + s.to_call + max(4, int(fraction * (s.pot + s.to_call)))
            return s.raise_to(max(s.min_raise_to, min(s.max_raise_to, total)))
        if s.street == 'preflop':
            premium = (pair and ranks[0] >= 9) or ranks[1] >= 10
            playable = pair or ranks[1] >= (7 if STYLE == 'pressure' else 9) or (suited and ranks[0] - ranks[1] <= 2)
            if premium:
                return bet(1 if STYLE != 'sticky' else .5)
            if playable and s.to_call <= (14 if STYLE == 'pressure' else 8):
                return bet(.6) if STYLE == 'pressure' and self.rng.random() < .35 else s.call()
            if STYLE == 'sticky' and s.to_call <= 4:
                return s.call()
            return free
        board = parse_cards(s.board)
        value = evaluate(h + board)
        own_pair = value[0] == 1 and value[1] in ranks
        top_pair = own_pair and value[1] >= max(c % 13 for c in board)
        strong = value[0] >= 3 or (value[0] == 2 and sum(r in [c % 13 for c in board] for r in ranks) == 2)
        if strong:
            return bet(.9)
        if top_pair:
            if s.to_call and price < (.42 if STYLE == 'sticky' else .32):
                return s.call()
            if not s.to_call:
                return bet(.5)
        if STYLE == 'sticky' and own_pair and price < .30:
            return s.call()
        if STYLE == 'pressure' and s.players_in_hand <= 3 and self.rng.random() < .30:
            return bet(.7)
        return free
