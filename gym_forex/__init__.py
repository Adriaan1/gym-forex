import logging
from gym.envs.registration import register

logger = logging.getLogger(__name__)

register(
    id='Forex-v0',
    entry_point='gym_forex.envs:ForexEnv',
    timestep_limit=1000000,
    reward_threshold=1.0,
    nondeterministic = True,
)

