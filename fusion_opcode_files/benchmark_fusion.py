import time
import os
from eth.chains.base import Chain
from eth.db.atomic import AtomicDB
from eth import constants
from eth_utils import to_canonical_address, decode_hex, is_hex
from eth_account import Account
from eth_keys import keys
from typing import Optional

# 假设你的自定义 Computation 类和原始 Computation 类可以被导入
# from custom_computation import FusedComputation, PlaceholderBaseComputation # 或者你的实际基类
# from eth.vm.forks.cancun.computation import CancunComputation as OriginalComputation # 示例原始类

# ！！！你需要替换这些占位符为你项目中实际的类！！！
# 为了演示，我们假设 FusedComputation 和一个 OriginalComputation 已经定义
# 并且 FusedComputation 内部能访问到 FUSION_RULES
try:
    from custom_computation import FusedComputation, BaseComputationForFusion
    OriginalComputation = BaseComputationForFusion # 使用占位符作为原始
    # 实际项目中，OriginalComputation 应该是 py-evm 中标准的分叉 Computation 类
    # 例如：from eth.vm.forks.cancun.computation import CancunComputation as OriginalComputation
    
    # 在 FusedComputation 中定义或使其可访问 FUSION_RULES 和常量
    # 这只是一个示例，你可能在 custom_computation.py 中已经做好了
    if not hasattr(FusedComputation, 'FUSION_RULES'):
        PUSH2_OPCODE = 0x61
        JUMP_OPCODE = 0x56
        SUB_OPCODE = 0x03
        MUL_OPCODE = 0x02
        UJUMP2_VIRTUAL_OPCODE = 0xB0 
        SUBMUL_VIRTUAL_OPCODE = 0xB1
        FusedComputation.FUSION_RULES = {
            PUSH2_OPCODE: [{"pattern_opcodes": (JUMP_OPCODE,), "trigger_arg_bytes": 2, "pattern_bytes": 1, "fused_opcode_id": UJUMP2_VIRTUAL_OPCODE, "fused_mnemonic": "UJUMP2_FUSED"}],
            SUB_OPCODE: [{"pattern_opcodes": (MUL_OPCODE,), "trigger_arg_bytes": 0, "pattern_bytes": 1, "fused_opcode_id": SUBMUL_VIRTUAL_OPCODE, "fused_mnemonic": "SUBMUL_FUSED"}],
        }
        FusedComputation.UJUMP2_OPCODE_CONST = UJUMP2_VIRTUAL_OPCODE


except ImportError:
    print("错误：无法导入自定义 Computation 类。请确保 custom_computation.py 文件和类定义正确。")
    exit()


# 假设你的基础VM类 (例如 CancunVM)
from eth.vm.forks.cancun import CancunVM # 替换为你项目的基础VM

# 其他导入 (如 fetch_bytecode, SilentFileWriter 等)
from db_utils import fetch_bytecode


# --- SilentFileWriter (如果需要捕获详细trace) ---
class SilentFileWriter: # (从你之前的脚本复制过来)
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
        self.file.close()
        sys.stdout = self.original_stdout
# --- 测试账户 ---
test_account = Account.create("benchmark_sender")

def prepare_genesis_state_for_benchmark(target_contract_address_hex: str, test_sender_address: str):
    bytecode = fetch_bytecode(target_contract_address_hex)
    genesis_state = {
        to_canonical_address(test_sender_address): {"balance": 10**21, "nonce": 0, "code": b"", "storage": {}},
        to_canonical_address(target_contract_address_hex): {"balance": 0, "nonce": 0, "code": bytecode or b"", "storage": {}},
    }
    return genesis_state

