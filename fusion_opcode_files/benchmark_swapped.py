import os
import time
import pandas as pd
import json
from typing import Optional, Tuple, Any

# 新增: 导入tqdm用于显示进度条
from tqdm import tqdm
# 新增: 导入logging模块用于记录错误到文件
import logging

from contextlib import redirect_stdout, redirect_stderr

from eth.chains.base import Chain
from eth.db.atomic import AtomicDB
from eth import constants
from eth_utils import to_canonical_address, decode_hex, is_hex
from eth_account import Account
from eth_keys import keys
import sys
import traceback

# --- 日志和错误记录配置 ---
def setup_error_logger(log_file='benchmark_errors.log'):
    """配置一个专门用来记录错误的 logger"""
    # 'w' 表示每次运行都覆盖旧日志, 'a' 表示追加
    handler = logging.FileHandler(log_file, mode='w')
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - TX_HASH: %(name)s - %(message)s')
    handler.setFormatter(formatter)
    
    logger = logging.getLogger('benchmark_error_logger')
    # 防止日志消息被传播到根 logger，避免在控制台重复输出
    logger.propagate = False 
    logger.setLevel(logging.ERROR)
    
    # 如果 logger 已经有 handler，先清除，防止重复添加
    if logger.hasHandlers():
        logger.handlers.clear()
        
    logger.addHandler(handler)
    return logger

error_logger = setup_error_logger()


# --- 配置: 用户需要确保这些路径和类是正确的 ---
try:
    from custom_computation import FusedComputation, BaseComputationForFusion, IdenticalComputation
    OriginalComputation = BaseComputationForFusion 
except ImportError:
    print("严重错误: 无法从 custom_computation.py 导入 FusedComputation 或 BaseComputationForFusion。")
    sys.exit(1)

try:
    from eth.vm.forks.cancun import CancunVM
except ImportError:
    print("严重错误: 无法导入基础EVM (例如 CancunVM)。请确保 py-evm 已正确安装。")
    sys.exit(1)

try:
    from db_utils import fetch_bytecode
except ImportError:
    print("严重错误: 无法从 db_utils.py 导入 fetch_bytecode。")
    sys.exit(1)


# --- 辅助类和函数 ---

test_account = Account.create("csv_benchmark_tx_sender_chinese")

def prepare_genesis_state(target_contract_address_hex: str, sender_address: str, contract_bytecode: bytes):
    owner_storage_slot = 0 
    owner_value = int(sender_address, 16)
    genesis_state = {
        to_canonical_address(sender_address): {"balance": 10**22, "nonce": 0, "code": b"", "storage": {}},
        to_canonical_address(target_contract_address_hex): {"balance": 0, "nonce": 1, "code": contract_bytecode, "storage": {owner_storage_slot: owner_value}},
    }
    return genesis_state


def run_and_time_transaction(
    chain_instance: Chain,
    signed_tx: Any,
    enable_tracing: bool = False,
    trace_filepath: Optional[str] = None,
) -> Tuple[Optional[float], bool, Optional[Any], Optional[Any]]:
    
    vm = chain_instance.get_vm()
    block_header_for_tx = chain_instance.get_block().header 

    computation_result = None
    receipt_result = None
    duration_ms = None
    success_status = False

    def _execute_transaction():
        nonlocal receipt_result, computation_result
        receipt_result, computation_result = vm.apply_transaction(block_header_for_tx, signed_tx)

    try:
        start_time = time.perf_counter()

        if enable_tracing and trace_filepath:
            with open(trace_filepath, "w", encoding="utf-8") as trace_file:
                # 同时重定向 stdout 和 stderr 到 trace 文件
                # 这样可以捕获所有类型的输出，包括 py-evm 可能的 debug 日志
                with redirect_stdout(trace_file), redirect_stderr(trace_file):
                    _execute_transaction()
        else:
            _execute_transaction()

        end_time = time.perf_counter()
        duration_ms = (end_time - start_time) * 1000
        success_status = computation_result is not None and not computation_result.is_error
    
    except Exception:
        # 当执行失败时，不在这里处理或打印
        # 直接将 success_status 设为 False，由上层调用者决定如何记录
        success_status = False

    return duration_ms, success_status, receipt_result, computation_result


