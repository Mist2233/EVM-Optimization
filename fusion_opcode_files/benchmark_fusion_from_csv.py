import os
import time
import pandas as pd
import json
from typing import Optional, Tuple, Any, List, Dict # 增加了更多类型

from eth.chains.base import Chain
from eth.db.atomic import AtomicDB
from eth import constants
from eth_utils import to_canonical_address, decode_hex, is_hex
from eth_account import Account
from eth_keys import keys
import sys # 用于 sys.stdout 重定向和 sys.path

# --- 配置: 用户需要确保这些路径和类是正确的 ---

# 1. 如果你的工具模块在不同的位置，请调整 sys.path
#    示例: 如果 db_utils.py 和 custom_computation.py 在上一级目录
# current_script_dir = os.path.dirname(os.path.abspath(__file__))
# parent_dir = os.path.dirname(current_script_dir)
# if parent_dir not in sys.path:
#     sys.path.insert(0, parent_dir)

# 2. 导入你实际的 Computation 类和基础 VM
try:
    # 假设 custom_computation.py 定义了 FusedComputation 和一个 BaseComputationForFusion
    # BaseComputationForFusion 应该是你目标分叉的标准 py-evm Computation 类
    from fusion_opcode_files.custom_computation_origin import FusedComputation, BaseComputationForFusion 
    OriginalComputation = BaseComputationForFusion 
except ImportError:
    print("严重错误: 无法从 custom_computation.py 导入 FusedComputation 或 BaseComputationForFusion。")
    print("请确保 custom_computation.py 文件存在且结构正确。")
    sys.exit(1)

try:
    from eth.vm.forks.cancun import CancunVM # 或你目标分叉的 VM, 例如 LondonVM
except ImportError:
    print("严重错误: 无法导入基础EVM (例如 CancunVM)。请确保 py-evm 已正确安装。")
    sys.exit(1)

# 3. 导入你的工具函数
try:
    from db_utils import fetch_bytecode
except ImportError:
    print("严重错误: 无法从 db_utils.py 导入 fetch_bytecode。")
    sys.exit(1)

# 4. 为 FusedComputation 设置 FUSION_RULES 和常量 (如果它们没有在类定义内部设置)
# 这确保 FusedComputation 可以访问它需要的规则。
if not hasattr(FusedComputation, 'FUSION_RULES'):
    print("提示: FUSION_RULES 未在 FusedComputation 上作为类属性找到。正在设置默认的示例规则。")
    PUSH2_OPCODE = 0x61
    JUMP_OPCODE = 0x56
    SUB_OPCODE = 0x03
    MUL_OPCODE = 0x02
    UJUMP2_VIRTUAL_OPCODE = 0xB0 
    SUBMUL_VIRTUAL_OPCODE = 0xB1
    # 这应该与你的 FusedComputation.apply_computation 内部使用的常量匹配
    FusedComputation.FUSION_RULES = {
        PUSH2_OPCODE: [{"pattern_opcodes": (JUMP_OPCODE,), "trigger_arg_bytes": 2, "pattern_bytes": 1, "fused_opcode_id": UJUMP2_VIRTUAL_OPCODE, "fused_mnemonic": "UJUMP2_FUSED"}],
        SUB_OPCODE: [{"pattern_opcodes": (MUL_OPCODE,), "trigger_arg_bytes": 0, "pattern_bytes": 1, "fused_opcode_id": SUBMUL_VIRTUAL_OPCODE, "fused_mnemonic": "SUBMUL_FUSED"}],
    }
    # 确保如果 FusedComputation 通过 cls. 来使用这些常量，它们也被设置了
    FusedComputation.UJUMP2_OPCODE_CONST = UJUMP2_VIRTUAL_OPCODE
    FusedComputation.SUBMUL_OPCODE_CONST = SUBMUL_VIRTUAL_OPCODE
    FusedComputation.PUSH2_OPCODE = PUSH2_OPCODE # 示例
    FusedComputation.JUMP_OPCODE = JUMP_OPCODE # 示例
    FusedComputation.SUB_OPCODE = SUB_OPCODE   # 示例
    FusedComputation.MUL_OPCODE = MUL_OPCODE   # 示例


