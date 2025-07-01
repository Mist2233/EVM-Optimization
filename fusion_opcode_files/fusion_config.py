# fusion_config.py

# =================================================================
# 1. 定义所有用到的操作码常量 (Opcode Constants)
# =================================================================
# --- 原始操作码 ---
PUSH1_OPCODE = 0x60
PUSH2_OPCODE = 0x61
JUMP_OPCODE = 0x56
SUB_OPCODE = 0x03
MUL_OPCODE = 0x02
ADD_OPCODE = 0x01

# --- 虚拟的融合操作码ID (Virtual Fused Opcode IDs) ---
VIRTUAL_UJUMP2_OPCODE = 0xB0 
VIRTUAL_SUB_MUL_OPCODE = 0xB1
VIRTUAL_PUSH1_ADD_OPCODE = 0xB2


# =================================================================
# 2. 新增: 创建一个 Opcode 值到助记符(名字)的映射词典
# =================================================================
# 这个词典能让我们的日志输出更具可读性。
# 你只需要把在上面定义过的常量加进来即可。
OPCODE_MNEMONICS = {
    PUSH1_OPCODE: "PUSH1",
    PUSH2_OPCODE: "PUSH2",
    JUMP_OPCODE: "JUMP",
    SUB_OPCODE: "SUB",
    MUL_OPCODE: "MUL",
    ADD_OPCODE: "ADD",
    # --- 融合后的操作码也可以加进来 ---
    VIRTUAL_UJUMP2_OPCODE: "FUSED_UJUMP2",
    VIRTUAL_SUB_MUL_OPCODE: "FUSED_SUB_MUL",
    VIRTUAL_PUSH1_ADD_OPCODE: "FUSED_PUSH1_ADD",
}


# =================================================================
# 3. 定义所有融合规则 (All Fusion Rules)
# =================================================================
# 这部分结构保持不变。
ALL_FUSION_RULES = {
    "PUSH2_JUMP": {
        "rule_name": "PUSH2_JUMP",
        "trigger_opcode": PUSH2_OPCODE,
        "pattern_opcodes": (JUMP_OPCODE,),
        "trigger_arg_bytes": 2,
        "pattern_bytes": 1,
        "fused_opcode_id": VIRTUAL_UJUMP2_OPCODE,
        "fused_mnemonic": OPCODE_MNEMONICS.get(VIRTUAL_UJUMP2_OPCODE)
    },

    "SUB_MUL": {
        "rule_name": "SUB_MUL",
        "trigger_opcode": SUB_OPCODE,
        "pattern_opcodes": (MUL_OPCODE,),
        "trigger_arg_bytes": 0,
        "pattern_bytes": 1,
        "fused_opcode_id": VIRTUAL_SUB_MUL_OPCODE,
        "fused_mnemonic": OPCODE_MNEMONICS.get(VIRTUAL_SUB_MUL_OPCODE)
    },
    
    "PUSH1_ADD": {
        "rule_name": "PUSH1_ADD",
        "trigger_opcode": PUSH1_OPCODE,
        "pattern_opcodes": (ADD_OPCODE,),
        "trigger_arg_bytes": 1,
        "pattern_bytes": 1,
        "fused_opcode_id": VIRTUAL_PUSH1_ADD_OPCODE,
        "fused_mnemonic": OPCODE_MNEMONICS.get(VIRTUAL_PUSH1_ADD_OPCODE)
    },
}
