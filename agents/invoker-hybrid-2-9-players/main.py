import os
for key in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):
    os.environ[key]='1'
import numpy as np
from macpoker import Bot
from base import Policy
from strategy import InvokerStrategy


class InvokerHybrid(Bot):
    name='Invoker'

    def __init__(self):
        weights=dict(np.load(os.path.join(os.path.dirname(__file__),'weights.npz'),allow_pickle=False))
        self.small=Policy(weights)
        self.large=InvokerStrategy()

    @property
    def rng(self):
        return self.small.rng

    @rng.setter
    def rng(self,value):
        self.small.rng=value
        self.large.rng=value

    @property
    def action_rng(self):
        return self.small.action_rng

    @action_rng.setter
    def action_rng(self,value):
        self.small.action_rng=value

    def on_hand_start(self,info):
        self.small.on_hand_start(info)
        self.large.on_hand_start(info)

    def on_action(self,event):
        self.small.on_action(event)
        self.large.on_action(event)

    def act(self,state):
        return (self.small if state.num_players<=6 else self.large).act(state)


bot=InvokerHybrid()