# --- 辅助类和函数 ---
class SilentFileWriter:
    def __init__(self, filename, mode="w"):
        self.file = open(filename, mode, encoding="utf-8")
        self.original_stdout = sys.stdout
    def write(self, text):
        self.file.write(text)
        self.file.flush()
    def flush(self): self.file.flush()
    def __enter__(self):
        sys.stdout = self
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.file and not self.file.closed:
            self.file.close()
        sys.stdout = self.original_stdout

test_account = Account.create("csv_benchmark_tx_sender_chinese") # 交易发送方

def prepare_genesis_state(target_contract_address_hex: str, sender_address: str, contract_bytecode: bytes):
    # 找到 owner 变量的存储插槽 (这需要一些技巧，但通常对于简单的合约是 slot 0)
    owner_storage_slot = 0 
    # 把你的测试账户地址编码成32字节的值
    owner_value = int(sender_address, 16)

    """为测试账户和目标合约准备Genesis状态 (字节码从数据库获取)"""
    genesis_state = {
        to_canonical_address(sender_address): {"balance": 10**22, "nonce": 0, "code": b"", "storage": {}}, # 增加了余额
        to_canonical_address(target_contract_address_hex): {"balance": 0, "nonce": 1, "code": contract_bytecode, "storage": {owner_storage_slot: owner_value}}, # 合约的nonce通常是1（如果已部署）
    }
    return genesis_state

def run_and_time_transaction(
    chain_instance: Chain,
    signed_tx: Any, # SignedTransactionAPI
    description: str,
    enable_tracing: bool = False,
    trace_filepath: Optional[str] = None,
    verbose_console: bool = True
) -> Tuple[Optional[float], bool, Optional[Any], Optional[Any]]: # duration_ms, success, receipt, computation
    
    vm = chain_instance.get_vm()
    # 获取合适的 block_header 来执行交易
    block_header_for_tx = chain_instance.get_block().header 

    computation_result = None
    receipt_result = None
    duration_ms = None
    success_status = False
    
    if verbose_console: print(f"\n--- 开始执行: {description} ---")
    
    stdout_wrapper = None
    original_stdout_backup = sys.stdout # 备份原始stdout
    try:
        if enable_tracing and trace_filepath:
            if verbose_console: print(f"详细跟踪将输出到: {trace_filepath}")
            stdout_wrapper = SilentFileWriter(trace_filepath, mode="w") # 创建写入器实例
            sys.stdout = stdout_wrapper # 重定向
        
        start_time = time.perf_counter()
        receipt_result, computation_result = vm.apply_transaction(block_header_for_tx, signed_tx)
        end_time = time.perf_counter()
        duration_ms = (end_time - start_time) * 1000
        success_status = computation_result is not None and not computation_result.is_error

    except Exception as e:
        if verbose_console: print(f"  执行交易时出错 ({description}): {e}")
        import traceback

        # 从异常对象中提取traceback信息
        tb = traceback.extract_tb(e.__traceback__)
        # 获取traceback中最后一个（即最深层的）帧，并拿到它的文件名
        failing_file_path = tb[-1].filename

        print("\n" + "="*20 + " 深度调试信息 " + "="*20)
        print(f"[!!!] 异常发生的真实文件路径是: {failing_file_path}")
        print(f"[!!!] 异常发生的真实代码行号是: {tb[-1].lineno}")
        print("="*55 + "\n")

        traceback.print_exc() # 打印完整的回溯信息以帮助调试
        success_status = False
    finally:
        if stdout_wrapper: # 如果创建了写入器实例
            sys.stdout = original_stdout_backup # 恢复 stdout
            if stdout_wrapper.file and not stdout_wrapper.file.closed: # 确保文件未关闭才关闭
                 stdout_wrapper.file.close()

    status_msg = "成功" if success_status else f"失败 ({computation_result.error if computation_result else '未知错误'})"
    gas_used_msg = receipt_result.gas_used if receipt_result else "N/A"
    
    if verbose_console:
        print(f"执行状态 ({description}): {status_msg}")
        print(f"Gas 使用量 ({description}): {gas_used_msg}")
        print(f"执行时间 ({description}): {duration_ms:.4f} ms" if duration_ms is not None else "N/A")
    
    return duration_ms, success_status, receipt_result, computation_result


