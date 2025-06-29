import os
import glob
import pandas as pd
from collections import defaultdict

def extract_opcode_frequency():
    # 初始化计数器
    opcode_counter = defaultdict(int)
    
    # 获取所有op_前缀的txt文件
    files = glob.glob('contract_opcode/op_*.txt')
    
    for file_path in files:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                # 只处理包含OPCODE的行
                if line.startswith("OPCODE:"):
                    # 提取括号中的操作码名称（例如 "PUSH1"）
                    opcode = line.split('(')[1].split(')')[0].strip()
                    opcode_counter[opcode] += 1

    # 转换为DataFrame并排序
    df = pd.DataFrame(list(opcode_counter.items()), columns=['OPCODE', 'Count'])
    df = df.sort_values(by='Count', ascending=False)
    
    # 保存到Excel
    df.to_excel('statistics/opcode_statistics.xlsx', index=False)
    print(f"统计完成，共找到 {len(df)} 种不同的OPCODE，结果已保存到 statistics/opcode_statistics.xlsx")

if __name__ == "__main__":
    extract_opcode_frequency()