"""Card tables, a table-driven 5-7 card evaluator and public-state features.

Cards follow the SDK: int 0..51, rank = c % 13 (0 = deuce), suit = c // 13.
Every per-hand array is indexed by the fixed list of 1326 two-card combos, so
ranges, likelihoods and showdown matrices stay aligned across streets.
"""
import numpy as np

NC = 1326
_a, _b = np.triu_indices(52, 1)
C1 = _a.astype(np.int64)
C2 = _b.astype(np.int64)
CIDX = np.zeros((52, 52), np.int32)
CIDX[C1, C2] = np.arange(NC)
CIDX[C2, C1] = np.arange(NC)
HAS = np.zeros((52, NC), bool)
HAS[C1, np.arange(NC)] = True
HAS[C2, np.arange(NC)] = True

_R = np.arange(13)


def _top(mask, k):
    """Highest k ranks set in each row of a (M, 13) mask, -1 where missing."""
    v = np.where(mask, _R, -1)
    v.sort(axis=1)
    return v[:, ::-1][:, :k].T


def _pack(cat, *digits):
    out = np.full(len(digits[0]), cat, np.int64)
    for i in range(5):
        out = out * 14 + ((digits[i] + 1) if i < len(digits) else 0)
    return out


def _straights():
    m = np.arange(8192)
    out = np.full(8192, -1, np.int64)
    out[(m & 4111) == 4111] = 3
    for high in range(4, 13):
        pat = 31 << (high - 4)
        out[(m & pat) == pat] = high
    return out


def _nonflush(cnt):
    present = cnt > 0
    mask = (present * (1 << _R)).sum(1)
    val = _pack(0, *_top(present, 5))
    p = _top(cnt >= 2, 2)
    t = _top(cnt >= 3, 1)[0]
    q = _top(cnt == 4, 1)[0]
    val = np.where(p[0] >= 0, _pack(1, p[0], *_top(present & (_R != p[0][:, None]), 3)), val)
    kick = _top(present & (_R != p[0][:, None]) & (_R != p[1][:, None]), 1)[0]
    val = np.where(p[1] >= 0, _pack(2, p[0], p[1], kick), val)
    val = np.where(t >= 0, _pack(3, t, *_top(present & (_R != t[:, None]), 2)), val)
    st = _STR[mask]
    val = np.where(st >= 0, _pack(4, st), val)
    other = _top((cnt >= 2) & (_R != t[:, None]), 1)[0]
    val = np.where((t >= 0) & (other >= 0), _pack(6, t, other), val)
    val = np.where(q >= 0, _pack(7, q, _top(present & (_R != q[:, None]), 1)[0]), val)
    return val


def _tuples(n):
    grid = np.indices((5,) * n).reshape(n, -1).T
    return grid[grid.sum(1) <= 7]


def _build():
    low, high = _tuples(6), _tuples(7)
    p5 = 5 ** np.arange(7)
    # Oversized id maps: a dead combo that repeats a board card can overflow a
    # digit; those cells are masked by callers and only need to stay in range.
    lid = np.zeros(2 * 5 ** 6, np.int32)
    hid = np.zeros(2 * 5 ** 7, np.int32)
    lid[(low * p5[:6]).sum(1)] = np.arange(len(low))
    hid[(high * p5[:7]).sum(1)] = np.arange(len(high))
    total = low.sum(1)[:, None] + high.sum(1)[None, :]
    li, hi = np.nonzero((total >= 5) & (total <= 7))
    raw = _nonflush(np.concatenate([low[li], high[hi]], 1))
    m = np.arange(8192)
    bits = ((m[:, None] >> _R) & 1).astype(bool)
    flush = np.zeros(8192, np.int64)
    ok = bits.sum(1) >= 5
    st = _STR[m[ok]]
    flush[ok] = np.where(st >= 0, _pack(8, st), _pack(5, *_top(bits[ok], 5)))
    classes = np.unique(np.concatenate([raw, flush[ok]]))
    table = np.zeros((len(low), len(high)), np.uint16)
    table[li, hi] = np.searchsorted(classes, raw) + 1
    fl = np.zeros(8192, np.uint16)
    fl[ok] = np.searchsorted(classes, flush[ok]) + 1
    cat = np.zeros(len(classes) + 1, np.int8)
    cat[1:] = classes // 14 ** 5
    return lid, hid, table, fl, cat


