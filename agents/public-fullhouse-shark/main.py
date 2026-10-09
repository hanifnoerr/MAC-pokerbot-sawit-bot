"""MAC adapter for Fullhouse Shark; original rank/position heuristics retained."""
from macpoker import Bot
from upstream import decide
from common import legal_raise

class Agent(Bot):
    def act(self,s):
        result=decide({'street':s.street,'amount_owed':s.to_call,'pot':s.pot,'your_stack':s.my_stack,'seat_to_act':s.seat,'players':s.players,'your_cards':s.hole,'min_raise_to':s.min_raise_to,'your_bet_this_street':s.street_bets[s.seat],'can_check':s.to_call==0})
        if result['action']=='raise':
            return legal_raise(s,result['amount'])
        return {'check':s.check,'call':s.call,'fold':s.fold}[result['action']]()
