import os
import numpy as np
from repair import RepairPolicy
bot = RepairPolicy(dict(np.load(os.path.join(os.path.dirname(__file__), 'weights.npz'), allow_pickle=False)), extended=True, risk=True, temperature=1.0)
bot.name = 'Invoker candidate'