def main_benchmark_from_csv():
    # --- Debug Mode Switch ---
    DEBUG_MODE_ENABLED = False  # <<<< 用户: 设置为 True 以启用调试模式 (打印更多信息)
    DEBUG_TX_HASH = "0x4bfa4e2d959b4ac7ba0a5985b4e1f90bd5d1471e7fbcba339975eed3e1f634b8"
    # --- End Debug Mode Switch ---

    csv_path = "test_transactions.csv"  # 你的CSV文件路径
    max_transactions_to_process = 100  # <<<< 用户: 调整此值以处理更多/更少的交易
    num_runs_per_tx = 1              # <<<< 用户: 每次交易的重复运行次数以求平均 (设为1以加快CSV遍历)
    
    # 批量测试时是否生成详细的EVM trace文件 (只为每笔交易的第一轮生成)
    ENABLE_DETAILED_TRACING = False  # <<<< 用户: 设置为 True 以生成trace文件

    print(f"正在从CSV文件加载交易: {csv_path}")
    try:
        df = pd.read_csv(csv_path, low_memory=False)
        if max_transactions_to_process is not None and max_transactions_to_process > 0 :
            df = df.head(max_transactions_to_process)
        print(f"已加载 {len(df)} 笔交易用于基准测试。")
    except FileNotFoundError:
        print(f"严重错误: CSV文件未找到 - {csv_path}")
        return
    except Exception as e:
        print(f"严重错误: 加载CSV文件时出错: {e}")
        return

    # --- VM 和 Chain 配置 (只需要配置一次) ---
    # 确保 CancunVM, OriginalComputation, FusedComputation 已正确定义/导入
    class VM_Original_CSV(CancunVM):
        computation_class = OriginalComputation
    Chain_Original_Config = Chain.configure(
        __name__="Chain_Original_CSV_Cfg",
        vm_configuration=((constants.GENESIS_BLOCK_NUMBER, VM_Original_CSV),)
    )

    class VM_Fused_CSV(CancunVM):
        computation_class = FusedComputation
    Chain_Fused_Config = Chain.configure(
        __name__="Chain_Fused_CSV_Cfg",
        vm_configuration=((constants.GENESIS_BLOCK_NUMBER, VM_Fused_CSV),)
    )
    # --- 配置结束 ---

    all_tx_benchmark_results = []
    output_dir = "csv_benchmark_traces_output_cn" # 新的输出目录
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n用于所有交易的发送方账户: {test_account.address}")

    for idx, row in df.iterrows():
        tx_hash = row.get('transactionHash', f'csv_row_{idx}')
        
        # --- Debug Mode Start ---
        if DEBUG_MODE_ENABLED and tx_hash != DEBUG_TX_HASH:
            continue

        if DEBUG_MODE_ENABLED and tx_hash == DEBUG_TX_HASH:
            print(f"\n/!\\ 进入单交易调试模式: {tx_hash} /!\\")
            # 在调试模式下，强制开启详细日志，并且只运行一次
            num_runs_per_tx = 1
            ENABLE_DETAILED_TRACING = True
        # --- Debug Mode End ---
        
        print(f"\n[{idx + 1}/{len(df)}] 处理交易哈希: {tx_hash}")

        target_contract_hex = row.get('to')
        calldata_str = str(row.get('inputData', '0x')) # 确保是字符串

        if pd.isna(target_contract_hex) or not isinstance(target_contract_hex, str) or not is_hex(target_contract_hex):
            print(f"  跳过交易 {tx_hash}: 无效或缺失 'to' 地址 ('{target_contract_hex}').")
            all_tx_benchmark_results.append({"tx_hash": tx_hash, "error": "无效的 'to' 地址"})
            continue
        
        contract_bytecode = fetch_bytecode(target_contract_hex)
        if not contract_bytecode:
            print(f"  跳过交易 {tx_hash}: 未能获取合约 {target_contract_hex} 的字节码或字节码为空。")
            all_tx_benchmark_results.append({"tx_hash": tx_hash, "contract": target_contract_hex, "error": "字节码未找到或为空"})
            continue

        try:
            tx_value = int(float(str(row.get("value", "0"))))
            tx_gas_limit = int(float(str(row.get("gasLimit", "5000000")).replace(",", ""))) # 增加默认值
            tx_gas_price = int(float(str(row.get("gasPrice", "10000000000")).replace(",", ""))) # 10 Gwei
            tx_data = decode_hex(calldata_str)
        except ValueError as ve:
            print(f"  跳过交易 {tx_hash}: 解析交易参数时出错 - {ve}")
            all_tx_benchmark_results.append({"tx_hash": tx_hash, "contract": target_contract_hex, "error": f"参数解析错误: {ve}"})
            continue

        # 这是修改后的正确代码
        current_genesis_params = {
            "difficulty": 0,  # <<<< 关键修改：对于 PoS 分叉 (如 Cancun), difficulty 必须为 0
            "mix_hash": b'\x00' * 32, # <<<< 关键补充：PoS 分叉需要 prev_randao 字段，用32个零字节作为创世块的默认值
            "gas_limit": max(tx_gas_limit + 1_000_000, 7_000_000), 
            "timestamp": int(row.get("timestamp", time.time()))
        }
        current_genesis_state = prepare_genesis_state(target_contract_hex, test_account.address, contract_bytecode)
        
        temp_db_tx = AtomicDB()
        temp_chain_tx = Chain_Original_Config.from_genesis(temp_db_tx, current_genesis_params, current_genesis_state)
        temp_vm_tx = temp_chain_tx.get_vm()
        
        try:
            sender_nonce_for_tx = temp_vm_tx.state.get_nonce(to_canonical_address(test_account.address))
            unsigned_tx = temp_vm_tx.create_unsigned_transaction(
                nonce=sender_nonce_for_tx, gas_price=tx_gas_price, gas=tx_gas_limit,
                to=to_canonical_address(target_contract_hex), value=tx_value, data=tx_data,
            )
            signer_private_key = keys.PrivateKey(test_account.key)
            signed_tx = unsigned_tx.as_signed_transaction(signer_private_key)
        except Exception as e_tx_create:
            print(f"  跳过交易 {tx_hash}: 为 {target_contract_hex} 创建签名交易时出错 - {e_tx_create}")
            all_tx_benchmark_results.append({"tx_hash": tx_hash, "contract": target_contract_hex, "error": f"签名交易创建错误: {e_tx_create}"})
            continue
            
        tx_times_original, tx_times_fused = [], []
        tx_gas_original, tx_gas_fused = [], []
        
        short_contract_hex = target_contract_hex.replace("0x", "")[:8]
        tx_hash_for_file = tx_hash.replace("0x", "")[:12] if isinstance(tx_hash, str) else f"idx{idx}"

        print("\n--- 交易预校验深度诊断 ---")
        try:
            # 1. 检查 Intrinsic Gas (内在Gas)
            intrinsic_gas = signed_tx.intrinsic_gas
            print(f"[*] 交易提供的 Gas Limit: {signed_tx.gas}")
            print(f"[*] EVM计算出的内在Gas: {intrinsic_gas}")
            if signed_tx.gas < intrinsic_gas:
                print("\n[!!!] 问题定位: 交易的 gas_limit 低于其内在Gas成本!")
                print("      这通常是因为模拟的EVM版本与交易原始版本的Gas计算规则不同。")
                return # 找到问题，直接退出

            # 2. 检查账户余额
            sender_balance = temp_vm_tx.state.get_balance(signed_tx.sender)
            max_cost = signed_tx.gas * signed_tx.gas_price
            print(f"\n[*] 发送方账户余额: {sender_balance}")
            print(f"[*] 交易最高可能成本 (gas_limit * gas_price): {max_cost}")
            if sender_balance < max_cost:
                print("\n[!!!] 问题定位: 发送方余额不足以支付最高Gas费用!")
                return # 找到问题，直接退出

            # 3. 检查 Nonce
            vm_state_nonce = temp_vm_tx.state.get_nonce(signed_tx.sender)
            tx_nonce = signed_tx.nonce
            print(f"\n[*] 账户当前需要的 Nonce: {vm_state_nonce}")
            print(f"[*] 交易实际使用的 Nonce: {tx_nonce}")
            if vm_state_nonce != tx_nonce:
                print("\n[!!!] 问题定位: 交易Nonce与账户Nonce不匹配!")
                return # 找到问题，直接退出

            print("\n--- 诊断通过: 预校验各项参数符合要求，问题可能出在执行期间 ---")

        except Exception as e_diag:
            print(f"\n[!!!] 在执行诊断代码时发生意外错误: {e_diag}")
        # =============================================================

        print(f"  正在对交易 {tx_hash} 进行基准测试 ({num_runs_per_tx} 轮/每种VM)...")
        for run_i in range(num_runs_per_tx):
            # 1. 原始VM
            db_orig_run = AtomicDB()
            chain_orig_instance = Chain_Original_Config.from_genesis(db_orig_run, current_genesis_params, current_genesis_state)
            trace_orig_path = None
            if ENABLE_DETAILED_TRACING and run_i == 0:
                trace_orig_path = os.path.join(output_dir, f"trace_原始_{short_contract_hex}_{tx_hash_for_file}.txt")
            
            dur_orig, suc_orig, rec_orig, comp_orig = run_and_time_transaction(
                chain_orig_instance, signed_tx, f"原始VM (Tx {tx_hash_for_file}, 轮次 {run_i+1})",
                enable_tracing=(ENABLE_DETAILED_TRACING and run_i == 0),
                trace_filepath=trace_orig_path, verbose_console=False 
            )

            # 在调试模式下，如果执行失败，打印出 Computation 对象帮助分析
            if DEBUG_MODE_ENABLED and not suc_orig:
                print("\n--- 调试信息: 原始VM执行失败 ---")
                if comp_orig:
                    print(f"错误详情: {comp_orig.error}")
                    print(f"Gas 消耗: {comp_orig.gas_meter.gas_used}")
                    print(f"栈内容 (Stack): {comp_orig.stack_depth} items -> {comp_orig._stack.values}")
                    print(f"内存内容 (Memory): {comp_orig.memory_size} bytes")
                else:
                    print("Computation 对象未能创建，可能是在交易应用前就已出错。")
                
                # 如果只想调试，可以在这里直接退出
                print("调试结束，脚本退出。请检查上面的错误信息和生成的 trace 文件。")
                return # 直接退出函数

            if suc_orig and dur_orig is not None: 
                tx_times_original.append(dur_orig)
                if rec_orig: tx_gas_original.append(rec_orig.gas_used)

            # 2. 融合VM
            db_fused_run = AtomicDB()
            chain_fused_instance = Chain_Fused_Config.from_genesis(db_fused_run, current_genesis_params, current_genesis_state)
            trace_fused_path = None
            if ENABLE_DETAILED_TRACING and run_i == 0:
                trace_fused_path = os.path.join(output_dir, f"trace_融合_{short_contract_hex}_{tx_hash_for_file}.txt")

            dur_fused, suc_fused, rec_fused, _ = run_and_time_transaction(
                chain_fused_instance, signed_tx, f"融合VM (Tx {tx_hash_for_file}, 轮次 {run_i+1})",
                enable_tracing=(ENABLE_DETAILED_TRACING and run_i == 0),
                trace_filepath=trace_fused_path, verbose_console=False
            )
            if suc_fused and dur_fused is not None:
                tx_times_fused.append(dur_fused)
                if rec_fused: tx_gas_fused.append(rec_fused.gas_used)
        
        avg_t_orig = sum(tx_times_original) / len(tx_times_original) if tx_times_original else None
        avg_t_fused = sum(tx_times_fused) / len(tx_times_fused) if tx_times_fused else None
        avg_g_orig = sum(tx_gas_original) / len(tx_gas_original) if tx_gas_original else None
        avg_g_fused = sum(tx_gas_fused) / len(tx_gas_fused) if tx_gas_fused else None
        
        current_tx_result_summary = {
            "tx_hash": tx_hash, "contract_address": target_contract_hex, "calldata": calldata_str,
            "avg_time_original_ms": avg_t_orig, "avg_time_fused_ms": avg_t_fused,
            "avg_gas_original": avg_g_orig, "avg_gas_fused": avg_g_fused,
            "runs_original_success": len(tx_times_original), "runs_fused_success": len(tx_times_fused),
            "num_runs_configured": num_runs_per_tx
        }
        all_tx_benchmark_results.append(current_tx_result_summary)
        if avg_t_orig is not None and avg_t_fused is not None :
             print(f"  交易 {tx_hash} 平均结果: 原始时间={avg_t_orig:.2f}ms (Gas:{avg_g_orig}), 融合时间={avg_t_fused:.2f}ms (Gas:{avg_g_fused})")
        else:
            print(f"  交易 {tx_hash}: 未能完成足够的成功运行以进行比较。原始成功次数: {len(tx_times_original)}/{num_runs_per_tx}, 融合成功次数: {len(tx_times_fused)}/{num_runs_per_tx}")


    # --- 批量测试结果分析与输出 ---
    print("\n\n--- 最终批量基准测试总结 ---")
    valid_comparisons = 0
    total_abs_improvement_ms = 0
    total_percent_improvement = 0
    
    for res in all_tx_benchmark_results:
        if res.get("error"):
            print(f"交易哈希: {res['tx_hash']}, 合约: {res.get('contract','N/A')}, 错误: {res['error']}")
            continue
        
        if res["avg_time_original_ms"] is not None and res["avg_time_fused_ms"] is not None and res["avg_time_original_ms"] > 0:
            valid_comparisons += 1
            improvement_ms = res["avg_time_original_ms"] - res["avg_time_fused_ms"]
            percent_imp = (improvement_ms / res["avg_time_original_ms"]) * 100
            total_abs_improvement_ms += improvement_ms
            total_percent_improvement += percent_imp
            print(f"交易哈希: {res['tx_hash']} | 合约: {res['contract_address'][:18]}... | "
                  f"原始: {res['avg_time_original_ms']:.2f}ms (Gas:{res['avg_gas_original']}) | "
                  f"融合: {res['avg_time_fused_ms']:.2f}ms (Gas:{res['avg_gas_fused']}) | "
                  f"差异: {improvement_ms:.2f}ms ({percent_imp:.2f}%)")
        else:
            print(f"交易哈希: {res['tx_hash']} | 合约: {res['contract_address'][:18]}... | 数据不完整，无法比较。")

    if valid_comparisons > 0:
        print(f"\n基于 {valid_comparisons} 笔可比较的交易:")
        print(f"  平均绝对时间节省 (每笔交易): {(total_abs_improvement_ms / valid_comparisons):.2f} ms")
        print(f"  平均百分比提升: {(total_percent_improvement / valid_comparisons):.2f}%")
    else:
        print("\n没有足够的数据进行总体性能比较。")

    output_summary_filepath = os.path.join(output_dir, "benchmark_all_transactions_summary.json")
    try:
        with open(output_summary_filepath, "w", encoding="utf-8") as f_out:
            json.dump(all_tx_benchmark_results, f_out, indent=4, ensure_ascii=False)
        print(f"\n所有交易的详细基准测试结果已保存到: {output_summary_filepath}")
    except Exception as e_json:
        print(f"\n保存总结JSON文件时出错: {e_json}")


if __name__ == "__main__":
    # --- 确保必要的 Python 模块可用 ---
    # 你应该优先确保从 py-evm 或你的项目中正确导入这些
    # 这些是当真实导入在脚本的其他地方（例如 custom_computation.py）失败时的极简后备模拟，
    # 通常在结构良好的项目中，这些后备是不需要的。
    if 'Halt' not in globals(): Halt = type('Halt', (Exception,), {})
    if 'InvalidOpcode' not in globals(): InvalidOpcode = lambda op_val: type('InvalidOpcode', (object,), {'mnemonic': f'INVALID(0x{op_val:02x})'})() # noqa: E731
    if 'NO_RESULT' not in globals(): NO_RESULT = object() # py-evm 中用于预编译的哨兵值
    if 'BaseComputationAPI' not in globals(): # 为 MockComputation 提供基类
        from eth.abc import ComputationAPI as BaseComputationAPI
        
    main_benchmark_from_csv()