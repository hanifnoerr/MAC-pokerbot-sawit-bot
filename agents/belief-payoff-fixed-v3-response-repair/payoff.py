"""Exact card exclusion for two opponents; factorized approximation for 3+.

Two-opponent equity conditions product ranges on distinct physical cards,
including the runout likelihood and blockers in unequal side pots. Larger
fields retain the bounded original approximation rather than a noisy sampler.
"""
import itertools
import numpy as np
import core

_CARD_INCIDENCE = core.HAS.astype(np.float64).T


class RangeResult(tuple):
    def __new__(cls, win, tie, mass, belief, den, token):
        obj = super().__new__(cls, (win, tie, mass))
        obj.belief = belief.copy()
        obj.den = den
        obj.token = token
        obj.cards = None
        return obj

_QUADRATURE={}
for _n in range(1,9):
    _x,_w=np.polynomial.legendre.leggauss((_n+2)//2)
    _QUADRATURE[_n]=((_x+1)/2,_w/2)


class Payoff:
    def _grid_cache(self):
        # Production assigns three fresh matrices per decision and never
        # mutates them during the search. Track all three for test fixtures.
        token=(self.A,self.W,self.T)
        old=getattr(self,'_grid_token',None)
        if old is None or any(a is not b for a,b in zip(old,token)):
            self._grid_token=token
            self._wins_cache={}
            self._pair_cache={}
            self._strict_win=self.W-.5*self.T

    def wins(self,b):
        self._grid_cache()
        b=np.asarray(b,dtype=np.float64)
        key=b.tobytes()
        if key in self._wins_cache:return self._wins_cache[key]
        den=self.A@b
        safe=np.maximum(den,1e-200)
        tie=(self.T@b)/safe
        win=np.maximum(0.,(self.W@b)/safe-.5*tie)
        # Relative likelihood of this runout under the conditional range.
        mass=den/max(float(np.mean(den)),1e-200)
        result=RangeResult(win,tie,mass,b,den,self.A)
        self._wins_cache[key]=result
        return result

    def _pair(self, first, second):
        # In larger actual fields the entire search remains factorized, even
        # in hypothetical branches where all but two opponents have folded.
        if not getattr(self,'joint_pair_enabled',True):return None
        if not (isinstance(first,RangeResult) and isinstance(second,RangeResult)):
            return None
        self._grid_cache()
        key=(id(first),id(second))
        if key in self._pair_cache:return self._pair_cache[key][2]
        reverse=(id(second),id(first))
        if reverse in self._pair_cache:
            result=self._pair_cache[reverse][2]
            return (result[0],result[1],result[3],result[2])
        if first.token is not self.A or second.token is not self.A:
            raise ValueError('Range belongs to a different equity grid')
        for r in (first,second):
            if r.cards is None:
                # Card marginal masses for all hands, strict wins, and ties.
                r.cards=tuple((matrix*r.belief)@_CARD_INCIDENCE
                    for matrix in (self.A,self._strict_win,self.T))
        a1,w1,t1=first.cards;a2,w2,t2=second.cards
        d1,d2=first.den,second.den
        sw1,st1=first[0]*d1,first[1]*d1
        sw2,st2=second[0]*d2,second[1]*d2
        same=first.belief*second.belief
        same_a=self.A@same
        same_t=self.T@same
        same_w=self.W@same-.5*same_t
        dot=lambda a,b:np.einsum('ij,ij->i',a,b)
        # Subtract every shared card, then add identical combos once: they
        # were subtracted twice and should be excluded only once.
        den=np.maximum(0.,d1*d2-dot(a1,a2)+same_a)
        num=(sw1*sw2-dot(w1,w2)+same_w
             +.5*(sw1*st2+st1*sw2-dot(w1,t2)-dot(t1,w2))
             +(st1*st2-dot(t1,t2)+same_t)/3.)
        one=(sw1+.5*st1)*d2-dot(w1+.5*t1,a2)+same_w+.5*same_t
        two=d1*(sw2+.5*st2)-dot(a1,w2+.5*t2)+same_w+.5*same_t
        safe=np.maximum(den,1e-200)
        result=(np.clip(num/safe,0.,1.),den,
                np.clip(one/safe,0.,1.),np.clip(two/safe,0.,1.))
        # Strong references also prevent range id reuse within the decision.
        self._pair_cache[key]=(first,second,result)
        return result

    def share(self,ranges):
        """Probability hero wins divided by the number sharing each tie."""
        if not ranges:return np.ones(1)
        if len(ranges)==2:
            pair=self._pair(*ranges)
            if pair is not None:return pair[0]
        # Integral_0^1 product(win + x*tie) dx equals the tie polynomial
        # sum coefficient[k]/(k+1). Gaussian quadrature integrates this
        # degree<=8 polynomial exactly, with fewer array operations.
        nodes,weights=_QUADRATURE[len(ranges)]
        terms=np.ones((len(nodes),len(ranges[0][0])))
        for win,tie,_ in ranges:terms*=win[None,:]+nodes[:,None]*tie[None,:]
        return weights@terms

    def average(self,values,ranges):
        mass=np.ones_like(np.asarray(values,dtype=float))
        pair=self._pair(*ranges) if len(ranges)==2 else None
        if pair is not None:mass=pair[1]
        else:
            for _,_,m in ranges:mass=mass*m
        total=float(np.sum(mass))
        return float(np.sum(values*mass)/total) if total>1e-200 else 0.

    def equity_share(self,ranges):
        return self.average(self.share(ranges),ranges)

    def settle(self,hero_total,entries,dead):
        levels=sorted({min(t,hero_total) for t,_ in entries}|{hero_total})
        everyone=[hero_total]+[t for t,_ in entries]+dead
        out,previous=0.,0.
        pair=self._pair(entries[0][1],entries[1][1]) if len(entries)==2 else None
        for level in levels:
            if level<=previous:continue
            amount=sum(min(c,level)-min(c,previous) for c in everyone)
            ranges=[w for total,w in entries if total>=level]
            if pair is not None and len(ranges)==1:
                eligible=0 if entries[0][0]>=level else 1
                share=pair[2+eligible]
            else:share=self.share(ranges)
            out=out+amount*share
            previous=level
        return out

    def branch(self,hero_total,must,optional,dead,room):
        value=0.
        for mask in itertools.product((0,1),repeat=len(optional)):
            p,entries,d=1.,list(must),list(dead)
            for bit,(q,tin,win,tout) in zip(mask,optional):
                if bit:p*=q;entries.append((tin,win))
                else:p*=1.-q;d.append(tout)
            if p<=0:continue
            ranges=[w for _,w in entries]
            ev=self.average(self.settle(hero_total,entries,d),ranges)
            if self.streets_left and entries and room>0:
                beat=self.share(ranges)
                pot=sum(min(c,hero_total) for c in [hero_total]+[t for t,_ in entries]+d)
                theirs=max(self.start_total-t for t,_ in entries)
                size=min(room,theirs,.7*self.streets_left*pot)
                if size>0:
                    gain=.7*np.maximum(beat-.5,0)*self.pos_gain-.3*np.maximum(.5-beat,0)*self.pos_loss
                    ev+=self.p['future']*size*self.average(gain,ranges)
            value+=p*ev
        return value
