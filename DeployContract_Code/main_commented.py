'''
This program can do:
- Compile the solidity code by solcx
- Run the executable file
- Output the opcodes and stack memory states to a file 
'''

from web3 import Web3, EthereumTesterProvider
from eth_tester import PyEVMBackend
from solcx import install_solc, compile_source
import time
import sys

class SilentFileWriter:
    def __init__(self, filename):
        self.file = open(filename, 'w', encoding='utf-8')
        self.original_stdout = sys.stdout  # 备份原输出流

    def write(self, text):
        # 仅写入文件，不输出到控制台
        self.file.write(text)

    def flush(self):
        # 确保缓冲区内容写入文件
        self.file.flush()

sys.stdout = SilentFileWriter('output_new.log')

# 安装指定版本的 Solidity 编译器
print("安装 Solidity 编译器 (solc 0.5.0)...")
install_solc(version='0.5.0')
print("Solidity 编译器安装完成\n")

# 使用 EthereumTesterProvider 创建一个本地的以太坊测试环境
print("创建本地以太坊测试环境...")
w3 = Web3(EthereumTesterProvider(ethereum_tester=PyEVMBackend()))
print("测试环境创建成功\n")

# Solidity 源代码
solidity_source = '''
pragma solidity ^0.5.0;

contract TestAddMultiCost {

    uint256 a;
    uint256 b;
    uint256 c;

    // 构造函数：初始化 a 和 b 的值
    constructor(uint256 x, uint256 y) public {
        a = x;
        b = y;
    }

    // AddMulti 函数：通过循环执行加法和乘法操作以消耗 gas
    function AddMulti() public {
        int j = 1;
        while(j > 0){
            c = a + b;
            c = a * b;
            j--;
        }
    }

}
'''

print("开始编译 Solidity 合约...")
compiled_sol = compile_source(
    solidity_source,
    output_values=['abi', 'bin'],
    solc_version="0.5.0"
)
print("合约编译成功\n")

# 提取合约接口及字节码
contract_id, contract_interface = compiled_sol.popitem()
bytecode = contract_interface['bin']
abi = contract_interface['abi']

print("合约字节码:")
print(bytecode, "\n")

print("合约 ABI:")
print(abi, "\n")

# 设置默认账户，用于后续交易
w3.eth.default_account = w3.eth.accounts[0]
print("测试环境中的账户列表:")
print(w3.eth.accounts, "\n")

# 创建合约对象
print("构造合约对象...")
Greeter = w3.eth.contract(abi=abi, bytecode=bytecode)
print("合约对象构造完成\n")

# 部署合约到测试网络（通过构造函数传入参数 1234 和 4321）
print("开始部署合约...")
tx_hash = Greeter.constructor(1234, 4321).transact()
tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
print("合约部署完成，交易回执:")
print(tx_receipt, "\n")

# 使用部署后的合约地址构造合约实例
print("通过部署的地址获取合约实例...")
greeter = w3.eth.contract(
    address=tx_receipt.contractAddress,
    abi=abi
)
print("合约实例获取成功\n")

# 调用合约中的 AddMulti 函数，并记录运行时间
print("调用合约中的 AddMulti 函数，开始计时...")
t1 = time.time()
tx_hash = greeter.functions.AddMulti().transact()
t2 = time.time()
print("函数调用完成")
print("平均每次操作的耗时 (秒):")
print((t2 - t1) / 10000, "\n")

# 等待 AddMulti 函数的交易完成
print("等待 AddMulti 函数的交易回执...")
tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
print("交易回执接收，函数执行结束")

sys.stdout = sys.stdout.original_stdout
