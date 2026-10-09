"""Adapted from tamlhp/deepbot-poker (cyril), Apache-2.0; see ADAPTATION.md."""
from macpoker import Bot as BaseBot
from common import equity, legal_raise


class CandidBot(BaseBot):
    def on_match_start(self, info):
        self.initial_stack = info['stack']
        self.big_blind = info['blinds'][1]

    def act(self, state):
        y = equity(state, simulations=100) ** 7 * self.initial_stack + state.street_bets[state.seat]
        call_total = state.street_bets[state.seat] + state.to_call
        minimum = state.min_raise_to if state.can_raise else float('inf')
        raised_twice = sum(street == state.street and kind == 'raise' for street, _, kind, _ in state.history) >= 2
        if y < call_total:
            return state.check() if state.to_call == 0 else state.fold()
        if y < minimum or (raised_twice and y < (2 / 3) * self.initial_stack):
            return state.call()
        if y > (2 / 3) * self.initial_stack:
            return legal_raise(state, state.max_raise_to)
        return legal_raise(state, self.big_blind * round(y / self.big_blind))
