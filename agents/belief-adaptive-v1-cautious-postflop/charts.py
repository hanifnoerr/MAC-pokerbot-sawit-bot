"""Original adapter for static, source-labelled solver preflop frequencies."""
import json
import math
import os
import numpy as np
import core
from base import BeliefSearch

POST_ORDER = {'SB':0,'BB':1,'LJ':2,'HJ':3,'CO':4,'BTN':5}

def position(n, button, seat):
    offset=(seat-button)%n
    if offset<3:
        return ('BTN','SB','BB')[offset]
    return ('LJ','HJ','CO')[-(n-3):][offset-3]

def raise_target(depth, hero, villain=None, previous=0):
    if depth==0:
        return 6 if hero=='SB' else 5
    ip=POST_ORDER[hero]>POST_ORDER[villain]
    if depth==1:
        return min(200,max(14,previous*(3 if ip else 5)))
    if depth==2:
        # The source sizing profile rounds the four-bet in big blinds.
        return min(200,2*math.floor(previous/2*(2 if ip else 2.5)+.5))
    return 200

class SolverCharts(BeliefSearch):
    name='Invoker chart candidate'

    def __init__(self):
        super().__init__()
        with open(os.path.join(os.path.dirname(__file__),'ranges.json'),encoding='utf8') as f:
            self.charts=json.load(f)
        self.chart_rng=np.random.default_rng(571937)
        self.chart_hits=0
        self.chart_fallbacks=0

    def lookup(self,s,hole):
        """Return conditional (raise, call, fold) and target, or no chart.

        Unsolved limps, cold calls, squeezes, sizes, stacks and table sizes
        retain the baseline. Mapping shorter tables onto later six-max seats
        is an explicit approximation, not an independently solved strategy.
        """
        n=s.num_players
        if n not in (4,5,6) or s.street!='preflop':
            return None
        if any(s.stacks[i]+self.tb.committed[i]!=200 for i in range(n)):
            return None
        if s.pot!=sum(self.tb.committed) or s.pot<3:
            return None
        raises=[];acted=set()
        for street,seat,kind,amount in s.history:
            if street!='preflop' or kind not in ('fold','raise'):
                return None
            if kind=='raise':
                depth=len(raises)
                if depth>=4:
                    return None
                if depth>=2 and seat!=raises[-2][0]:
                    return None
                hp=position(n,s.button,seat)
                vp=position(n,s.button,raises[-1][0]) if depth else None
                previous=raises[-1][1] if depth else 0
                if amount!=raise_target(depth,hp,vp,previous):
                    return None
                raises.append((seat,amount))
            acted.add(seat)
        hero=position(n,s.button,s.seat)
        depth=len(raises)
        if depth==0:
            if s.seat in acted or hero=='BB':
                return None
            keys=('Open'+hero,'Limp'+hero)
            arrival=None
            target=raise_target(0,hero)
        else:
            villain=position(n,s.button,raises[-1][0])
            if raises[-1][0]==s.seat or (depth==1 and s.seat in acted):
                return None
            if depth>=2 and s.seat!=raises[-2][0]:
                return None
            suffix=hero+'vs'+villain
            if depth==1:
                keys=('3Bet'+suffix,'Call'+suffix);arrival=None
            elif depth==2:
                keys=('4Bet'+suffix,'Call 3Bet'+suffix);arrival='Open'+hero
            elif depth==3:
                keys=('5Bet'+suffix,'Call 4Bet'+suffix);arrival='3Bet'+suffix
            else:
                keys=(None,'Call 5Bet'+suffix);arrival='4Bet'+suffix
            target=raise_target(depth,hero,villain,raises[-1][1])
        ranks='23456789TJQKA'
        hi,lo=sorted((int(c)%13 for c in hole),reverse=True)
        hand=ranks[hi]+ranks[lo]+('' if hi==lo else 's' if hole[0]//13==hole[1]//13 else 'o')
        if any(k is not None and (k not in self.charts or hand not in self.charts[k]) for k in (*keys,arrival)):
            return None
        reach=self.charts[arrival][hand] if arrival else 1.
        if reach<=1e-9:
            return None
        r=self.charts[keys[0]][hand]/reach if keys[0] else 0.
        c=self.charts[keys[1]][hand]/reach
        # Reject inconsistent source nodes instead of turning them into policy.
        if not np.isfinite([r,c]).all() or min(r,c)<0 or r+c>1.00001:
            return None
        r=min(1.,r);c=min(1.-r,c)
        if r>0 and (not s.can_raise or not s.min_raise_to<=target<=s.max_raise_to):
            return None
        return (r,c,1.-r-c),target

    def preflop(self,s,hole):
        choice=self.lookup(s,hole)
        if choice is None:
            self.chart_fallbacks+=1
            return super().preflop(s,hole)
        self.chart_hits+=1
        (r,c,_),target=choice
        u=self.chart_rng.random()
        if u<r:
            return s.raise_to(int(target))
        if u<r+c:
            return s.call() if s.to_call else s.check()
        return s.fold() if s.to_call else s.check()


