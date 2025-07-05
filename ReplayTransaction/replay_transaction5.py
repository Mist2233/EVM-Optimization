import os
import time
import pandas as pd
import json
from eth.chains.base import Chain
from eth.db.atomic import AtomicDB
from eth.vm.forks import LATEST_VM
from eth_utils import to_canonical_address, decode_hex
from eth_account import Account
from eth_keys import keys
from eth import constants
import sys
from db_utils import fetch_bytecode


# ============ 将输出直接导入文件 ==================
class SilentFileWriter:
    def __init__(self, filename):
        self.file = open(filename, "w", encoding="utf-8")
        self.original_stdout = sys.stdout  # 备份原输出流

    def write(self, text):
        # 仅写入文件，不输出到控制台
        self.file.write(text)

    def flush(self):
        # 确保缓冲区内容写入文件
        self.file.flush()


# ============== 准备测试账户 ===================
test_account = Account.create("test")


# ================== 第一部分：读取CSV数据 ==================
def load_csv_data(csv_path: str):
    """加载CSV数据，返回DataFrame和所有唯一的合约地址列表"""
    df = pd.read_csv(csv_path)
    contract_addresses = df["to"].unique().tolist()  # 从“to”列获得所有合约地址（去重）
    return df, contract_addresses


# ================== 第二部分：获取合约字节码 ==================
# 利用db_utils.py中的fetch_bytecode函数完成


# ================== 第三部分：动态构建测试环境 ==================
def prepare_genesis_state(contract_addresses: list):
    """准备动态创世状态"""
    genesis_state = {
        # 初始化测试账户（交易发起账户）
        to_canonical_address(test_account.address): {
            "balance": 10**30,
            "nonce": 0,
            "code": b"",
            "storage": {},
        }
    }

    # 动态添加每个合约地址
    for addr in contract_addresses:
        if pd.isna(addr):
            continue
        print(f"正在准备合约 {addr} ...")
        bytecode = fetch_bytecode(addr)

        genesis_state[to_canonical_address(addr)] = {
            "balance": 0,
            "nonce": 0,
            "code": bytecode,
            "storage": {},
        }

    return genesis_state


# ================== 第四部分：写入执行结果 ==================
def write_result_to_file(address, result_str):
    """将执行结果写入 contract_opcode/op_{address}.txt 文件中"""

    output_dir = "contract_opcode"
    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"op_{address}.txt")
    # 采用追加模式写入，每笔交易结果作为一条记录
    with open(filename, "a", encoding="utf-8") as f:
        f.write(result_str + "\n" + "-" * 40 + "\n")


