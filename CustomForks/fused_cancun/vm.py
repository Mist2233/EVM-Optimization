from eth.vm.forks.cancun import CancunVM
from .state import FusedCancunState

class FusedCancunVM(CancunVM):
    # fork name
    fork = "fused cancun"

    # classes
    _state_class = FusedCancunState


