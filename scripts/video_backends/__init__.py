from .compshare_h3 import CompShareH3
from .local_h3 import LocalH3
from .minimax_h3 import MiniMaxH3
from .minimax_hailuo import MiniMaxHailuo
from .seedance_ark import SeedanceArk
from .wan3 import Wan3

BACKENDS = {
    "hailuo": MiniMaxHailuo,
    "h3": MiniMaxH3,
    "minimax": MiniMaxH3,
    "compshare": CompShareH3,
    "local": LocalH3,
    "seedance": SeedanceArk,
    "ark": SeedanceArk,
    "wan": Wan3,
    "wan3": Wan3,
    "wan_3": Wan3,
}
