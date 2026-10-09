import os
from proxy import ReplayProxy
bot=ReplayProxy(os.path.join(os.path.dirname(__file__),"model.npz"),'Replay proxy - jongwon')
