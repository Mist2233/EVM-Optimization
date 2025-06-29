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

def cjump2(computation: ComputationAPI) -> None:
    '''
    Conditional Jump
    '''

    # 从代码中读取 2 字节跳转地址（立即数）
    raw_value = computation.code.read(2)
    jump_dest = int.from_bytes(raw_value, byteorder='big')

    # 从栈中弹出条件值
    check_value = computation.stack_pop1_int()

    if check_value:
        # 设置 program_counter 到跳转地址
        computation.code.program_counter = jump_dest

        # 安全检查：目标地址必须是有效的 JUMPDEST
        if not computation.code.is_valid_opcode(jump_dest):
            raise InvalidInstruction("Jump resulted in invalid instruction")

        next_opcode = computation.code.peek()
        if next_opcode != JUMPDEST:
            raise InvalidJumpDestination("Invalid Jump Destination")
