import os
import sys
import time
import pandas as pd
import json
from typing import Optional, Tuple, Any

# 新增: 导入tqdm用于显示进度条
from tqdm import tqdm
# 新增: 导入logging模块用于记录错误到文件
import logging

# --- 路径修复 (确保能找到所有模块) ---
# 这几行代码现在至关重要，它能确保 Python 找到我们的 custom_forks 目录
current_script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_script_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

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
    from custom_computation import FusedComputation, IdenticalComputation
    from fused_cancun.computation import FusedCancunComputation
    OriginalComputation = IdenticalComputation 

    # === 核心修改 1: 使用更清晰的变量名来定义控制组和实验组 ===
    # 控制组/基准：使用我们“什么都没做”的子类，以获得最精确的对比基准
    ControlComputation = IdenticalComputation
    # 实验组：使用我们真正实现了融合逻辑的类
    ExperimentComputation = FusedCancunComputation
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
    # === 新增：一个用来汇总所有计数结果的字典 ===
    total_fusion_hits = {}

    # --- 设定要测试的 fused opcode ---
    rules_to_test = ["SUB_MUL"]
    ExperimentComputation.configure_rules(rules_to_test)
    print(f"当前测试的 fused opcodes 为{rules_to_test}")

    # --- 主要配置 ---
    csv_path = "200k_transactions_with_inputs.csv" 
    max_transactions_to_process = 100
    # 是否为正式测试的交易生成详细的 opcode trace 文件
    ENABLE_DETAILED_TRACING = False
    # 是否启用热身阶段来消除系统预热效应
    ENABLE_WARMUP = True

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
    # 控制组VM，使用 ControlComputation
    class VM_Control(CancunVM):
        computation_class = ControlComputation
    Chain_Control_Config = Chain.configure(__name__="Chain_Control_Cfg", vm_configuration=((constants.GENESIS_BLOCK_NUMBER, VM_Control),))

    # === 核心修改 3: 实验组VM必须使用 ExperimentComputation ===
    # 你之前的代码在这里错误地使用了 IdenticalComputation，导致没有融合被执行
    # class VM_Experiment(CancunVM):
    #     computation_class = ExperimentComputation

    # 直接用我们新定义的 fork 作为实验组的虚拟机
    from CustomForks.fused_cancun import FusedCancunVM as VM_Experiment
    Chain_Experiment_Config = Chain.configure(__name__="Chain_Experiment_Cfg", vm_configuration=((constants.GENESIS_BLOCK_NUMBER, VM_Experiment),))
    
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
            chain_tx_setup = Chain_Control_Config.from_genesis(db_tx_setup, current_genesis_params, current_genesis_state)
            vm_tx_setup = chain_tx_setup.get_vm()
            
            sender_nonce_for_tx = vm_tx_setup.state.get_nonce(to_canonical_address(test_account.address))
            unsigned_tx = vm_tx_setup.create_unsigned_transaction(nonce=sender_nonce_for_tx, gas_price=tx_gas_price, gas=tx_gas_limit, to=to_canonical_address(target_contract_hex), value=tx_value, data=tx_data)
            signer_private_key = keys.PrivateKey(test_account.key)
            signed_tx_object = unsigned_tx.as_signed_transaction(signer_private_key)
                
            # ---- 插入热身阶段 ----
            if ENABLE_WARMUP:
                # 热身阶段现在也使用更清晰的命名
                db_warmup_ctrl = AtomicDB()
                chain_warmup_ctrl = Chain_Control_Config.from_genesis(db_warmup_ctrl, current_genesis_params, current_genesis_state)
                run_and_time_transaction(chain_warmup_ctrl, signed_tx_object, enable_tracing=False)

                db_warmup_exp = AtomicDB()
                chain_warmup_exp = Chain_Experiment_Config.from_genesis(db_warmup_exp, current_genesis_params, current_genesis_state)
                run_and_time_transaction(chain_warmup_exp, signed_tx_object, enable_tracing=False)

            # --- 正式计时测试 ---
            # 1. 执行控制组 (Control)
            db_ctrl_run = AtomicDB()
            chain_ctrl_instance = Chain_Control_Config.from_genesis(db_ctrl_run, current_genesis_params, current_genesis_state)
            trace_ctrl_path = None
            if ENABLE_DETAILED_TRACING:
                tx_hash_for_file = tx_hash.replace("0x", "")[:12] if isinstance(tx_hash, str) else f"idx{idx}"
                short_contract_hex = target_contract_hex.replace("0x", "")[:8]
                trace_ctrl_path = os.path.join(output_dir, f"trace_控制组_{short_contract_hex}_{tx_hash_for_file}.txt")
            
            # === 核心修改：填充了这里的参数 ===
            dur_ctrl, suc_ctrl, rec_ctrl, _ = run_and_time_transaction(
                chain_instance=chain_ctrl_instance,
                signed_tx=signed_tx_object,
                enable_tracing=ENABLE_DETAILED_TRACING,
                trace_filepath=trace_ctrl_path
            )

            # 2. 执行实验组 (Experiment)
            db_exp_run = AtomicDB()
            chain_exp_instance = Chain_Experiment_Config.from_genesis(db_exp_run, current_genesis_params, current_genesis_state)
            trace_exp_path = None
            if ENABLE_DETAILED_TRACING:
                tx_hash_for_file = tx_hash.replace("0x", "")[:12] if isinstance(tx_hash, str) else f"idx{idx}"
                short_contract_hex = target_contract_hex.replace("0x", "")[:8]
                trace_exp_path = os.path.join(output_dir, f"trace_实验组_{short_contract_hex}_{tx_hash_for_file}.txt")

            # === 核心修改：填充了这里的参数 ===
            dur_exp, suc_exp, rec_exp, comp_exp = run_and_time_transaction(
                chain_instance=chain_exp_instance,
                signed_tx=signed_tx_object,
                enable_tracing=ENABLE_DETAILED_TRACING,
                trace_filepath=trace_exp_path
            )
            
            # --- 记录结果 ---
            if suc_ctrl and suc_exp:
                 all_tx_benchmark_results.append({
                    "tx_hash": tx_hash, 
                    "avg_time_original_ms": dur_ctrl, # 使用控制组作为原始时间
                    "avg_time_fused_ms": dur_exp,    # 使用实验组作为融合时间
                    "avg_gas_original": rec_ctrl.gas_used if rec_ctrl else None,
                    "avg_gas_fused": rec_exp.gas_used if rec_exp else None,
                 })
                 if comp_exp and hasattr(comp_exp, 'fusion_hit_counts'):
                    for rule_name, count in comp_exp.fusion_hit_counts.items():
                        total_fusion_hits[rule_name] = total_fusion_hits.get(rule_name, 0) + count
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

    # === 关键修改：打印融合规则的触发次数总结 ===
    print("\n--- 融合规则触发次数总结 ---")
    if total_fusion_hits:
        for rule_name, count in total_fusion_hits.items():
            print(f"  规则 '{rule_name}': 在所有成功交易中总共触发了 {count} 次")
    else:
        print("  在所有成功比较的交易中，没有任何融合规则被触发。")


if __name__ == "__main__":
    if 'Halt' not in globals(): Halt = type('Halt', (Exception,), {})
    if 'InvalidOpcode' not in globals(): InvalidOpcode = lambda op_val: type('InvalidOpcode', (object,), {'mnemonic': f'INVALID(0x{op_val:02x})'})()
    if 'NO_RESULT' not in globals(): NO_RESULT = object()
    if 'BaseComputationAPI' not in globals(): from eth.abc import ComputationAPI as BaseComputationAPI
        
    main_benchmark_from_csv()
