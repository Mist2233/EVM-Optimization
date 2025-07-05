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
DUP1_OPCODE = 0x80

# --- 虚拟的融合操作码ID (Virtual Fused Opcode IDs) ---
VIRTUAL_SUB_MUL_OPCODE = 0xB0
VIRTUAL_PUSH1_DUP1_OPCODE = 0xB1


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
    VIRTUAL_SUB_MUL_OPCODE: "FUSED_SUB_MUL",
    VIRTUAL_PUSH1_DUP1_OPCODE: "FUSED_PUSH1_DUP1"
}


# =================================================================
# 3. 定义所有融合规则 (All Fusion Rules)
# =================================================================
# 这部分结构保持不变。
ALL_FUSION_RULES = {
    "SUB_MUL": {
        "rule_name": "SUB_MUL",
        "trigger_opcode": SUB_OPCODE,
        "pattern_opcodes": b'\x02',
        "trigger_arg_bytes": 0,
        "pattern_bytes": 1,
        "fused_opcode_id": VIRTUAL_SUB_MUL_OPCODE,
        "fused_mnemonic": OPCODE_MNEMONICS.get(VIRTUAL_SUB_MUL_OPCODE)
    },
    "PUSH1_DUP1": {
        "rule_name": "PUSH1_DUP1",
        "trigger_opcode": PUSH1_OPCODE,
        "pattern_opcodes": b'\x80',  # 这是 DUP1 对应的字节码的值。之所以这样设定，是因为我们的操作码在检测时，是直接比较byte的值，这样设定使得类型统一，可以比较成功。
        "trigger_arg_bytes": 1,      # PUSH1 有1个字节的参数
        "pattern_bytes": 1,          # DUP1 指令本身占1个字节
        "fused_opcode_id": VIRTUAL_PUSH1_DUP1_OPCODE,
        "fused_mnemonic": "FUSED_PUSH1_DUP1"
    },
}
