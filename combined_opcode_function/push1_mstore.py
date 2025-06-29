from eth.abc import (
    ComputationAPI,
)


def push1_mstore(computation: ComputationAPI, value: bytes, offset: int) -> None:
    '''
    Combine PUSH1 with MSTORE.
    '''
    value = computation.code.read(1)
    offset = computation.code.read(1)

    padded_value = value.rjust(32, b"\x00")
    computation.extend_memory(int.from_bytes(offset, "big"), 32)
    computation.memory_write(int.from_bytes(offset, "big"), 32, padded_value)
