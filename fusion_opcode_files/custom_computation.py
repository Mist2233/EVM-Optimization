# custom_computation.py

from typing import Dict, List, Optional
from eth.abc import (
    ComputationAPI,
    MessageAPI,
    StateAPI,
    TransactionContextAPI
)
from eth.exceptions import Halt
from eth.vm.computation import NO_RESULT

# 1. 明确导入你作为基准的原始 Computation 类。
#    我们将它命名为 BaseComputationForFusion，这样你的 benchmark 脚本就可以
#    直接从这个文件导入它，作为你的 "OriginalComputation"。
from eth.vm.forks.cancun.computation import CancunComputation as BaseComputationForFusion

# 2. 导入你优化后的 fusion_config 文件
import fusion_config

# =============================================================
# ===            新增的“完美对照组” (在此处添加)            ===
# =============================================================
class IdenticalComputation(BaseComputationForFusion):
    """
    这是一个完美的对照组。它继承了所有东西，但没有做任何修改。
    它的行为理应和 BaseComputationForFusion 100% 相同。
    我们用它来测试是否存在“无心插柳”的优化。
    """
# =============================================================


class FusedComputation(BaseComputationForFusion):
    """
    一个支持可配置化 Opcode Fusion 的 Computation 类。
    它继承自 BaseComputationForFusion，并重写了核心的执行逻辑，
    在标准的 EVM 执行循环中加入了模式匹配和指令替换的功能。
    """

    # 一个类属性，用来存储当前被激活的融合规则。
    # 它的结构是: { trigger_opcode: [rule_dict_1, rule_dict_2, ...] }
    _active_rules: Dict[int, List[Dict]] = {}

    @classmethod
    def configure_rules(cls, rule_names: List[str]) -> None:
        """
        根据传入的规则名称列表，来动态配置当前要激活的融合规则。
        这使得我们可以灵活地测试单个规则或多个规则的组合效果。

        :param rule_names: 一个包含规则名称的字符串列表, e.g., ["SUB_MUL", "PUSH_JUMP"]
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
        
        # 为了调试，可以打印出当前激活了哪些规则
        active_rules_info = [
            f"{fusion_config.OPCODE_MNEMONICS.get(op_code, 'UNKNOWN')} (0x{op_code:02x})" 
            for op_code in cls._active_rules.keys()
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
        它创建 computation 对象，并调用核心的执行循环。
        """
        # 使用上下文管理器创建 computation 对象，确保资源的正确处理
        with cls(state, message, transaction_context) as computation:
            
            # 1. 处理预编译合约 (Precompiles)，这是标准流程
            if message.code_address in computation.precompiles:
                computation.precompiles[message.code_address](computation)
                return computation

            # 2. 执行带有融合逻辑的 EVM 主循环
            cls._main_loop(computation)

            return computation

    @classmethod
    def _main_loop(cls, computation: "ComputationAPI") -> None:
        """
        带有融合逻辑的 EVM 核心执行循环。
        """
        # 使用 is_stopped 属性来判断循环是否应该终止
        while not computation.is_stopped:
            # 获取当前程序计数器处的 opcode
            opcode_value = computation.code.peek()

            # 尝试应用融合规则
            fusion_applied = cls._try_apply_fusion(computation, opcode_value)

            # 如果没有触发任何融合规则，则执行标准 opcode
            if not fusion_applied:
                # 定位并执行标准 opcode
                opcode_fn = computation.opcodes.get(opcode_value)
                if opcode_fn is None:
                    # 如果找不到，则执行无效操作码逻辑
                    from eth.vm.logic.invalid import InvalidOpcode
                    opcode_fn = InvalidOpcode(opcode_value)
                
                try:
                    opcode_fn(computation=computation)
                except Halt:
                    break

    @classmethod
    def _try_apply_fusion(cls, computation: "ComputationAPI", opcode_value: int) -> bool:
        """
        检查当前 opcode 是否能触发一个融合规则，如果能，则执行它。
        :return: 如果成功执行了融合，返回 True，否则返回 False。
        """

        # =============================================================
        # ===                诊断探针 (在此处添加)                ===
        # =============================================================
        # 在第一次进入这个函数时，打印出当前激活了哪些规则
        # 我们用一个 "has_printed" 标志来确保它只打印一次，避免刷屏
        if not hasattr(cls, '_debug_rules_printed'):
            print(f"\n[DIAGNOSTIC PROBE] Inside _try_apply_fusion. Current _active_rules keys: {list(cls._active_rules.keys())}\n")
            cls._debug_rules_printed = True # 设置标志，防止重复打印
        # =============================================================


        # 如果当前 opcode 不是任何一个激活规则的触发器，直接返回 False
        if opcode_value not in cls._active_rules:
            return False

        # 遍历所有由该 opcode 触发的规则
        for rule in cls._active_rules[opcode_value]:
            pattern = rule["pattern_opcodes"]
            pattern_len = len(pattern)
            pc = computation.code.program_counter
            trigger_arg_bytes = rule["trigger_arg_bytes"]
            
            # 检查是否有足够的字节码来匹配整个模式
            # +1 是因为 peek() 并没有移动 PC
            if pc + 1 + trigger_arg_bytes + pattern_len > len(computation.code):
                continue

            # 检查模式是否完全匹配
            is_match = True
            pattern_start_pc = pc + 1 + trigger_arg_bytes
            for i in range(pattern_len):
                if computation.code[pattern_start_pc + i] != pattern[i]:
                    is_match = False
                    break
            
            # 如果模式完全匹配，执行融合操作
            if is_match:
                fused_op_id = rule["fused_opcode_id"]
                fused_op_fn = computation.opcodes.get(fused_op_id)
                
                if fused_op_fn:
                    try:
                        # 执行融合后的 "超级指令"
                        fused_op_fn(computation=computation)

                        # 手动推进程序计数器 (PC)，跳过已被融合的指令
                        is_jump_type = "JUMP" in fused_op_fn.mnemonic.upper()
                        if not is_jump_type:
                            bytes_to_skip = 1 + trigger_arg_bytes + rule["pattern_bytes"]
                            # 注意：我们应该直接设置PC，而不是累加
                            computation.code.program_counter = pattern_start_pc + rule["pattern_bytes"]
                        
                        return True # 成功执行了融合，返回 True
                    
                    except Halt:
                        # 如果融合指令本身导致了 Halt (如 FUSED_STOP)，则中断循环
                        computation.stop()
                        return True
                
        # 遍历完所有规则都没有匹配成功
        return False
