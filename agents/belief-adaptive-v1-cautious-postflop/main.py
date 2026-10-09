"""Conservative, within-game public-action adaptation of the solver candidate."""
import numpy as np
import core
from base import STREETS
from charts import SolverCharts


def context_key(name, street, ctx):
    # Context is the same vector used by the population action model.
    price=float(ctx[3])
    price_bucket=0 if name=='unbet' or price<=.25 else 1 if price<=.40 else 2
    last=int(float(ctx[7])==0.)
    multi=int(float(ctx[6])>0.)
    return (name,street,price_bucket,last,multi)


class AdaptiveCharts(SolverCharts):
    name='Invoker adaptive candidate'

    def __init__(self):
        super().__init__()
        self.observed={}
        self.frozen={}
        self.hero_player=None
        self.adaptation_hits=0

    def on_match_start(self,info):
        super().on_match_start(info)
        # Explicit reset also supports a reused instance in local tests.
        self.observed={};self.frozen={};self.hero_player=None
        self.stats={};self.totals={};self.hands_seen=0
        self.hand_no=None;self.tb=None;self.pub=None;self.done=0
        self.feat={};self.belief={};self.adaptation_hits=0

    def on_hand_start(self,info):
        super().on_hand_start(info)
        players=info.get('players',[]);seat=info.get('seat',-1)
        self.hero_player=players[seat] if 0<=seat<len(players) else None
        # Use completed-hand evidence only. An action must not change the
        # likelihood model used to explain that very same action later.
        self.frozen={p:{k:v.copy() for k,v in rows.items()} for p,rows in self.observed.items()}

    def on_action(self,event):
        tb=self.pub;players=event.get('players') or [];seat=event.get('seat',-1)
        street=STREETS.get(event.get('street'),0)
        if tb is not None and 0<=seat<tb.n and len(players)==tb.n:
            tb.enter(street)
            player=players[seat]
            if street>0 and player!=self.hero_player:
                cost=tb.to_call(seat)
                name='facing' if cost>0 else 'unbet'
                kind=event.get('action');amount=event.get('amount',0)
                if kind in ('fold','check','call','raise'):
                    ctx=tb.post_ctx(seat,self.pub_board)
                    key=context_key(name,street-1,ctx)
                    fraction=(amount-max(tb.bets))/max(1,tb.pot+cost) if kind=='raise' else 0.
                    action=core.post_class(kind,fraction,cost>0)
                    rows=self.observed.setdefault(player,{})
                    rows.setdefault(key,np.zeros(4))[action]+=1
        super().on_action(event)

    def shift(self,player,name,bucket,ctx):
        rows=self.frozen.get(player,{})
        pooled=np.zeros(4);same_street=np.zeros(4)
        for key,values in rows.items():
            if key[0]==name:
                pooled+=values
                if key[1]==bucket:same_street+=values
        total=float(pooled.sum())
        if total<8:
            return None
        rate=np.maximum(self.rates[name][bucket],1e-6);rate=rate/rate.sum()
        # Hierarchical shrinkage: broad tendency, then street, then exact
        # price/position/multiway context. Sparse buckets stay near the prior.
        population=(pooled+40*rate)/(total+40)
        street_rate=(same_street+24*population)/(same_street.sum()+24)
        exact=rows.get(context_key(name,bucket,ctx),np.zeros(4))
        posterior=(exact+16*street_rate)/(exact.sum()+16)
        confidence=total/(total+24)
        return confidence*np.clip(np.log(posterior/rate),-np.log(2.),np.log(2.))

    def probs(self,name,bucket,player,x):
        if name=='pre' or not self.p['adapt']:
            return super().probs(name,bucket,player,x)
        shift=self.shift(player,name,bucket,x[0,4:])
        if shift is not None:self.adaptation_hits+=1
        # Retain hand-dependent likelihoods. Frequent aggression does not
        # establish bluffing, so never replace them with hand-independent bets.
        p=core.mlp(self.net[name],x,shift)
        tremble=self.p['tremble']
        return (1-tremble)*p+tremble*self.rates[name][bucket]


bot=AdaptiveCharts()
