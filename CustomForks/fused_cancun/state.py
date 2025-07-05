
from eth.vm.forks.cancun.state import (
    CancunTransactionExecutor,
    CancunState
)

from .computation import FusedCancunComputation

class FusedCancunTransactionExecutor(CancunTransactionExecutor):
    pass

class FusedCancunState(CancunState):
    computation_class = FusedCancunComputation
    transaction_executor_class = FusedCancunTransactionExecutor


