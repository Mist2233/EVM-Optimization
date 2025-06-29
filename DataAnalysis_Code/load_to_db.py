# load_to_db.py
import os
import json
import sqlite3

json_dir = r"E:\XBlock-ETH"
db_path = "contract_codes.db"

# 初始化数据库
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS contract_codes (
    address TEXT PRIMARY KEY,
    bytecode TEXT
)
""")

# 逐个读取 JSON 文件并插入数据
for filename in os.listdir(json_dir):
    if filename.endswith(".json"):
        print(f"正在导入 {filename}")
        with open(os.path.join(json_dir, filename), "r", encoding="utf-8") as f:
            data = json.load(f)
            items = [(addr.lower(), code) for addr, code in data.items()]
            cur.executemany("INSERT OR IGNORE INTO contract_codes (address, bytecode) VALUES (?, ?)", items)
        conn.commit()

conn.close()
print("✅ 所有数据已导入数据库。")