_STR = _straights()
LID, HID, TABLE, FLUSH, CATEGORY = _build()
NCLASS = len(CATEGORY)
POP = np.array([bin(i).count('1') for i in range(8192)], np.int8)
_rank = np.arange(52) % 13
LK = np.where(_rank < 6, 5 ** np.minimum(_rank, 5), 0).astype(np.int64)
HK = np.where(_rank >= 6, 5 ** np.maximum(_rank - 6, 0), 0).astype(np.int64)
BIT = np.left_shift(np.int64(1), np.arange(52, dtype=np.int64))
CLK, CHK, CBIT = LK[C1] + LK[C2], HK[C1] + HK[C2], BIT[C1] + BIT[C2]


def evaluate(cards):
    """Dense strength class (higher wins) for arrays of 5 to 7 distinct cards."""
    cards = np.asarray(cards, np.int64)
    v = TABLE[LID[LK[cards].sum(-1)], HID[HK[cards].sum(-1)]]
    bits = BIT[cards].sum(-1)
    for suit in range(4):
        v = np.maximum(v, FLUSH[(bits >> (13 * suit)) & 8191])
    return v


def grid(board, runs=None):
    """Strength of every combo on `board` plus each row of extra cards.

    Returns (values (R, 1326) uint16, alive (R, 1326) bool). Combos that share
    a card with the board or the row's extra cards are dead and hold garbage.
    """
    board = np.asarray(board, np.int64)
    if runs is None:
        runs = np.zeros((1, 0), np.int64)
    runs = np.asarray(runs, np.int64)
    rl = LK[runs].sum(1) + LK[board].sum()
    rh = HK[runs].sum(1) + HK[board].sum()
    rb = BIT[runs].sum(1) + BIT[board].sum()
    v = TABLE[LID[rl[:, None] + CLK], HID[rh[:, None] + CHK]]
    if board.size + runs.shape[1] >= 5:
        for suit in range(4):
            rows = np.flatnonzero(POP[(rb >> (13 * suit)) & 8191] >= 3)
            if len(rows):
                m = ((rb[rows, None] + CBIT) >> (13 * suit)) & 8191
                v[rows] = np.maximum(v[rows], FLUSH[m])
    dead = HAS[board].any(0) if board.size else np.zeros(NC, bool)
    alive = np.broadcast_to(~dead, v.shape).copy()
    for j in range(runs.shape[1]):
        alive &= ~HAS[runs[:, j]]
    return v, alive


def midrank(v, alive):
    """Row-wise percentile (ties count half) of each alive combo's strength."""
    rows, cols = v.shape
    key = (np.arange(rows)[:, None] * NCLASS + v).ravel()
    hist = np.bincount(key, weights=alive.ravel(), minlength=rows * NCLASS).reshape(rows, NCLASS)
    below = np.cumsum(hist, axis=1) - hist
    live = np.maximum(alive.sum(1), 1)[:, None]
    out = (below.ravel()[key] + .5 * hist.ravel()[key]).reshape(rows, cols) / live
    return np.where(alive, out, 0.)


def board_features(board):
    """(strength now, expected strength after the next card, alive mask).

    Both are percentiles among all combos consistent with the board only, so
    the same numbers describe any player's holding from public information.
    """
    board = [int(c) for c in board]
    v, alive = grid(board)
    now = midrank(v, alive)[0]
    if len(board) >= 5:
        return now, now.copy(), alive[0]
    nxt = np.array([[c] for c in range(52) if c not in board])
    v2, alive2 = grid(board, nxt)
    pct = midrank(v2, alive2)
    ahead = pct.sum(0) / np.maximum(alive2.sum(0), 1)
    return now, np.where(alive[0], ahead, 0.), alive[0]


