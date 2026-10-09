"""Adapted from tamlhp/deepbot-poker (cyril), Apache-2.0; see ADAPTATION.md."""
from macpoker import Bot as BaseBot
from macpoker.cards import parse_card, card_rank


class ConservativeBot(BaseBot):
    def act(self, state):
        high, low = sorted((card_rank(parse_card(c)) + 2 for c in state.hole), reverse=True)
        return state.call() if high >= 13 and low >= 11 else state.fold()
