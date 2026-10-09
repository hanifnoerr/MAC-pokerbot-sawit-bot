"""Adapted from tamlhp/deepbot-poker (cyril), Apache-2.0; see ADAPTATION.md."""
from macpoker import Bot as BaseBot
from common import equity, legal_raise


class EquityBot(BaseBot):
    def act(self, state):
        win_rate = equity(state, simulations=100)
        n = state.players_in_hand
        call_total = state.street_bets[state.seat] + state.to_call
        if win_rate > 1.6 / n:
            return legal_raise(state, call_total + 2 * state.pot)
        if win_rate > 1.4 / n:
            return legal_raise(state, call_total + state.pot)
        if win_rate > 1.2 / n:
            return legal_raise(state, state.min_raise_to)
        if win_rate > 1 / n:
            return state.call()
        return state.check() if state.to_call == 0 else state.fold()
