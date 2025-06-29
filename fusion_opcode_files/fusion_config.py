# fusion_config.py (或者作为 Computation 类的属性)

# 假设你的操作码值已定义
PUSH2_OPCODE = 0x61
JUMP_OPCODE = 0x56
SUB_OPCODE = 0x03
MUL_OPCODE = 0x02

# 你定义的融合后操作码的“虚拟”ID (这些ID必须在 opcode_lookup 中有对应的 _FastOpcode 定义)
UJUMP2_VIRTUAL_OPCODE = 0xB0 
SUBMUL_VIRTUAL_OPCODE = 0xB1 # 假设你为 SUB-MUL 融合定义的新操作码值

FUSION_RULES = {
    PUSH2_OPCODE: [
        {
            "pattern_opcodes": (JUMP_OPCODE,),      # 在 PUSH2 参数之后期望的序列
            "trigger_arg_bytes": 2,                 # PUSH2 从字节码读取2个参数字节
            "pattern_bytes": 1,                     # JUMP_OPCODE 本身占1字节
            "fused_opcode_id": UJUMP2_VIRTUAL_OPCODE,
            "fused_mnemonic": "UJUMP2_FUSED_FROM_PUSH2_JUMP" # 用于日志
        },
        # 可以为 PUSH2 添加其他融合规则
    ],
    SUB_OPCODE: [
        {
            "pattern_opcodes": (MUL_OPCODE,),       # 在 SUB 之后期望的序列
            "trigger_arg_bytes": 0,                  # SUB 不从字节码读取参数
            "pattern_bytes": 1,                      # MUL_OPCODE 本身占1字节
            "fused_opcode_id": SUBMUL_VIRTUAL_OPCODE,
            "fused_mnemonic": "SUBMUL_FUSED_FROM_SUB_MUL"
        },
        # 可以为 SUB 添加其他融合规则
    ],
    # ... 可以为其他触发操作码定义规则 ...
}