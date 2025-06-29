from typing import cast, Optional # 确保导入

# --- 假设的导入 ---
from eth.abc import (
    StateAPI, MessageAPI, TransactionContextAPI, ComputationAPI, OpcodeAPI
)
from eth.vm.computation import BaseComputation
from eth.vm.exceptions import Halt, InvalidOpcode
from eth.constants import NO_RESULT
from .fusion_rules import FUSION_RULES # 导入你定义的融合规则
from .opcodes import UJUMP2_VIRTUAL_OPCODE, SUBMUL_VIRTUAL_OPCODE # 导入融合后的操作码ID

class YourActualComputationClass(ComputationAPI): # 替换为你的类名

    @classmethod
    def apply_computation(
        cls,
        state: "StateAPI",
        message: "MessageAPI",
        transaction_context: "TransactionContextAPI",
        parent_computation: Optional["ComputationAPI"] = None,
    ) -> "ComputationAPI":
        with cls(state, message, transaction_context) as computation:
            # --- 保留你原有的初始逻辑 (contracts_created, initcode_gas, etc.) ---
            if computation.is_origin_computation:
                computation.contracts_created = []
                if message.is_create:
                    cls.consume_initcode_gas_cost(computation)
            if parent_computation is not None:
                computation.contracts_created = parent_computation.contracts_created
            if message.is_create:
                computation.contracts_created.append(message.storage_address)
            # --- 原有初始逻辑结束 ---

            precompile = computation.precompiles.get(message.code_address, NO_RESULT)
            if precompile is not NO_RESULT:
                precompile(computation)
                return computation

            computation.logger.show_debug2 = True # 你强制开启的调试
            show_debug2 = computation.logger.show_debug2

            opcode_lookup = computation.opcodes

            for current_opcode_byte in computation.code: # 当前从流中取出的操作码字节
                pc_of_current_opcode_byte = computation.code.program_counter - 1 # 这个操作码本身的PC
                # pc_after_current_opcode_byte 指向当前操作码字节之后的位置 (可能是参数，或下一个指令)
                pc_after_current_opcode_byte = computation.code.program_counter

                fusion_rule_matched_and_executed = False

                if current_opcode_byte in FUSION_RULES:
                    for rule in FUSION_RULES[current_opcode_byte]:
                        # 模式应该在触发操作码的参数之后开始匹配
                        pc_where_pattern_starts = pc_after_current_opcode_byte + rule["trigger_arg_bytes"]
                        
                        # 边界检查: 确保有足够的字节来匹配整个模式
                        if pc_where_pattern_starts + (len(rule["pattern_opcodes"]) -1) < len(computation.code):
                            # "窥视"并匹配模式
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
                                    
                                    # 调用融合后的 _FastOpcode 对象。
                                    # 其 logic_fn (如 flow.ujump2, sub_then_mul_fused) 会被执行。
                                    # Gas 消耗由 _FastOpcode 的 __call__ 处理。
                                    # PC 管理:
                                    # - 对于 UJUMP2 (flow.ujump2): `program_counter` 在调用时指向 PUSH2 的参数，
                                    #   flow.ujump2 会 read(2) 这些参数并设置最终的跳转PC。
                                    # - 对于 SUBMUL (sub_then_mul_fused): `program_counter` 在调用时指向原 MUL 的位置。
                                    #   sub_then_mul_fused 不读字节码，只操作堆栈。
                                    fused_opcode_object(computation=computation)

                                    # PC后处理：如果不是跳转类型的融合操作，需要手动跳过被融合的模式字节
                                    # 检查融合操作是否是已知的跳转类型 (这需要一种方式来标记或识别)
                                    # 简单起见，我们先假设 UJUMP2 (0xB0) 是跳转，SUBMUL (0xB1) 不是。
                                    is_fused_op_a_jump_type = (rule["fused_opcode_id"] == 0xB0) # 示例判断

                                    if not is_fused_op_a_jump_type:
                                        # 对于非跳转融合（如SUBMUL），其logic_fn执行后，PC仍指向原模式的开头
                                        # (例如，对于SUB-MUL融合，PC在flow.sub_mul_fused执行后，仍指向原MUL指令位置)
                                        # 我们需要将PC前进以跳过这个模式。
                                        # `pc_after_current_opcode_byte` 是在触发指令之后，参数之前
                                        # `rule["trigger_arg_bytes"]` 是触发指令的参数长度
                                        # `rule["pattern_bytes"]` 是模式本身的长度
                                        # 我们需要跳过整个模式，所以PC应设置为 pattern 的末尾
                                        computation.code.program_counter = pc_where_pattern_starts + rule["pattern_bytes"]
                                    
                                    if show_debug2:
                                        # base_comp = cast(BaseComputation, computation)
                                        print("    >> FUSED OPCODE EXECUTED: 0x%x (%s) | PC now: %s | Stack: %s" %
                                              (rule["fused_opcode_id"],
                                               fused_opcode_object.mnemonic, # 或者 rule["fused_mnemonic"]
                                               computation.code.program_counter,
                                               computation._stack))
                                    
                                    fusion_rule_matched_and_executed = True
                                    break # 跳出当前触发操作码的规则循环，因为已处理

                                except KeyError:
                                    if show_debug2:
                                        print(f"    [ERROR] FUSION FAILED: Fused Opcode ID 0x{rule['fused_opcode_id']:02x} not found in opcode_lookup.")
                                except Exception as e_fusion_exec:
                                    if show_debug2:
                                        print(f"    [ERROR] FUSION FAILED: Exception during execution of fused logic for 0x{rule['fused_opcode_id']:02x}: {e_fusion_exec}")
                        # else: pattern did not match (is_full_pattern_match is False)
                    # else: boundary check failed
                
                if fusion_rule_matched_and_executed:
                    continue # 非常重要：跳过当前触发操作码及其已融合部分的常规执行

                # --- 融合逻辑结束 ---

                # 如果没有融合发生，则正常执行当前 current_opcode_byte
                try:
                    opcode_fn_to_execute = opcode_lookup[current_opcode_byte]
                except KeyError:
                    from eth.vm.logic.invalid import InvalidOpcode # 应在模块顶部导入
                    opcode_fn_to_execute = InvalidOpcode(current_opcode_byte)
                
                # --- 保留你原有的调试输出逻辑 ---
                if show_debug2:
                    base_comp_for_print = cast(BaseComputation, computation) # 假设已导入
                    try:
                        mnemonic_to_print = opcode_fn_to_execute.mnemonic
                    except AttributeError:
                        if hasattr(opcode_fn_to_execute, '__wrapped__') and hasattr(opcode_fn_to_execute.__wrapped__, 'mnemonic'):
                             mnemonic_to_print = opcode_fn_to_execute.__wrapped__.mnemonic
                        else:
                             mnemonic_to_print = "INVALID/UNKNOWN"
                    
                    computation.logger.debug2("测试 DEBUG2 级别日志是否生效") 
                    print("OPCODE: 0x%x (%s) | pc: %s | stack: %s" %
                          (current_opcode_byte,
                           mnemonic_to_print,
                           pc_of_current_opcode_byte,
                           base_comp_for_print._stack))
                # --- 原有调试输出逻辑结束 ---

                try:
                    opcode_fn_to_execute(computation=computation)
                except Halt: # 假设已导入
                    break
            return computation
