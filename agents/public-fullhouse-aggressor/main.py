"""MAC adapter for Fullhouse Aggressor; see upstream.py and LICENSE."""
from macpoker import Bot
from upstream import decide
from common import legal_raise

class Agent(Bot):
    def act(self,s):
        result=decide({'your_stack':s.my_stack,'pot':s.pot,'min_raise_to':s.min_raise_to,'your_bet_this_street':s.street_bets[s.seat],'can_check':s.to_call==0})
        if result['action']=='raise':
            return legal_raise(s,result['amount'])
        return s.check() if s.to_call==0 else s.call()