def run_and_time_transaction(
    chain_instance: Chain,
    signed_tx,
    description: str,
    enable_tracing: bool = False, # 新增参数，默认为False
    trace_filepath: Optional[str] = None,
    verbose_console: bool = True # 新增参数，控制单次运行的控制台输出
):
    vm = chain_instance.get_vm()
    block_header = chain_instance.get_block().header # 获取当前区块头

    computation_result = None
    receipt_result = None
    
    if verbose_console:
        print(f"\n--- 开始执行: {description} ---")
    if verbose_console and trace_filepath:
        if verbose_console:
            print(f"详细跟踪将输出到: {trace_filepath}")
        with SilentFileWriter(trace_filepath, mode="w"): # 每次覆盖
            start_time = time.perf_counter()
            receipt_result, computation_result = vm.apply_transaction(block_header, signed_tx)
            end_time = time.perf_counter()
    else:
        start_time = time.perf_counter()
        receipt_result, computation_result = vm.apply_transaction(block_header, signed_tx)
        end_time = time.perf_counter()

    duration_ms = (end_time - start_time) * 1000
    
    status = "成功" if not computation_result.is_error else f"失败 ({computation_result.error})"
    gas_used = receipt_result.gas_used if receipt_result else "N/A"
    if verbose_console:
        print(f"执行状态 ({description}): {status}")
        print(f"Gas 使用量 ({description}): {gas_used}")
        print(f"执行时间 ({description}): {duration_ms:.4f} ms")
        
    return duration_ms, status == "成功", receipt_result, computation_result


def main_benchmark():
    # --- 固定测试参数 (来自你之前的例子) ---
    target_contract_hex = "0xfee1db36c0618c11b8604cf3f5e43b6ecfc47657"
    calldata_hex = "0x3ccfd60b"
    tx_value = 0
    tx_gas_limit = 222901
    tx_gas_price = 4744839671
    # --- 固定参数结束 ---

    print(f"基准测试账户地址: {test_account.address}")
    print(f"目标合约: {target_contract_hex}")
    print(f"Calldata: {calldata_hex}")

    tx_data = decode_hex(calldata_hex)
    genesis_params = {"difficulty": 0, "gas_limit": 30_000_000, "timestamp": int(time.time())}
    
    # 准备Genesis状态 (只需要一次)
    current_genesis_state = prepare_genesis_state_for_benchmark(target_contract_hex, test_account.address)

    # --- 配置不同的VM和Chain ---
    # VM 和 Chain (原始，无融合)
    # 通过显式子类化来定义 VM_Original，并直接设置其 computation_class
    class VM_Original_Bench(CancunVM):
        computation_class = OriginalComputation

    Chain_Original = Chain.configure(
        __name__="Chain_Original_Bench",
        # vm_configuration 现在直接使用我们新定义的 VM 类
        vm_configuration=((constants.GENESIS_BLOCK_NUMBER, VM_Original_Bench),) 
    )

    # VM 和 Chain (带融合逻辑)
    # 通过显式子类化来定义 VM_Fused，并直接设置其 computation_class
    class VM_Fused_Bench(CancunVM): # 同样继承自你的基础VM，例如 CancunVM
        computation_class = FusedComputation # 使用你的 FusedComputation 类

    Chain_Fused = Chain.configure(
        __name__="Chain_Fused_Bench",
        vm_configuration=((constants.GENESIS_BLOCK_NUMBER, VM_Fused_Bench),)
    )

    # --- 创建交易 (只需要一次) ---
    # 使用任一链的VM来创建交易对象 (例如原始链)
    # 注意：每次执行 run_and_time_transaction 时，都会用新的DB创建链，所以nonce会从0开始
    # 如果你想在同一个链上连续执行，nonce管理会更复杂，但对于独立基准测试，每次新链更好。
    
    # 为了获取正确的初始 nonce，我们从一个临时链实例开始
    temp_chain_for_nonce = Chain_Original.from_genesis(AtomicDB(), genesis_params, current_genesis_state)
    temp_vm_for_nonce = temp_chain_for_nonce.get_vm()
    sender_nonce = temp_vm_for_nonce.state.get_nonce(to_canonical_address(test_account.address))

    unsigned_tx = temp_vm_for_nonce.create_unsigned_transaction(
        nonce=sender_nonce,
        gas_price=tx_gas_price,
        gas=tx_gas_limit,
        to=to_canonical_address(target_contract_hex),
        value=tx_value,
        data=tx_data,
    )
    signed_tx = unsigned_tx.as_signed_transaction(keys.PrivateKey(test_account.key))

    # --- 执行基准测试 ---
    num_runs = 500 # 多次运行以获得更稳定的结果
    times_original = []
    times_fused = []
    
    output_dir = "benchmark_traces"
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n将执行 {num_runs} 轮基准测试...")

    for i in range(num_runs):
        print(f"\n--- 第 {i+1}/{num_runs} 轮 ---")
        # 只在第一轮运行时启用详细的trace文件记录
        generate_trace_file_this_run = (i == 0) 
        short_contract_hex = target_contract_hex[2:10] # 用于文件名，避免过长
        
        # 1. 执行原始版本
        db_orig = AtomicDB() # 每次执行使用新的DB，确保状态隔离
        chain_orig_instance = Chain_Original.from_genesis(db_orig, genesis_params, current_genesis_state)
        trace_orig_path = os.path.join(output_dir, f"trace_original_run{i+1}.txt")
        duration_orig, success_orig, _, _ = run_and_time_transaction(
            chain_orig_instance, 
            signed_tx, 
            f"原始VM (轮次 {i+1})", 
            enable_tracing=generate_trace_file_this_run, 
            trace_filepath=trace_orig_path,
            verbose_console=(i == 0) # 只在第一轮打印详细的单次运行信息
        )
        if success_orig:
            times_original.append(duration_orig)

        # 2. 执行融合版本
        db_fused = AtomicDB() # 新的DB
        chain_fused_instance = Chain_Fused.from_genesis(db_fused, genesis_params, current_genesis_state)
        trace_fused_path = os.path.join(output_dir, f"trace_fused_run{i+1}.txt")
        duration_fused, success_fused, _, comp_fused = run_and_time_transaction(
            chain_fused_instance, 
            signed_tx, 
            f"融合VM (轮次 {i+1})",
            enable_tracing=generate_trace_file_this_run,
            trace_filepath=trace_fused_path,
            verbose_console=(i == 0) # 只在第一轮打印详细的单次运行信息
        )
        if success_fused:
            times_fused.append(duration_fused)
        
        # 短暂休眠，避免系统负载影响连续测试 (可选)
        # time.sleep(0.1) 

    # --- 结果分析 ---
    print("\n\n--- 基准测试结果总结 ---")
    if times_original:
        avg_original = sum(times_original) / len(times_original)
        print(f"原始VM平均执行时间: {avg_original:.4f} ms (基于 {len(times_original)} 次成功运行)")
    else:
        print("原始VM未能成功运行。")

    if times_fused:
        avg_fused = sum(times_fused) / len(times_fused)
        print(f"融合VM平均执行时间: {avg_fused:.4f} ms (基于 {len(times_fused)} 次成功运行)")
    else:
        print("融合VM未能成功运行。")

    if times_original and times_fused and avg_original > 0:
        improvement_percent = ((avg_original - avg_fused) / avg_original) * 100
        print(f"性能提升 (或下降): {improvement_percent:.2f}%")
        if improvement_percent > 0:
            print("融合版本更快！")
        elif improvement_percent < 0:
            print("融合版本更慢。请检查融合逻辑的开销。")
        else:
            print("性能无显著差异。")

