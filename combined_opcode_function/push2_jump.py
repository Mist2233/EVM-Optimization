from eth.abc import (
    ComputationAPI,
)
from eth.exceptions import (
    Halt,
    InvalidInstruction,
    InvalidJumpDestination,
)
from eth.vm.opcode_values import (
    JUMPDEST,
)


def ujump2(computation: ComputationAPI) -> None:
    '''
    Unconditional Jump
    '''
    # 从字节码读取 2 字节跳转地址
    raw_value = computation.code.read(2)
    jump_dest = int.from_bytes(raw_value, byteorder='big')

    # 设置 program_counter 到 jump_dest
    computation.code.program_counter = jump_dest

    # 合法性检查
    if not computation.code.is_valid_opcode(jump_dest):
        raise InvalidInstruction("Jump resulted in invalid instruction")

    next_opcode = computation.code.peek()
    if next_opcode != JUMPDEST:
        raise InvalidJumpDestination("Invalid Jump Destination")