# ---- preflop hand classes --------------------------------------------------
def _classes():
    r1, r2 = C1 % 13, C2 % 13
    hi, lo = np.maximum(r1, r2), np.minimum(r1, r2)
    suited = (C1 // 13) == (C2 // 13)
    # 0..12 pairs, then suited/offsuit triangles: 169 classes in total.
    tri = hi * (hi - 1) // 2 + lo
    cls = np.where(hi == lo, hi, np.where(suited, 13 + tri, 13 + 78 + tri))
    return cls.astype(np.int64), hi, lo, suited


CLS, CHI, CLO, CSUITED = _classes()
CLS_COUNT = np.bincount(CLS, minlength=169).astype(float)


def preflop_features(eq_random):
    """(1326, 7) per-combo inputs of the preflop action model."""
    q = eq_random[CLS]
    pair = (CHI == CLO).astype(float)
    return np.column_stack([q, q * q, pair, CSUITED.astype(float), CHI / 12., CLO / 12.,
                            np.where(CHI == CLO, 0., (CHI - CLO) / 12.)])


# ---- context vectors shared by the offline fit and the live bot ------------
PRE_CTX, POST_CTX = 10, 13


def pre_context(pot, to_call, level, raises, limpers, active, behind, blind, invested):
    return np.array([to_call / max(1., pot + to_call), np.log1p(to_call / 2.) / 5.,
                     np.log1p(level / 2.) / 5., min(raises, 3) / 3., min(limpers, 3) / 3.,
                     active / 8., behind / 8., float(blind == 1), float(blind == 2),
                     float(invested)])


def post_context(street, pot, to_call, stack, active, behind, aggressor, raises, board):
    suits = np.bincount(np.asarray(board) // 13, minlength=4).max()
    ranks = np.bincount(np.asarray(board) % 13, minlength=13).max()
    return np.array([float(street == 1), float(street == 2), float(street == 3),
                     to_call / max(1., pot + to_call), np.log1p(pot / 2.) / 5.,
                     min(stack / max(1., pot), 10.) / 10., min(active - 2, 3) / 3.,
                     min(behind, 3) / 3., float(aggressor), min(raises, 2) / 2.,
                     float(ranks >= 2), float(suits >= 3), float(to_call >= stack > 0)])


def mlp(params, x, shift=None):
    """Class probabilities of a one-hidden-layer network; `shift` moves logits."""
    w1, b1, w2, b2 = params
    z = np.tanh(x @ w1 + b1) @ w2 + b2
    if shift is not None:
        z = z + shift
    z -= z.max(axis=-1, keepdims=True)
    p = np.exp(z)
    return p / p.sum(axis=-1, keepdims=True)


def post_inputs(now, ahead, ctx):
    x = np.empty((len(now), 4 + len(ctx)))
    x[:, 0], x[:, 1], x[:, 2], x[:, 3] = now, ahead, now * now, ahead * ahead
    x[:, 4:] = ctx
    return x


def pre_inputs(feat, ctx):
    x = np.empty((len(feat), feat.shape[1] + len(ctx)))
    x[:, :feat.shape[1]] = feat
    x[:, feat.shape[1]:] = ctx
    return x


def pre_class(kind, amount):
    """0 fold, 1 check/call, 2 raise, 3 large raise (raise-to of 40+ chips)."""
    if kind == 'fold':
        return 0
    if kind in ('check', 'call'):
        return 1
    return 3 if amount >= 40 else 2


def post_class(kind, fraction, facing):
    """Facing: fold/call/raise/big raise. Unbet: check/small/medium/large bet."""
    if facing:
        if kind == 'fold':
            return 0
        if kind in ('call', 'check'):
            return 1
        return 2 if fraction <= .75 else 3
    if kind in ('check', 'fold', 'call'):
        return 0
    return 1 if fraction <= .45 else 2 if fraction <= .9 else 3
