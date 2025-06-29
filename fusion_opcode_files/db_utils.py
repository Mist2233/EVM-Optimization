# db_utils.py
import sqlite3
from eth_utils import decode_hex

db_path = "E:\op-evm\contract_codes.db"

def fetch_bytecode(address: str) -> bytes:
    """根据地址从数据库中查找字节码，并转换为 bytes 类型"""
    address = address.lower()
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT bytecode FROM contract_codes WHERE address = ?", (address,))
        result = cur.fetchone()
        conn.close()

        if result and result[0]:
            hex_code = result[0].lstrip("0x")  # 去掉 0x 前缀
            return decode_hex(hex_code)
        else:
            return b''
    except Exception as e:
        print(f"读取 {address} 出错: {e}")
        return b''
