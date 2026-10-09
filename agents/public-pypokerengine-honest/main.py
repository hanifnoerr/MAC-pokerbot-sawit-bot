"""Port of ishikota/PyPokerEngine HonestPlayer, with clock-bounded equity."""
from macpoker import Bot
from common import equity

class Agent(Bot):
    def act(self,s):
        win_rate=equity(s,simulations=1000,players=s.num_players,ties_as_win=True)
        return s.call() if win_rate>=1/s.num_players else s.fold()
