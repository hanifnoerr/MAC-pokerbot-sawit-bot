"""Adapted from tamlhp/deepbot-poker (cyril), Apache-2.0; see ADAPTATION.md."""
from macpoker import Bot as BaseBot
from common import legal_raise


class ManiacBot(BaseBot):
    def act(self, state):
        raised = any(street == state.street and kind == 'raise' for street, _, kind, _ in state.history)
        call_total = state.street_bets[state.seat] + state.to_call
        return legal_raise(state, call_total + (2 if raised else 1) * state.pot)
