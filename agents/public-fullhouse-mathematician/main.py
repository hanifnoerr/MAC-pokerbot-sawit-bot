"""MAC adapter for Fullhouse Mathematician; see upstream.py and LICENSE."""
from macpoker import Bot
from upstream import decide

class Agent(Bot):
    def act(self,s):
        result=decide({'amount_owed':s.to_call,'pot':s.pot,'your_stack':s.my_stack,'can_check':s.to_call==0})
        return {'check':s.check,'call':s.call,'fold':s.fold}[result['action']]()
