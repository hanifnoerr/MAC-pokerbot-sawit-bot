"""Replay-conditioned local opponents. No competitor code or identity at inference."""
import numpy as np
from macpoker.cards import parse_cards
from strategy import InvokerStrategy, preflop, values


def features(hole,board,n,active,position,pot,cost,stack,raises):
    h=parse_cards(hole);b=parse_cards(board);hi,lo=sorted((c%13 for c in h),reverse=True)
    category=int(values(np.array([h+b]))[0])//15**5 if b else 0
    ranks=[c%13 for c in b];top=max(ranks,default=-1)
    flush=max((sum(c//13==s for c in h+b) for s in range(4)),default=0)
    return np.asarray([float(preflop(np.array([h]))[0]),hi/12,lo/12,hi==lo,h[0]//13==h[1]//13,
        n/9,active/9,position, min(3,pot/200),min(1,cost/200),cost/max(1,pot+cost),stack/200,
        min(3,raises)/3,category/8,any(c%13==top for c in h),flush/7,len(set(ranks))/5],np.float32)


SCALE=np.asarray([5,1,1,2,1,.4,1,.4,.5,3,3,1,1,5,1,1,1],np.float32)


def neighbours(x,can_raise,street,data):
    selected=np.flatnonzero((data['street']==street)&(data['can_raise']==can_raise)&((data['x'][:,9]>0)==(x[9]>0)))
    if len(selected)<8:return None,None
    distance=np.sum(((data['x'][selected]-x)*SCALE)**2,axis=1)
    take=np.argsort(distance)[:min(12,len(selected))]
    ids=selected[take];weights=np.exp(-(distance[take]-distance[take][0])/.18)
    return ids,weights/weights.sum()


class ReplayProxy(InvokerStrategy):
    def __init__(self,path,name):
        super().__init__();self.name=name
        self.data=dict(np.load(path,allow_pickle=False))

    def act(self,s):
        if s.clock_ms<600:return super().act(s)
        street=('preflop','flop','turn','river').index(s.street)
        x=features(s.hole,s.board,s.num_players,s.players_in_hand,(s.seat-s.button)%s.num_players/s.num_players,
            s.pot,min(s.to_call,s.my_stack),s.my_stack,sum(a[0]==s.street and a[2]=='raise' for a in s.history))
        ids,p=neighbours(x,s.can_raise,street,self.data)
        if ids is None:return super().act(s)
        row=int(self.rng.choice(ids,p=p));action=int(self.data['action'][row])
        if action==0:return s.fold() if s.to_call else s.check()
        if action==1 or not s.can_raise:return s.call() if s.to_call else s.check()
        if self.data['allin'][row]:target=s.max_raise_to
        else:target=s.street_bets[s.seat]+s.to_call+self.data['raise_fraction'][row]*(s.pot+s.to_call)
        return s.raise_to(max(s.min_raise_to,min(s.max_raise_to,int(round(target)))))
