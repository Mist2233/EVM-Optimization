import pandas as pd

# 读取 CSV 文件
input_file = "filtered_transactions.csv"
output_file = "200k_transactions.csv"

# 读取前 200000 行
df = pd.read_csv(input_file, nrows=2e5)

# 将数据存储到新的 CSV 文件
df.to_csv(output_file, index=False, encoding='utf-8')

print(f"已成功提取前 200k 行数据，并保存到 {output_file}")
