import pandas as pd
import requests
from eth.chains.base import Chain
from eth.db.atomic import AtomicDB
from eth.vm.forks import LATEST_VM
from eth_utils import to_canonical_address, decode_hex
from eth_account import Account
from eth_keys import keys
from eth import constants
import time

# ============== 准备测试账户 ===================
test_account = Account.create("test")

# ================== 第一部分：从CSV获取合约地址 ==================
def load_contract_addresses(csv_path):
    """从CSV加载所有唯一的合约地址"""
    df = pd.read_csv(csv_path)
    return df['to'].unique().tolist()  # 返回去重后的地址列表

# ================== 第二部分：获取合约字节码 ==================
ETHERSCAN_API_KEY = "QNUNRW6KGF5PKFTV48WDTIHWZVVQT74J8G"  # 替换为真实API Key

def fetch_bytecode(address):
    """通过Etherscan API获取部署字节码"""
    api_url = f"https://api.etherscan.io/api?module=proxy&action=eth_getCode&address={address}&tag=latest&apikey={ETHERSCAN_API_KEY}"
    try:
        response = requests.get(api_url)
        data = response.json()
        bytecode_hex = data.get('result', '')
        return decode_hex(bytecode_hex) if bytecode_hex.startswith('0x') else b''
    except Exception as e:
        print(f"获取 {address} 字节码失败: {str(e)}")
        return b''

# ================== 第三部分：动态构建测试环境 ==================
def prepare_genesis_state(contract_addresses):
    """准备动态创世状态"""
    genesis_state = {
        # 初始化测试账户（交易发起账户）
        to_canonical_address(test_account.address): {
            "balance": 10**30,
            "nonce": 0,
            "code": b"",
            "storage": {}
        }
    }
    
    # 动态添加合约
    for addr in contract_addresses:
        print(f"正在准备合约 {addr}...")
        bytecode = fetch_bytecode(addr)
        time.sleep(0.2)  # API速率限制
        
        genesis_state[to_canonical_address(addr)] = {
            "balance": 0,
            "nonce": 0,
            "code": bytecode,
            "storage": {}
        }
    
    return genesis_state

# ================== 第四部分：主执行流程 ==================
def main():
    # 步骤1：加载交易数据
    contract_addresses = load_contract_addresses("output_test.csv")
    print(f"发现 {len(contract_addresses)} 个唯一合约地址")
    
    # 步骤2：准备区块链环境
    db = AtomicDB()
    genesis_params = {
        'difficulty': 0,
        'gas_limit': 30_000_000,  # 提高gas limit
        'timestamp': int(time.time()),
    }
    
    # 动态生成创世状态
    genesis_state = prepare_genesis_state(contract_addresses)
    
    # 步骤3：创建测试链
    TestChain = Chain.configure(
        __name__="DynamicChain",
        vm_configuration=((constants.GENESIS_BLOCK_NUMBER, LATEST_VM),),
    )
    
    chain = TestChain.from_genesis(
        db,
        genesis_params=genesis_params,
        genesis_state=genesis_state
    )
    
    # 步骤4：处理交易（示例处理第一个交易）
    if contract_addresses:
        sample_address = contract_addresses[0]
        print(f"\n执行示例交易到 {sample_address}")
        
        vm = chain.get_vm()
        tx = vm.create_unsigned_transaction(
            nonce=0,
            gas_price=10**9,
            gas=1_000_000,
            to=to_canonical_address(sample_address),
            value=0,
            data=b""
        )
        
        # 签名交易
        
        signed_tx = tx.as_signed_transaction(keys.PrivateKey(test_account.key))
        
        # 执行交易
        block_header = chain.get_block().header
        receipt, computation = vm.apply_transaction(block_header, signed_tx)
        
        print(f"交易结果: Gas Used = {receipt.gas_used}")
        print(f"执行状态: {'成功' if not computation.is_error else '失败'}")

if __name__ == "__main__":
    main()