# custom_computation.py

from typing import Dict, List, Optional, cast
from eth.abc import (
    ComputationAPI,
    MessageAPI,
    StateAPI,
    TransactionContextAPI,
    OpcodeAPI,
)
from eth.exceptions import Halt
from eth.vm.logic.invalid import InvalidOpcode
from eth.vm.opcode import as_opcode
from eth.vm.computation import BaseComputation


# 导入基础类和配置
from eth.vm.forks.cancun.computation import CancunComputation as BaseComputationForFusion
import fusion_config
from fused_logic import fused_sub_mul, fused_push1_dup1

def NO_RESULT(computation: ComputationAPI) -> None:
    """
    This is a special method intended for usage as the "no precompile found" result.
    The type signature is designed to match the other precompiles.
    """
    raise Exception("This method is never intended to be executed")

# =============================================================
# ===            “完美对照组” (保持不变)                  ===
# =============================================================
class IdenticalComputation(BaseComputationForFusion):
    pass

# =============================================================
# ===            核心的 FusedComputation 类 (修正版)        ===
# =============================================================
class FusedComputation(BaseComputationForFusion):
    _active_rules: Dict[int, List[Dict]] = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fusion_hit_counts: Dict[str, int] = {}

    @property
    def opcodes(self) -> Dict[int, OpcodeAPI]:
        original_opcodes = super().opcodes
        custom_opcodes = {
            fusion_config.VIRTUAL_SUB_MUL_OPCODE: as_opcode(
                logic_fn=fused_sub_mul, mnemonic="FUSED_SUB_MUL", gas_cost=0
            ),
            fusion_config.VIRTUAL_PUSH1_DUP1_OPCODE: as_opcode(
                logic_fn=fused_push1_dup1, mnemonic="FUSED_PUSH1_DUP1", gas_cost=0
            ),
        }
        return {**original_opcodes, **custom_opcodes}

    @classmethod
    def configure_rules(cls, rule_names: List[str]) -> None:
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
        state: StateAPI,
        message: MessageAPI,
        transaction_context: TransactionContextAPI,
        parent_computation: Optional[ComputationAPI] = None,
    ) -> ComputationAPI:
        with cls(state, message, transaction_context) as computation:
            if computation.is_origin_computation:
                # If origin computation, reset contracts_created
                computation.contracts_created = []

                if message.is_create:
                    # If computation is from a create transaction, consume initcode gas
                    # if >= Shanghai. CREATE and CREATE2 are handled in the opcode
                    # implementations.
                    cls.consume_initcode_gas_cost(computation)

            if parent_computation is not None:
                # If this is a child computation (has a parent computation), inherit the
                # contracts_created
                computation.contracts_created = parent_computation.contracts_created

            if message.is_create:
                # For all create messages, append the storage address to the
                # contracts_created list
                computation.contracts_created.append(message.storage_address)

            # Early exit on pre-compiles
            precompile = computation.precompiles.get(message.code_address, NO_RESULT)
            if precompile is not NO_RESULT:
                if not message.is_delegation:
                    precompile(computation)
                return computation

            show_debug2 = computation.logger.show_debug2

            opcode_lookup = computation.opcodes

            # 标记还需跳过的循环次数
            skip_num = 0

            for opcode in computation.code:
                
                if skip_num > 0:
                    skip_num -= 1
                    continue
                
                # 重新引入fusion_successful这个量，是为了处理jump的情况。
                # jump类型的函数本身就有跳转的功能，因此它跳转后我不能再跳过其后续的
                fusion_successful = False

                # 记录当前PC，以便在融合时进行操作
                pc_before_opcode = computation.code.program_counter - 1
                
                # =================== START: FUSION LOGIC INSERTION ===================
                # 检查当前 opcode 是否是我们关心的“触发器”
                if opcode in cls._active_rules:
                    # 遍历所有由该 opcode 触发的规则
                    for rule in cls._active_rules[opcode]:
                        # --- 执行模式匹配 ---
                        trigger_arg_bytes = rule["trigger_arg_bytes"]
                        pattern_bytes = rule["pattern_bytes"]
                        pattern_opcodes = rule["pattern_opcodes"]
                        pattern_start_pc = pc_before_opcode + 1 + trigger_arg_bytes

                        if pattern_start_pc + pattern_bytes > len(computation.code):
                            continue # 边界检查失败，尝试下一条规则

                        actual_pattern = computation.code[pattern_start_pc : pattern_start_pc + pattern_bytes]
                        is_match = actual_pattern == pattern_opcodes
                        
                        # is_match = False # 用于强制关闭匹配
                        # --- 如果匹配成功 ---
                        if is_match:
                            rule_name = rule["rule_name"]
                            computation.logger.debug(f"FUSION HIT: {rule_name} at PC {pc_before_opcode}")

                            # 获取并执行对应的融合函数
                            fused_op_id = rule["fused_opcode_id"]
                            fused_op_fn = opcode_lookup[fused_op_id]
                            
                            # 执行前，将PC重置到触发器之后，以便融合函数能正确读取参数
                            computation.code.seek(pc_before_opcode + 1)
                            fused_op_fn(computation=computation)
                            
                            # Check if the fused operation was a JUMP type.
                            is_jump_type = "JUMP" in fused_op_fn.mnemonic.upper()

                            if not is_jump_type:
                                # If it's not a JUMP, set skip_num to skip the pattern opcodes.
                                skip_num = pattern_bytes
                            # If it IS a JUMP, we do NOT set skip_num. The JUMP has already
                            # moved the PC, and the loop will naturally continue from there.
                            
                            fusion_successful = True

                            # 标记融合成功，并记录次数
                            computation.fusion_hit_counts[rule_name] = computation.fusion_hit_counts.get(rule_name, 0) + 1
                            break # 成功匹配并执行了一条规则，跳出规则循环
                
                # 如果融合已成功，跳过原生 Opcode 的执行，进入下一次主循环
                if fusion_successful:
                    continue
                # ==================== END: FUSION LOGIC INSERTION ====================

                try:
                    opcode_fn = opcode_lookup[opcode]
                except KeyError:
                    opcode_fn = InvalidOpcode(opcode)

                if show_debug2:
                    # We dig into some internals for debug logs
                    base_comp = cast(BaseComputation, computation)

                    try:
                        mnemonic = opcode_fn.mnemonic
                    except AttributeError:
                        mnemonic = opcode_fn.__wrapped__.mnemonic  # type: ignore

                    computation.logger.debug2(
                        f"OPCODE: 0x{opcode:x} ({mnemonic}) | "
                        f"pc: {max(0, computation.code.program_counter - 1)} | "
                        f"stack: {base_comp._stack}"
                    )

                try:
                    opcode_fn(computation=computation)
                except Halt:
                    break

        return computation
