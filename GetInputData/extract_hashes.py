import pandas as pd

INPUT_FILENAME = "200k_transactions.csv"
HASH_COLUMN_NAME = "transactionHash"
OUTPUT_HATCH_LIST_FILENAME = "transaction_hash.csv"

try:
    print(f"正在从 '{INPUT_FILENAME}' 读取原始数据...")
    df = pd.read_csv(INPUT_FILENAME)
    
    if HASH_COLUMN_NAME not in df.columns:
        print(f"错误: 未找到列 '{HASH_COLUMN_NAME}'")
    else:
        # 提取哈希列，去重，并确保没有空值
        hashes_df = df[[HASH_COLUMN_NAME]].dropna().drop_duplicates()
        
        # 保存到新的 CSV 文件，不带索引
        hashes_df.to_csv(OUTPUT_HATCH_LIST_FILENAME, index=False)
        print(f"成功！已将 {len(hashes_df)} 个不重复的哈希值保存到 '{OUTPUT_HATCH_LIST_FILENAME}'。")
except Exception as e:
    print(f"发生错误: {e}")