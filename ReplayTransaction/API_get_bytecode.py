import requests
import json
import os
import time

API_KEY = "QNUNRW6KGF5PKFTV48WDTIHWZVVQT74J8G"  # 我申请的Etherscan的API
INPUT_FILE = "contract_addresses.txt"
OUTPUT_DIR = "bytecodes"
RATE_LIMIT = 0.2  # 每次请求间隔(秒)

def get_contract_creation(contract_address):
    """获取合约创建信息"""
    url = f"https://api.etherscan.io/api?module=contract&action=getcontractcreation&contractaddresses={contract_address}&apikey={API_KEY}"
    try:
        response = requests.get(url)
        result = response.json()
        return result['result'][0] if result['status'] == '1' else None
    except Exception as e:
        print(f"Error fetching creation info: {str(e)}")
        return None

def get_deployed_bytecode(address):
    """获取已部署字节码"""
    api_url = f"https://api.etherscan.io/api?module=proxy&action=eth_getCode&address={address}&tag=latest&apikey={API_KEY}"
    try:
        response = requests.get(api_url)
        data = response.json()
        return data['result'][2:] if data.get('result') else None  # 去掉0x前缀
    except Exception as e:
        print(f"Error fetching bytecode: {str(e)}")
        return None

def process_address(address):
    """处理单个地址"""
    print(f"Processing {address}...")
    
    # 优先获取部署字节码
    bytecode = get_deployed_bytecode(address)
    
    # 如果失败则尝试通过合约创建记录获取
    if not bytecode:
        creation_info = get_contract_creation(address)
        if creation_info:
            bytecode = creation_info.get('contractCode', '')[2:]  # 去掉0x前缀
    
    # 保存结果
    if bytecode:
        filename = f"{address}.bin"
        with open(os.path.join(OUTPUT_DIR, filename), 'w') as f:
            f.write(bytecode)
        return True
    return False

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    with open(INPUT_FILE, 'r') as f:
        addresses = [line.strip() for line in f if line.strip()]
    
    success = 0
    for idx, addr in enumerate(addresses, 1):
        if process_address(addr):
            success += 1
        time.sleep(RATE_LIMIT)
        
        # 进度打印
        if idx % 10 == 0:
            print(f"Progress: {idx}/{len(addresses)} ({success} success)")

    print(f"\nCompleted! Success rate: {success}/{len(addresses)}")

if __name__ == "__main__":
    main()