# custom_computation.py

from typing import Dict, List, Optional
from eth.abc import (
    ComputationAPI,
    MessageAPI,
    StateAPI,
    TransactionContextAPI,
    OpcodeAPI,
)
from eth.exceptions import Halt
from eth.vm.computation import NO_RESULT
from eth.vm.logic.invalid import InvalidOpcode
# 导入 py-evm 的内部工具，用于创建 Opcode 对象
from eth.vm.opcode import as_opcode

# 1. 明确导入你作为基准的原始 Computation 类
from eth.vm.forks.cancun.computation import CancunComputation as BaseComputationForFusion

# 2. 导入你的融合规则和逻辑函数
import fusion_config
from fused_logic import (
    fused_sub_mul
)

# =============================================================
# ===            “完美对照组”，用于消除意外优化             ===
# =============================================================
class IdenticalComputation(BaseComputationForFusion):
    """
    这是一个完美的对照组。它继承了所有东西，但没有做任何修改。
    用它作为基准，可以精确测量出 FusedComputation 的净性能增益。
    """
    pass

# =============================================================
# ===            核心的 FusedComputation 类                 ===
# =============================================================
class FusedComputation(BaseComputationForFusion):
    """
    一个支持可配置化 Opcode Fusion 的 Computation 类。
    """

    _active_rules: Dict[int, List[Dict]] = {}

    # --- 核心修改 1: 重写 opcodes 属性，动态注册新指令 ---
    @property
    def opcodes(self) -> Dict[int, OpcodeAPI]:
        # 1. 先获取父类（原始EVM）的所有标准操作码
        original_opcodes = super().opcodes

        # 2. 定义我们自己的新操作码和它们的逻辑函数
        #    这是将“虚拟ID”和“执行逻辑”绑定的关键步骤
        custom_opcodes = {
            # 示例：将ID 0xB1 和 fused_sub_mul 函数绑定
            fusion_config.VIRTUAL_SUB_MUL_OPCODE: as_opcode(
                logic_fn=fused_sub_mul,
                mnemonic="FUSED_SUB_MUL",
                gas_cost=0  # Gas在logic_fn内部计算，这里设为0
            ),
            # 在这里添加你所有其他的虚拟操作码...
        }

        # 3. 将两者合并，返回一个完整的、增强版的操作码字典
        return {**original_opcodes, **custom_opcodes}

    @classmethod
    def configure_rules(cls, rule_names: List[str]) -> None:
        """
        根据传入的规则名称列表，来动态配置当前要激活的融合规则。
        """
        cls._active_rules.clear()
        all_rules = fusion_config.ALL_FUSION_RULES
        for name in rule_names:
            if name in all_rules:
                rule_info = all_rules[name]
                trigger_op = rule_info['trigger_opcode']
                if trigger_op not in cls._active_rules:
                    cls._active_rules[trigger_op] = []
                cls._active_rules[trigger_op].append(rule_info)
        
        active_rules_info = [
            f"{fusion_config.OPCODE_MNEMONICS.get(op, 'UNKNOWN')} (0x{op:02x})" 
            for op in cls._active_rules.keys()
        ]
        print(f"[INFO] FusedComputation configured with rules triggered by: {active_rules_info}")

    @classmethod
    def apply_computation(
        cls,
        state: "StateAPI",
        message: "MessageAPI",
        transaction_context: "TransactionContextAPI",
        parent_computation: Optional["ComputationAPI"] = None,
    ) -> "ComputationAPI":
        """
        重写的核心方法，所有交易执行的入口。
        """
        # 正确的写法：不将 parent_computation 传入构造函数
        with cls(state, message, transaction_context) as computation:
            # 在对象创建后，再处理 parent_computation 的逻辑
            if parent_computation is not None:
                computation.contracts_created = parent_computation.contracts_created
            
            # 标准的初始化逻辑
            if computation.is_origin_computation:
                computation.contracts_created = []
                if message.is_create:
                    cls.consume_initcode_gas_cost(computation)
            if message.is_create:
                computation.contracts_created.append(message.storage_address)

            # 处理预编译合约
            if message.code_address in computation.precompiles:
                computation.precompiles[message.code_address](computation)
                return computation

            # 执行主循环
            cls._main_loop(computation)
            return computation

    @classmethod
    def _main_loop(cls, computation: "ComputationAPI") -> None:
        """
        带有融合逻辑的 EVM 核心执行循环。
        """
        while not computation.is_stopped:
            opcode_value = computation.code.peek()
            fusion_applied = cls._try_apply_fusion(computation, opcode_value)
            if not fusion_applied:
                opcode_fn = computation.opcodes.get(opcode_value)
                if opcode_fn is None:
                    opcode_fn = InvalidOpcode(opcode_value)
                try:
                    opcode_fn(computation=computation)
                except Halt:
                    break

    @classmethod
    def _try_apply_fusion(cls, computation: "ComputationAPI", opcode_value: int) -> bool:
        """
        检查并执行融合规则。
        """
        if opcode_value not in cls._active_rules:
            return False
        
        for rule in cls._active_rules[opcode_value]:
            pattern = rule["pattern_opcodes"]
            pattern_len = len(pattern)
            pc = computation.code.program_counter
            trigger_arg_bytes = rule["trigger_arg_bytes"]
            
            if pc + 1 + trigger_arg_bytes + pattern_len > len(computation.code):
                continue

            is_match = True
            pattern_start_pc = pc + 1 + trigger_arg_bytes
            for i in range(pattern_len):
                if computation.code[pattern_start_pc + i] != pattern[i]:
                    is_match = False
                    break
            
            if is_match:
                fused_op_id = rule["fused_opcode_id"]
                fused_op_fn = computation.opcodes.get(fused_op_id)
                
                if fused_op_fn:
                    try:
                        fused_op_fn(computation=computation)
                        is_jump_type = "JUMP" in fused_op_fn.mnemonic.upper()
                        if not is_jump_type:
                            computation.code.program_counter = pattern_start_pc + rule["pattern_bytes"]
                        return True
                    except Halt:
                        computation.stop()
                        return True
        return False
