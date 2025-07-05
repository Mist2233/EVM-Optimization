# custom_forks/fused_cancun/computation.py

# 1. 从我们之前的文件中，导入那个包含了所有核心逻辑的“原型引擎”类
from custom_computation import FusedComputation

# 2. 定义我们的“量产引擎”，让它直接继承“原型引擎”
class FusedCancunComputation(FusedComputation):
    """
    这是我们 FusedCancun fork 专用的计算类。
    它通过继承，自动拥有了 FusedComputationForDebug 中的所有功能，
    包括：
    - 自定义的 opcodes 字典
    - apply_computation 方法
    - _main_loop 方法
    - _try_apply_fusion 方法
    - ...以及其他所有属性和方法。
    """
    # 3. 这里什么都不用写！它已经拥有了父类的一切。
    pass