# ================== 第五部分：主执行流程 ==================
def main():
    # 步骤1：加载CSV数据和合约地址
    csv_path = "200k_transactions.csv"
    df, contract_addresses = load_csv_data(csv_path)
    print(f"发现 {len(contract_addresses)} 个唯一合约地址")

    # 步骤2：准备区块链环境
    db = AtomicDB()
    genesis_params = {
        "difficulty": 0,
        "gas_limit": 30_000_000,  # 提高gas limit
        "timestamp": int(time.time()),
    }
    genesis_state = prepare_genesis_state(contract_addresses)

    # 创建测试链
    TestChain = Chain.configure(
        __name__="DynamicChain",
        vm_configuration=((constants.GENESIS_BLOCK_NUMBER, LATEST_VM),),
    )
    chain = TestChain.from_genesis(
        db, genesis_params=genesis_params, genesis_state=genesis_state
    )

    # 步骤3：逐行处理CSV中的交易数据
    start_time = time.time()
    for idx, row in df.iterrows():
        # 读取必要的字段，注意需要转换数据类型
        block_number = row.get("blockNumber")
        timestamp = row.get("timestamp")
        transaction_hash = row.get("transactionHash")
        from_addr = row.get("from")
        to_addr = row.get("to")
        to_create = row.get("toCreate")
        from_is_contract = row.get("fromIsContract")
        to_is_contract = row.get("toIsContract")
        value = int(row.get("value", 0))
        gas_limit = int(str(row.get("gasLimit", "1000000")).replace(",", ""))
        gas_price = int(str(row.get("gasPrice", "1000000000")).replace(",", ""))
        gas_used_csv = row.get("gasUsed")
        calling_function = row.get("callingFunction")
        is_error = row.get("isError")
        eip2718type = row.get("eip2718type")
        base_fee_per_gas = row.get("baseFeePerGas")
        max_fee_per_gas = row.get("maxFeePerGas")
        max_priority_fee_per_gas = row.get("maxPriorityFeePerGas")
        blob_hashes = row.get("blobHashes")
        blob_base_fee_per_gas = row.get("blobBaseFeePerGas")
        blob_gas_used = row.get("blobGasUsed")

        # 根据CSV的“to”字段确定目标合约地址
        # print(f"\n执行交易到合约地址: {to_addr}")

        vm = chain.get_vm()
        try:
            # 如果calling_function数据为十六进制字符串，则进行解码；否则按utf-8编码
            if isinstance(calling_function, str) and calling_function.startswith("0x"):
                data_field = decode_hex(calling_function)
            else:
                data_field = (
                    calling_function.encode("utf-8")
                    if isinstance(calling_function, str)
                    else b""
                )

            # 创建交易，注意使用CSV中的gas_price、gas_limit、value和data字段
            tx = vm.create_unsigned_transaction(
                nonce=0,
                gas_price=gas_price,
                gas=gas_limit,
                to=to_canonical_address(to_addr),
                value=value,
                data=data_field,
            )
            # 签名交易
            signed_tx = tx.as_signed_transaction(keys.PrivateKey(test_account.key))
            # 执行交易
            block_header = chain.get_block().header

            sys.stdout = SilentFileWriter(f"contract_opcode/op_{to_addr}.txt")
            receipt, computation = vm.apply_transaction(block_header, signed_tx)

            exec_status = "成功" if not computation.is_error else "失败"
            gas_used_exec = receipt.gas_used

            # 组合所有输出信息
            result_str = (
                f"blockNumber: {block_number}\n"
                f"timestamp: {timestamp}\n"
                f"transactionHash: {transaction_hash}\n"
                f"from: {from_addr}\n"
                f"to: {to_addr}\n"
                f"toCreate: {to_create}\n"
                f"fromIsContract: {from_is_contract}\n"
                f"toIsContract: {to_is_contract}\n"
                f"value: {value}\n"
                f"gasLimit: {gas_limit}\n"
                f"gasPrice: {gas_price}\n"
                f"gasUsed (CSV): {gas_used_csv}\n"
                f"gasUsed (执行): {gas_used_exec}\n"
                f"callingFunction: {calling_function}\n"
                f"isError: {is_error}\n"
                f"eip2718type: {eip2718type}\n"
                f"baseFeePerGas: {base_fee_per_gas}\n"
                f"maxFeePerGas: {max_fee_per_gas}\n"
                f"maxPriorityFeePerGas: {max_priority_fee_per_gas}\n"
                f"blobHashes: {blob_hashes}\n"
                f"blobBaseFeePerGas: {blob_base_fee_per_gas}\n"
                f"blobGasUsed: {blob_gas_used}\n"
                f"执行状态: {exec_status}"
            )
            print("===============相关参数情况==================")
            print(result_str)
            print(f"实际交易结果: Gas Used = {receipt.gas_used}")
            sys.stdout = sys.stdout.original_stdout

            # 将结果写入到对应合约地址的文件中
            write_result_to_file(to_addr, result_str)

        except Exception as e:
            error_msg = f"执行交易时出现错误: {str(e)}"
            print(error_msg)
            write_result_to_file(to_addr, error_msg)
        if (idx + 1) % 100 == 0:
            elapsed = time.time() - start_time
            print(f"[进度] 已处理 {idx + 1} / {len(df)} 行交易，用时 {elapsed:.2f} 秒")


if __name__ == "__main__":
    main()
