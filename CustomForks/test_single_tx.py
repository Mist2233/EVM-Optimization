# debug_single_tx.py
# 最终版：调用我们自己创建的、独立的、可复用的 FusedCancunVM

import os
import sys
import time
import json
import logging

# --- 路径修复 (确保能找到所有模块) ---
# 这几行代码现在至关重要，它能确保 Python 找到我们的 custom_forks 目录
current_script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_script_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# --- 导入模块 ---
from eth.chains.base import Chain
from eth.db.atomic import AtomicDB
from eth import constants
from eth_utils import to_canonical_address, decode_hex
from eth_keys import keys

# 导入我们自己的工具
from db_utils import fetch_bytecode
import fusion_config

# ======================= 1. 导入我们最终打造的“成品”虚拟机 =======================
# 不再需要从 py-evm 导入 CancunVM 或其他组件了
from custom_forks.fused_cancun import FusedCancunVM
# ==============================================================================


# --- 实验目标配置 ---
CONTRACT_ADDRESS = "0x32353a6c91143bfd6c7d363b546e62a9a2489a20"
INPUT_DATA = "0x095ea7b300000000000000000000000069460570c93f9de5e2edbc3052bf10125f0ca22d0000000000000000000000000000000000000000000000122af4aaf33e220827"
RULES_TO_TEST = ["PUSH1_DUP1"]
OUTPUT_LOG_FILE = "debug_trace.log"

def main_debug():
    print("--- 开始单点调试 ---")
    print(f"目标合约: {CONTRACT_ADDRESS}")
    print(f"测试规则: {RULES_TO_TEST}")

    # ======================= 2. 所有复杂的本地类定义都已删除！ =======================
    # FusedTransactionExecutor, FusedState, VM_Debug 等类不再需要在这里定义。
    # 它们已经被整齐地封装在了我们的 custom_forks 包中。
    # ==============================================================================

    # --- 准备虚拟机环境 ---
    # 为我们的融合逻辑配置规则 (现在需要通过 FusedCancunVM 来访问)
    FusedCancunVM._state_class.computation_class.configure_rules(RULES_TO_TEST)
    
    # ======================= 3. 直接使用导入的 FusedCancunVM =======================
    Chain_Debug_Config = Chain.configure(
        __name__="Chain_Debug_Cfg",
        vm_configuration=((constants.GENESIS_BLOCK_NUMBER, FusedCancunVM),)
    )

    # --- 日志配置 ---
    # 4. 日志记录器现在也引用最终的 VM 来找到正确的 computation logger
    computation_logger = logging.getLogger(FusedCancunVM._state_class.computation_class.logger.name)
    computation_logger.setLevel(1)
    if not computation_logger.handlers:
        handler = logging.FileHandler(OUTPUT_LOG_FILE, mode='w', encoding='utf-8')
        formatter = logging.Formatter('[%(levelname)s] %(message)s')
        handler.setFormatter(formatter)
        computation_logger.addHandler(handler)
    print(f"[INFO] 已配置日志处理器，所有详细输出将被写入到: {os.path.abspath(OUTPUT_LOG_FILE)}")


    # --- 准备交易和状态 (这部分不变) ---
    private_key_bytes = b'\x01' * 32
    private_key = keys.PrivateKey(private_key_bytes)
    test_account_address = private_key.public_key.to_canonical_address()
    
    contract_bytecode = fetch_bytecode(CONTRACT_ADDRESS)
    if not contract_bytecode: return

    genesis_params = {"difficulty": 0, "mix_hash": b'\x00' * 32, "gas_limit": 8_000_000, "timestamp": int(time.time())}
    genesis_state = {
        to_canonical_address(test_account_address): {"balance": 10**22, "nonce": 0, "code": b'', "storage": {}},
        to_canonical_address(CONTRACT_ADDRESS): {"balance": 0, "nonce": 1, "code": contract_bytecode, "storage": {}},
    }

    db = AtomicDB()
    chain = Chain_Debug_Config.from_genesis(db, genesis_params, genesis_state)
    vm = chain.get_vm()

    sender_nonce = vm.state.get_nonce(to_canonical_address(test_account_address))
    unsigned_tx = vm.create_unsigned_transaction(nonce=sender_nonce, gas_price=10**10, gas=500_000, to=to_canonical_address(CONTRACT_ADDRESS), value=0, data=decode_hex(INPUT_DATA))
    signed_tx = unsigned_tx.as_signed_transaction(private_key)

    # --- 执行交易 (这部分不变) ---
    print("\n--- 开始执行交易，请等待执行结束... ---")
    header = chain.get_block().header
    receipt, computation = vm.apply_transaction(header, signed_tx)

    print("\n--- 执行结束 ---")
    if computation.is_error:
        print(f"交易失败，错误: {computation.error}")
    else:
        print("交易成功执行！")
    
    print("\n--- 融合规则触发次数总结 ---")
    if hasattr(computation, 'fusion_hit_counts') and computation.fusion_hit_counts:
        for rule_name, count in computation.fusion_hit_counts.items():
            print(f"  规则 '{rule_name}': 触发了 {count} 次")
    else:
        print("  没有任何融合规则被触发。")


if __name__ == "__main__":
    main_debug()