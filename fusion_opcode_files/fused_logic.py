from eth_utils.toolz import (
    curry,
)

from eth import (
    constants,
)
from eth._utils.numeric import (
    ceil8,
    signed_to_unsigned,
    unsigned_to_signed,
)
from eth.abc import (
    ComputationAPI,
)

def sub(computation: ComputationAPI) -> None:
    """
    Subtraction
    """
    left, right = computation.stack_pop_ints(2)

    result = (left - right) & constants.UINT_256_MAX

    computation.stack_push_int(result)

def mul(computation: ComputationAPI) -> None:
    """
    Multiplication
    """
    left, right = computation.stack_pop_ints(2)

    result = (left * right) & constants.UINT_256_MAX

    computation.stack_push_int(result)

def fused_sub_mul(computation: ComputationAPI) -> None:
    """
    融合 SUB 和 MUL 操作。
    从堆栈中弹出三个整数 s0, s1, s2 (其中 s0 是原栈顶元素, s1 是原次栈顶, s2 是原第三个元素)。
    计算 (s2 * ((s1 - s0) & UINT_256_MAX)) & UINT_256_MAX。
    将最终结果压回堆栈。

    这模拟了以下操作序列:
    Initial Stack: [..., s2, s1, s0] (s0 is TOS)
    1. SUB: Pops s0, s1. Pushes (s1 - s0). Stack: [..., s2, (s1-s0)]
    2. MUL: Pops (s1-s0), s2. Pushes (s2 * (s1-s0)). Stack: [..., result]
    """
    # computation.stack_pop_ints(3) 返回一个元组，
    # 其中第一个元素是原栈顶 (s0)，第二个是原次栈顶 (s1)，第三个是原第三个元素 (s2)。
    # 例如，如果栈是 [..., X, Y, Z] (Z是栈顶), stack_pop_ints(3) 返回 (Z, Y, X)
    # 所以 s0 = Z, s1 = Y, s2 = X
    s0, s1, s2 = computation.stack_pop_ints(3)

    # 执行减法: (s1 - s0)
    # 结果需要 & UINT_256_MAX 来模拟 EVM 的 256位无符号整数行为
    # (Python的整数减法可能产生负数，& 操作会将其转换为正确的无符号表示)
    sub_result = (s1 - s0) & constants.UINT_256_MAX

    # 执行乘法: (s2 * sub_result)
    mul_result = (s2 * sub_result) & constants.UINT_256_MAX

    # 将最终结果压回堆栈
    computation.stack_push_int(mul_result)

# 示例中使用的常量 (通常在 py-evm 的 constants 模块中)
# class constants: # 只是为了让上面的代码片段能独立理解
#     UINT_256_MAX = (2**256) - 1