# custom_computation.py

from typing import cast, Optional
from eth.vm.forks.cancun.computation import CancunComputation as BaseComputationForFusion
from eth.abc import (
    StateAPI, MessageAPI, TransactionContextAPI, ComputationAPI, OpcodeAPI
)
from eth.exceptions import Halt
from eth.vm.logic.invalid import InvalidOpcode
from eth.vm.computation import NO_RESULT
import fusion_config
# from .opcodes import UJUMP2_OPCODE_CONST, SUBMUL_OPCODE_CONST # 示例融合操作码ID

# 假设从你的项目中导入基础 Computation 类，例如 CancunComputation
# 以及相关的类型和常量


# 这是一个占位符，你需要替换为你的实际基础 Computation 类
# 比如，如果你基于 Cancun 分叉，可能是 from eth.vm.forks.cancun.computation import CancunComputation
# class PlaceholderBaseComputation(ComputationAPI):
#     # 这个类需要填充一个实际的 py-evm Computation 类的实现
#     # 为了让下面的 FusedComputation 能运行，这里只是一个最小骨架
#     def __init__(self, state, message, transaction_context):
#         self.state = state
#         self.message = message
#         self.transaction_context = transaction_context
#         self.logger = type('Logger', (object,), {'show_debug2': False, 'debug2': print})() # 模拟logger
#         self.opcodes = {} # 模拟opcodes
#         self.precompiles = {}
#         self._stack = [] # 模拟stack
#         self.code = type('Code', (object,), {'program_counter': 0, '__iter__': lambda: iter([]), '__len__': lambda: 0, '__getitem__': lambda s, i: 0})() # 模拟code
#         # ... 需要更多模拟属性和方法 ...
#         pass
    
#     @classmethod
#     def apply_computation(cls, state, message, transaction_context, parent_computation=None):
#         # 这是原始的 apply_computation 逻辑（无融合）
#         # 你需要从 py-evm 的实际 Computation 类中复制过来，或者确保这个基类就是原始的
#         print("[INFO] Executing with ORIGINAL apply_computation (no fusion).")
#         with cls(state, message, transaction_context) as computation:
#             # ... (此处应为原始的、不含融合逻辑的 apply_computation 实现) ...
#             # 为了演示，我们简化一下
#             opcode_lookup = computation.opcodes
#             for opcode_byte_value in computation.code:
#                 opcode_fn_to_execute = opcode_lookup.get(opcode_byte_value, InvalidOpcode(opcode_byte_value))
#                 # print(f"Original Exec: {opcode_fn_to_execute.mnemonic if hasattr(opcode_fn_to_execute, 'mnemonic') else 'UNKNOWN'}")
#                 try:
#                     opcode_fn_to_execute(computation=computation)
#                 except Halt:
#                     break
#             return computation

#     def __enter__(self): return self
#     def __exit__(self, exc_type, exc_val, exc_tb): pass
#     # ... 其他 ComputationAPI 需要的方法 ...
#     @property
#     def is_origin_computation(self): return True # 模拟
#     def consume_initcode_gas_cost(self, computation): pass # 模拟

# 使用一个实际的基类，例如 CancunComputation
# 假设 BaseComputationForFusion 是你项目中正确的基类
# BaseComputationForFusion = PlaceholderBaseComputation # ！！！请务必替换为实际的基类 ！！！