# benchmark_fusion.py

# ... (其他 imports 和函数定义，包括修改后的 run_and_time_transaction) ...

# def get_all_contract_addresses_from_db(): # 你需要实现这个函数
#     # return ["0x...", "0x..."] # 从数据库返回地址列表
#     # 为了演示，我们用之前find_sub_mul_contracts.py中的示例
#     return ["0xfee1db36c0618c11b8604cf3f5e43b6ecfc47657", "0xYOUR_OTHER_CONTRACT_ADDRESS_HERE"]


def main_benchmark_batch(): # 重命名 main 函数以示区分
    # 获取所有要测试的合约地址
    # contract_addresses_to_test = get_all_contract_addresses_from_db()
    contract_addresses_to_test = get_all_contract_addresses() # 使用上面定义的示例函数

    if not contract_addresses_to_test:
        print("错误: 未能获取到要测试的合约地址列表。")
        return

    print(f"将对 {len(contract_addresses_to_test)} 个合约进行基准测试...")

    # --- 通用交易参数 (对于批量测试，你可能需要更通用的calldata) ---
    # 对于 SUB-MUL 测试，理想情况下，你应该为每个已知包含该模式的合约使用特定的、能触发该路径的calldata
    # 这里我们使用一个非常通用的空calldata，它可能无法触发所有合约的复杂逻辑
    calldata_hex = "0x" 
    tx_data = decode_hex(calldata_hex)
    tx_value = 0
    tx_gas_limit = 300_000 # 为每个合约设置一个合理的默认Gas Limit
    tx_gas_price = 10 * (10**9) # 10 Gwei
    # --- 通用交易参数结束 ---

    # --- VM 和 Chain 配置 (只需要配置一次) ---
    VM_Original = CancunVM.configure(
        __name__='VM_Original_Batch',
        computation_class=OriginalComputation
    )
    Chain_Original_Config = Chain.configure( # 注意这里是配置，不是实例
        __name__="Chain_Original_Batch_Cfg",
        vm_configuration=((constants.GENESIS_BLOCK_NUMBER, VM_Original),)
    )
    VM_Fused = CancunVM.configure(
        __name__='VM_Fused_Batch',
        computation_class=FusedComputation
    )
    Chain_Fused_Config = Chain.configure(
        __name__="Chain_Fused_Batch_Cfg",
        vm_configuration=((constants.GENESIS_BLOCK_NUMBER, VM_Fused),)
    )
    # --- VM 和 Chain 配置结束 ---

    all_benchmark_results = []
    num_runs_per_contract = 3 # 对每个合约运行多次以求平均
    ENABLE_DETAILED_TRACING_IN_BATCH = False # 批量测试时通常关闭详细trace以提高速度

    output_dir = "batch_benchmark_traces" # 单独的目录
    os.makedirs(output_dir, exist_ok=True)

    for contract_idx, target_contract_hex in enumerate(contract_addresses_to_test):
        print(f"\n[{contract_idx+1}/{len(contract_addresses_to_test)}] 测试合约: {target_contract_hex}")
        
        current_genesis_params = {"difficulty": 0, "gas_limit": 5_000_000, "timestamp": int(time.time())} # 提高区块GasLimit
        try:
            current_genesis_state = prepare_genesis_state_for_benchmark(target_contract_hex, test_account.address)
        except Exception as e_genesis:
            print(f"  准备合约 {target_contract_hex} 的Genesis状态失败: {e_genesis}")
            all_benchmark_results.append({"address": target_contract_hex, "error": "Genesis setup failed"})
            continue # 跳到下一个合约

        # 为当前合约创建交易 (nonce会从0开始，因为每次都是新的链实例)
        # 使用一个临时VM来创建交易对象，确保nonce从0开始
        temp_db_for_tx = AtomicDB()
        temp_chain_for_tx = Chain_Original_Config.from_genesis(temp_db_for_tx, current_genesis_params, current_genesis_state)
        temp_vm_for_tx = temp_chain_for_tx.get_vm()
        
        try:
            sender_nonce = temp_vm_for_tx.state.get_nonce(to_canonical_address(test_account.address))
            unsigned_tx = temp_vm_for_tx.create_unsigned_transaction(
                nonce=sender_nonce, gas_price=tx_gas_price, gas=tx_gas_limit,
                to=to_canonical_address(target_contract_hex), value=tx_value, data=tx_data,
            )
            signed_tx = unsigned_tx.as_signed_transaction(keys.PrivateKey(test_account.key))
        except Exception as e_tx_create:
            print(f"  为合约 {target_contract_hex} 创建交易失败: {e_tx_create}")
            all_benchmark_results.append({"address": target_contract_hex, "error": "Transaction creation failed"})
            continue

        # 为当前合约执行多次运行
        contract_times_original = []
        contract_times_fused = []
        contract_gas_original = []
        contract_gas_fused = []
        
        print(f"  将执行 {num_runs_per_contract} 轮...")
        for run_idx in range(num_runs_per_contract):
            # 1. 原始VM
            db_orig_run = AtomicDB()
            chain_orig_run_instance = Chain_Original_Config.from_genesis(db_orig_run, current_genesis_params, current_genesis_state)
            trace_orig_path_run = None
            if ENABLE_DETAILED_TRACING_IN_BATCH and run_idx == 0: # 只为每合约第一轮生成trace
                trace_orig_path_run = os.path.join(output_dir, f"trace_orig_{target_contract_hex[2:10]}_{contract_idx}.txt")
            
            # 注意: run_and_time_transaction 现在返回 (duration, success, receipt, computation)
            dur_orig, suc_orig, rec_orig, _ = run_and_time_transaction(
                chain_orig_run_instance, signed_tx, f"原始 ({target_contract_hex[2:10]} R{run_idx+1})",
                enable_tracing=(ENABLE_DETAILED_TRACING_IN_BATCH and run_idx == 0),
                trace_filepath=trace_orig_path_run,
                verbose_console=False # 批量模式下减少控制台输出
            )
            if suc_orig:
                contract_times_original.append(dur_orig)
                contract_gas_original.append(rec_orig.gas_used if rec_orig else 0)

            # 2. 融合VM
            db_fused_run = AtomicDB()
            chain_fused_run_instance = Chain_Fused_Config.from_genesis(db_fused_run, current_genesis_params, current_genesis_state)
            trace_fused_path_run = None
            if ENABLE_DETAILED_TRACING_IN_BATCH and run_idx == 0:
                trace_fused_path_run = os.path.join(output_dir, f"trace_fused_{target_contract_hex[2:10]}_{contract_idx}.txt")

            dur_fused, suc_fused, rec_fused, _ = run_and_time_transaction(
                chain_fused_run_instance, signed_tx, f"融合 ({target_contract_hex[2:10]} R{run_idx+1})",
                enable_tracing=(ENABLE_DETAILED_TRACING_IN_BATCH and run_idx == 0),
                trace_filepath=trace_fused_path_run,
                verbose_console=False # 批量模式下减少控制台输出
            )
            if suc_fused:
                contract_times_fused.append(dur_fused)
                contract_gas_fused.append(rec_fused.gas_used if rec_fused else 0)
        
        # 计算当前合约的平均值
        avg_t_orig = sum(contract_times_original) / len(contract_times_original) if contract_times_original else None
        avg_t_fused = sum(contract_times_fused) / len(contract_times_fused) if contract_times_fused else None
        avg_g_orig = sum(contract_gas_original) / len(contract_gas_original) if contract_gas_original else None
        avg_g_fused = sum(contract_gas_fused) / len(contract_gas_fused) if contract_gas_fused else None

        print(f"  合约 {target_contract_hex} 平均时间: 原始={avg_t_orig:.2f}ms, 融合={avg_t_fused:.2f}ms" if avg_t_orig and avg_t_fused else "  结果不完整")
        
        all_benchmark_results.append({
            "address": target_contract_hex,
            "avg_time_original_ms": avg_t_orig,
            "avg_time_fused_ms": avg_t_fused,
            "avg_gas_original": avg_g_orig,
            "avg_gas_fused": avg_g_fused,
            "runs_original_success": len(contract_times_original),
            "runs_fused_success": len(contract_times_fused),
        })

    # --- 批量测试结果分析与输出 ---
    print("\n\n--- 批量基准测试最终总结 ---")
    num_contracts_tested = len(all_benchmark_results)
    num_improved = 0
    total_improvement_percent = 0
    valid_comparisons = 0

    for result in all_benchmark_results:
        if result.get("error"):
            print(f"合约 {result['address']}: 错误 - {result['error']}")
            continue
        
        if result["avg_time_original_ms"] is not None and result["avg_time_fused_ms"] is not None and result["avg_time_original_ms"] > 0:
            valid_comparisons += 1
            improvement = ((result["avg_time_original_ms"] - result["avg_time_fused_ms"]) / result["avg_time_original_ms"]) * 100
            print(f"合约 {result['address']}: "
                  f"原始 avg time: {result['avg_time_original_ms']:.2f}ms (Gas: {result['avg_gas_original']}), "
                  f"融合 avg time: {result['avg_time_fused_ms']:.2f}ms (Gas: {result['avg_gas_fused']}), "
                  f"提升: {improvement:.2f}%")
            if result["avg_time_fused_ms"] < result["avg_time_original_ms"]:
                num_improved += 1
            total_improvement_percent += improvement
        else:
            print(f"合约 {result['address']}: 数据不完整，无法比较时间。")
            print(f"  (原始成功次数: {result['runs_original_success']}, 融合成功次数: {result['runs_fused_success']})")


    if valid_comparisons > 0:
        avg_total_improvement = total_improvement_percent / valid_comparisons
        print(f"\n在 {valid_comparisons} 个可比较的合约中，平均性能提升: {avg_total_improvement:.2f}%")
        print(f"共有 {num_improved} 个合约显示出性能提升。")
    else:
        print("\n没有足够的数据进行总体性能比较。")

if __name__ == "__main__":
    # main_benchmark() # 如果你还想运行之前的单合约固定参数测试
    main_benchmark_batch() # 运行批量测试




if __name__ == "__main__":
    # 需要在你的环境中设置PYTHONPATH，以便能够找到 custom_computation 和 db_utils
    # 例如: export PYTHONPATH=$PYTHONPATH:/path/to/your/project/directory
    # 或者在脚本顶部使用 sys.path.append
    import sys
    # sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))) # 示例路径调整

    main_benchmark()