def main_benchmark_from_csv():
    # --- 设定要测试的 fused opcode ---
    # rules_to_test = ["SUB_MUL"]
    # FusedComputation.configure_rules(rules_to_test)
    # print(f"当前测试的 fused opcodes 为{rules_to_test}")

    # --- 主要配置 ---
    csv_path = "200k_transactions_with_inputs.csv" 
    max_transactions_to_process = 200
    ENABLE_DETAILED_TRACING = True

    print(f"正在从CSV文件加载交易: {csv_path}")
    try:
        df = pd.read_csv(csv_path, low_memory=False)
        if max_transactions_to_process is not None and max_transactions_to_process > 0 :
            df = df.head(max_transactions_to_process)
        print(f"已加载 {len(df)} 笔交易用于基准测试。")
        print(f"所有错误和详细堆栈信息将被记录到: {os.path.abspath('benchmark_errors.log')}")
    except FileNotFoundError:
        print(f"严重错误: CSV文件未找到 - {csv_path}")
        return
    except Exception as e:
        print(f"严重错误: 加载CSV文件时出错: {e}")
        return

    # --- VM 和 Chain 配置 ---
    class VM_Original_CSV(CancunVM): computation_class = OriginalComputation
    Chain_Original_Config = Chain.configure(__name__="Chain_Original_CSV_Cfg", vm_configuration=((constants.GENESIS_BLOCK_NUMBER, VM_Original_CSV),))
    class VM_Fused_CSV(CancunVM): computation_class = IdenticalComputation
    Chain_Fused_Config = Chain.configure(__name__="Chain_Fused_CSV_Cfg", vm_configuration=((constants.GENESIS_BLOCK_NUMBER, VM_Fused_CSV),))

    all_tx_benchmark_results = []
    output_dir = "csv_benchmark_traces_output_cn"
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n用于所有交易的发送方账户: {test_account.address}\n")

    # --- 主循环，使用 tqdm 显示进度条 ---
    progress_bar = tqdm(df.iterrows(), total=len(df), desc="处理交易中", unit="tx")
    for idx, row in progress_bar:
        tx_hash = None
        signed_tx_object = None # 用于在 except 块中引用
        try:
            tx_hash = row.get('transactionHash', f'csv_row_{idx}')
            
            target_contract_hex = row.get('to')
            calldata_str = str(row.get('inputData', '0x'))

            if pd.isna(target_contract_hex) or not isinstance(target_contract_hex, str) or not is_hex(target_contract_hex):
                raise ValueError(f"无效或缺失 'to' 地址 ('{target_contract_hex}')")
            
            contract_bytecode = fetch_bytecode(target_contract_hex)
            if not contract_bytecode:
                raise ValueError(f"未能获取合约 {target_contract_hex} 的字节码或字节码为空")

            tx_value = int(float(str(row.get("value", "0"))))
            tx_gas_limit = int(float(str(row.get("gasLimit", "5000000")).replace(",", "")))
            tx_gas_price = int(float(str(row.get("gasPrice", "10000000000")).replace(",", "")))
            tx_data = decode_hex(calldata_str)

            current_genesis_params = {"difficulty": 0, "mix_hash": b'\x00' * 32, "gas_limit": max(tx_gas_limit + 1_000_000, 7_000_000), "timestamp": int(row.get("timestamp", time.time()))}
            current_genesis_state = prepare_genesis_state(target_contract_hex, test_account.address, contract_bytecode)
            
            db_tx_setup = AtomicDB()
            chain_tx_setup = Chain_Original_Config.from_genesis(db_tx_setup, current_genesis_params, current_genesis_state)
            vm_tx_setup = chain_tx_setup.get_vm()
            
            sender_nonce_for_tx = vm_tx_setup.state.get_nonce(to_canonical_address(test_account.address))
            unsigned_tx = vm_tx_setup.create_unsigned_transaction(nonce=sender_nonce_for_tx, gas_price=tx_gas_price, gas=tx_gas_limit, to=to_canonical_address(target_contract_hex), value=tx_value, data=tx_data)
            signer_private_key = keys.PrivateKey(test_account.key)
            signed_tx_object = unsigned_tx.as_signed_transaction(signer_private_key)

            # -- 执行融合VM --
            db_fused_run = AtomicDB()
            chain_fused_instance = Chain_Fused_Config.from_genesis(db_fused_run, current_genesis_params, current_genesis_state)
            trace_fused_path = None
            if ENABLE_DETAILED_TRACING:
                tx_hash_for_file = tx_hash.replace("0x", "")[:12] if isinstance(tx_hash, str) else f"idx{idx}"
                trace_fused_path = os.path.join(output_dir, f"trace_融合_{tx_hash_for_file}.txt")

            dur_fused, suc_fused, rec_fused, _ = run_and_time_transaction(chain_fused_instance, signed_tx_object, enable_tracing=ENABLE_DETAILED_TRACING, trace_filepath=trace_fused_path)
            

            # -- 执行原始VM --
            db_orig_run = AtomicDB()
            chain_orig_instance = Chain_Original_Config.from_genesis(db_orig_run, current_genesis_params, current_genesis_state)
            trace_orig_path = None
            if ENABLE_DETAILED_TRACING:
                tx_hash_for_file = tx_hash.replace("0x", "")[:12] if isinstance(tx_hash, str) else f"idx{idx}"
                trace_orig_path = os.path.join(output_dir, f"trace_原始_{tx_hash_for_file}.txt")
            
            dur_orig, suc_orig, rec_orig, _ = run_and_time_transaction(chain_orig_instance, signed_tx_object, enable_tracing=ENABLE_DETAILED_TRACING, trace_filepath=trace_orig_path)


            if suc_orig and suc_fused:
                 all_tx_benchmark_results.append({
                    "tx_hash": tx_hash, "avg_time_original_ms": dur_orig, "avg_time_fused_ms": dur_fused,
                    "avg_gas_original": rec_orig.gas_used if rec_orig else None,
                    "avg_gas_fused": rec_fused.gas_used if rec_fused else None,
                 })
            # 如果有任何一个执行失败 (但没有抛出致命异常)，则忽略这笔交易，不计入成功也不计入失败日志
            # 这通常意味着是一个可控的 REVERT

        except Exception as e_main_loop:
            # 只有当准备过程或执行过程中发生致命的、未被预料的错误时，才记录到日志
            logger = logging.getLogger(tx_hash or f"csv_row_{idx}")
            logger.error(f"处理交易时发生致命错误: {e_main_loop}", exc_info=True)
            continue

    # --- 最终结果分析与输出 ---
    print("\n\n--- 最终批量基准测试总结 ---")
    valid_comparisons = len(all_tx_benchmark_results)
    
    if valid_comparisons > 0:
        total_abs_improvement_ms = sum(res["avg_time_original_ms"] - res["avg_time_fused_ms"] for res in all_tx_benchmark_results)
        total_percent_improvement = sum(
            ((res["avg_time_original_ms"] - res["avg_time_fused_ms"]) / res["avg_time_original_ms"]) * 100 
            for res in all_tx_benchmark_results if res["avg_time_original_ms"] > 0
        )
        
        print(f"\n基于 {valid_comparisons} 笔成功比较的交易:")
        print(f"  平均绝对时间节省 (每笔交易): {(total_abs_improvement_ms / valid_comparisons):.4f} ms")
        print(f"  平均百分比提升: {(total_percent_improvement / valid_comparisons):.2f}%")
        
        output_summary_filepath = os.path.join(output_dir, "benchmark_successful_transactions.json")
        try:
            with open(output_summary_filepath, "w", encoding="utf-8") as f_out:
                json.dump(all_tx_benchmark_results, f_out, indent=4)
            print(f"\n所有成功的基准测试结果已保存到: {output_summary_filepath}")
        except Exception as e_json:
            print(f"\n保存成功总结JSON文件时出错: {e_json}")

    else:
        print("\n没有可用于比较的成功交易。请检查 benchmark_errors.log 文件分析失败原因。")


if __name__ == "__main__":
    if 'Halt' not in globals(): Halt = type('Halt', (Exception,), {})
    if 'InvalidOpcode' not in globals(): InvalidOpcode = lambda op_val: type('InvalidOpcode', (object,), {'mnemonic': f'INVALID(0x{op_val:02x})'})()
    if 'NO_RESULT' not in globals(): NO_RESULT = object()
    if 'BaseComputationAPI' not in globals(): from eth.abc import ComputationAPI as BaseComputationAPI
        
    main_benchmark_from_csv()
