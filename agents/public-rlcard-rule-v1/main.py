"""RLCard limit-holdem rule-v1 port; limit raises map to minimum NL raises."""
from macpoker import Bot
from upstream import LimitholdemRuleAgentV1
from common import legal_raise

class Agent(Bot):
    def act(self,s):
        legal=['fold','call' if s.to_call else 'check']
        if s.can_raise:
            legal.append('raise')
        convert=lambda c:c[1].upper()+c[0]
        result=LimitholdemRuleAgentV1.step({'raw_legal_actions':legal,'raw_obs':{'hand':list(map(convert,s.hole)),'public_cards':list(map(convert,s.board))}})
        if result=='raise':
            return legal_raise(s,s.min_raise_to)
        return {'fold':s.fold,'call':s.call,'check':s.check}[result]()
