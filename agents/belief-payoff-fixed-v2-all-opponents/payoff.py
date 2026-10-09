"""Tie-aware marginal-range payoff with conditional runout weighting.

Opponent ranges remain factorized: cross-opponent card collisions are not
jointly enumerated. All supplied opponents and their contributions are kept.
"""
import itertools
import numpy as np

_QUADRATURE={}
for _n in range(1,9):
    _x,_w=np.polynomial.legendre.leggauss((_n+2)//2)
    _QUADRATURE[_n]=((_x+1)/2,_w/2)


class Payoff:
    def wins(self,b):
        den=self.A@b
        safe=np.maximum(den,1e-200)
        tie=(self.T@b)/safe
        win=np.maximum(0.,(self.W@b)/safe-.5*tie)
        # Relative likelihood of this runout under the conditional range.
        mass=den/max(float(np.mean(den)),1e-200)
        return (win,tie,mass)

    @staticmethod
    def share(ranges):
        """Probability hero wins divided by the number sharing each tie."""
        if not ranges:return np.ones(1)
        # Integral_0^1 product(win + x*tie) dx equals the tie polynomial
        # sum coefficient[k]/(k+1). Gaussian quadrature integrates this
        # degree<=8 polynomial exactly, with fewer array operations.
        nodes,weights=_QUADRATURE[len(ranges)]
        terms=np.ones((len(nodes),len(ranges[0][0])))
        for win,tie,_ in ranges:terms*=win[None,:]+nodes[:,None]*tie[None,:]
        return weights@terms

    @staticmethod
    def average(values,ranges):
        mass=np.ones_like(np.asarray(values,dtype=float))
        for _,_,m in ranges:mass=mass*m
        total=float(np.sum(mass))
        return float(np.sum(values*mass)/total) if total>1e-200 else 0.

    def equity_share(self,ranges):
        return self.average(self.share(ranges),ranges)

    def settle(self,hero_total,entries,dead):
        levels=sorted({min(t,hero_total) for t,_ in entries}|{hero_total})
        everyone=[hero_total]+[t for t,_ in entries]+dead
        out,previous=0.,0.
        for level in levels:
            if level<=previous:continue
            amount=sum(min(c,level)-min(c,previous) for c in everyone)
            ranges=[w for total,w in entries if total>=level]
            out=out+amount*self.share(ranges)
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
