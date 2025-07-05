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


def fused_push1_dup1(computation: ComputationAPI) -> None:
    """
    一个融合了 PUSH1 <value> 和 DUP1 的高效操作。

    原始操作:
    1. PUSH1: 从字节码读取1个字节，压入堆栈。Gas成本: 3。
    2. DUP1: 复制栈顶元素。Gas成本: 3。
    总成本: 6 Gas。

    融合后操作:
    1. 从字节码读取1个字节。
    2. 将这个字节连续两次压入堆栈。
    3. 消耗一个更低的、经过优化的Gas成本。
    """
    # 1. 读取 PUSH1 的1字节参数。
    #    这行代码的行为与原始的 `push1` 函数完全一致。
    #    `computation.code.read(1)` 会从当前程序计数器(PC)的位置读取1个字节，
    #    并自动将PC向前移动1位。
    value_to_push = computation.code.read(1)

    # 2. 将读取到的值连续两次压入堆栈。
    #    这比一次 push + 一次 dup 更高效，因为它减少了内部的堆栈指针操作
    #    和一次函数分派的开销。
    computation.stack_push_bytes(value_to_push)
    computation.stack_push_bytes(value_to_push)

    # 3. 消耗 Gas。原始成本是 3 + 3 = 6。
    #    我们设定一个更低的值（例如4或5）来体现优化带来的节省。
    #    这个值的设定本身也是一个可以研究的课题。
    computation.consume_gas(4, reason="Gas for FUSED_PUSH1_DUP1")