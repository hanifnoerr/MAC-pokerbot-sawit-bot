"""Local adaptation helpers. No private engine state or deck seeds are consumed."""
from collections import Counter
import hashlib
import random
from macpoker.cards import parse_cards

def legal_raise(state, total):
    if not state.can_raise:
        return state.call() if state.to_call else state.check()
    return state.raise_to(max(state.min_raise_to, min(state.max_raise_to, int(total))))

def straight(ranks):
    mask = sum(1 << r for r in set(ranks))
    for high in range(12, 3, -1):
        if mask & (31 << (high-4)) == 31 << (high-4):
            return high
    if mask & 4111 == 4111:
        return 3
    return -1

def evaluate(cards):
    """Direct 5–7 card ranking, checked against macpoker's combinatorial evaluator."""
    ranks=[c%13 for c in cards]
    counts=Counter(ranks)
    groups=sorted(((n,r) for r,n in counts.items()),reverse=True)
    suits=[[] for _ in range(4)]
    for card in cards:
        suits[card//13].append(card%13)
    flush=next((sorted(s,reverse=True) for s in suits if len(s)>=5),None)
    if flush:
        high=straight(flush)
        if high>=0:
            return (8,high)
    if groups[0][0]==4:
        q=groups[0][1]
        return (7,q,max(r for r in ranks if r!=q))
    trips=sorted((r for r,n in counts.items() if n>=3),reverse=True)
    if trips:
        pairs=sorted((r for r,n in counts.items() if n>=2 and r!=trips[0]),reverse=True)
        if pairs:
            return (6,trips[0],pairs[0])
    if flush:
        return (5,*flush[:5])
    high=straight(ranks)
    if high>=0:
        return (4,high)
    if trips:
        return (3,trips[0],*sorted((r for r in ranks if r!=trips[0]),reverse=True)[:2])
    pairs=sorted((r for r,n in counts.items() if n==2),reverse=True)
    if len(pairs)>=2:
        return (2,*pairs[:2],max(r for r in ranks if r not in pairs[:2]))
    if pairs:
        return (1,pairs[0],*sorted((r for r in ranks if r!=pairs[0]),reverse=True)[:3])
    return (0,*sorted(ranks,reverse=True)[:5])

def category(state):
    if len(state.board)<3:
        return 1 if state.hole[0][0]==state.hole[1][0] else 0
    return evaluate(parse_cards(state.hole+state.board))[0]

def equity(state, simulations=100, players=None, ties_as_win=False):
    """Random-opponent equity; 128-sample cap for the competition clock.

    Seed depends only on information already visible to this agent.
    players overrides active-player count for sources using table-size equity.
    """
    n=max(2, players or state.players_in_hand)
    count=max(16,min(128,int(simulations)))
    hole=parse_cards(state.hole)
    board=parse_cards(state.board)
    seen=set(hole+board)
    deck=[c for c in range(52) if c not in seen]
    seed=hashlib.sha256(repr((state.hole,state.board,state.hand,n)).encode()).digest()
    rng=random.Random(seed)
    score=0.
    missing=5-len(board)
    for _ in range(count):
        sample=rng.sample(deck,missing+2*(n-1))
        community=board+sample[:missing]
        hero=evaluate(hole+community)
        values=[evaluate(sample[missing+2*i:missing+2*i+2]+community) for i in range(n-1)]
        if all(hero>=v for v in values):
            score+=1 if ties_as_win else 1/(1+sum(hero==v for v in values))
    return score/count