class FusedComputation(BaseComputationForFusion):

    # 将导入的配置赋值给类属性，以便在类方法中通过 cls 访问
    FUSION_RULES = fusion_config.FUSION_RULES
    UJUMP2_OPCODE_CONST = fusion_config.UJUMP2_VIRTUAL_OPCODE
    SUBMUL_OPCODE_CONST = fusion_config.SUBMUL_VIRTUAL_OPCODE
    # ... 其他常量 ...

    @classmethod
    def apply_computation(
        cls,
        state: "StateAPI",
        message: "MessageAPI",
        transaction_context: "TransactionContextAPI",
        parent_computation: Optional["ComputationAPI"] = None,
    ) -> "ComputationAPI":
        # 这里是你之前包含JIT融合逻辑和调试标志的 apply_computation 实现
        with cls(state, message, transaction_context) as computation:
            # --- 保留你原有的初始逻辑 (contracts_created, initcode_gas, etc.) ---
            if computation.is_origin_computation:
                computation.contracts_created = []
                if message.is_create:
                    cls.consume_initcode_gas_cost(computation) # 假设基类有此方法
            if parent_computation is not None:
                computation.contracts_created = parent_computation.contracts_created
            if message.is_create:
                computation.contracts_created.append(message.storage_address)
            # --- 原有初始逻辑结束 ---

            precompile = computation.precompiles.get(message.code_address, NO_RESULT)
            if precompile is not NO_RESULT:
                precompile(computation)
                return computation

            computation.logger.show_debug2 = True 
            show_debug2 = computation.logger.show_debug2

            opcode_lookup = computation.opcodes
            
            # 假设 FUSION_RULES 和相关常量已导入或在此定义
            FUSION_RULES = getattr(cls, 'FUSION_RULES', {}) # 从类属性获取，或默认为空
            UJUMP2_OPCODE_CONST = getattr(cls, 'UJUMP2_OPCODE_CONST', 0xB0)
            # ... 其他融合操作码常量 ...


            if UJUMP2_OPCODE_CONST not in opcode_lookup and show_debug2:
                 print(f"[CRITICAL FUSION ERROR] UJUMP2 (0x{UJUMP2_OPCODE_CONST:02x}) is not defined in opcode_lookup! Fusion will fail.")
            # ... (其他健全性检查) ...

            for current_opcode_byte in computation.code:
                pc_of_current_opcode_byte = computation.code.program_counter - 1
                pc_after_current_opcode_byte = computation.code.program_counter
                fusion_rule_matched_and_executed = False

                if current_opcode_byte in FUSION_RULES:
                    for rule in FUSION_RULES[current_opcode_byte]:
                        pc_where_pattern_starts = pc_after_current_opcode_byte + rule["trigger_arg_bytes"]
                        if pc_where_pattern_starts + (len(rule["pattern_opcodes"]) -1) < len(computation.code):
                            is_full_pattern_match = True
                            for i, expected_pattern_op_byte in enumerate(rule["pattern_opcodes"]):
                                if computation.code[pc_where_pattern_starts + i] != expected_pattern_op_byte:
                                    is_full_pattern_match = False
                                    break
                            if is_full_pattern_match:
                                if show_debug2:
                                    print(f"\n[FUSION TRIGGERED] PC={pc_of_current_opcode_byte}: Op 0x{current_opcode_byte:02x} "
                                          f"matched pattern for Fused Op ID 0x{rule['fused_opcode_id']:02x} ({rule['fused_mnemonic']})")
                                try:
                                    fused_opcode_object = opcode_lookup[rule["fused_opcode_id"]]
                                    fused_opcode_object(computation=computation)
                                    # PC 后处理 (如之前讨论的)
                                    is_fused_op_a_jump_type = (rule["fused_opcode_id"] == UJUMP2_OPCODE_CONST) # 示例
                                    if not is_fused_op_a_jump_type:
                                        computation.code.program_counter = pc_where_pattern_starts + rule["pattern_bytes"]
                                    
                                    if show_debug2:
                                        print("    >> FUSED OPCODE EXECUTED: 0x%x (%s) | PC now: %s | Stack: %s" %
                                              (rule["fused_opcode_id"], fused_opcode_object.mnemonic,
                                               computation.code.program_counter, computation._stack))
                                    fusion_rule_matched_and_executed = True
                                    break 
                                except KeyError:
                                    if show_debug2: print(f"    [ERROR] FUSION FAILED: Fused Opcode ID 0x{rule['fused_opcode_id']:02x} not found.")
                                except Exception as e_fusion_exec:
                                    if show_debug2: print(f"    [ERROR] FUSION FAILED: Exception during fused logic: {e_fusion_exec}")
                
                if fusion_rule_matched_and_executed:
                    continue

                # --- 如果没有融合，则正常执行 ---
                try:
                    opcode_fn_to_execute = opcode_lookup[current_opcode_byte]
                except KeyError:
                    # 确保 InvalidOpcode 已导入
                    from eth.vm.logic.invalid import InvalidOpcode 
                    opcode_fn_to_execute = InvalidOpcode(current_opcode_byte)
                
                if show_debug2:
                    # 确保 BaseComputation 和 cast 已导入
                    # base_comp_for_print = cast(BaseComputation, computation)
                    try:
                        mnemonic_to_print = opcode_fn_to_execute.mnemonic
                    except AttributeError: mnemonic_to_print = "INVALID/UNKNOWN"
                    print("OPCODE: 0x%x (%s) | pc: %s | stack: %s" %
                          (current_opcode_byte, mnemonic_to_print,
                           pc_of_current_opcode_byte, computation._stack))
                try:
                    opcode_fn_to_execute(computation=computation)
                except Halt: # 确保 Halt 已导入
                    break
            return computation

# 你需要将 FUSION_RULES 和相关常量作为 FusedComputation 的类属性或以其他方式使其可访问
# 例如:
# FusedComputation.FUSION_RULES = { ... } 
# FusedComputation.UJUMP2_OPCODE_CONST = 0xB0
# (或者在 FusedComputation 类定义内部直接定义它们)
