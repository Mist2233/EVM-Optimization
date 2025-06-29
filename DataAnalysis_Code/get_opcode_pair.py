import os
import glob
import pandas as pd
from collections import defaultdict

def get_top_opcodes(top_n=20):
    """获取高频OPCODE列表"""
    df = pd.read_excel('statistics/opcode_statistics.xlsx')
    return df.head(top_n)['OPCODE'].tolist()

def analyze_opcode_pairs():
    top_opcodes = set(get_top_opcodes())  # 获取高频OPCODE集合
    pair_counter = defaultdict(int)       # 组合计数器
    
    # 遍历所有文件
    for file_path in glob.glob('contract_opcode/op_*.txt'):
        prev_op = None
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.startswith("OPCODE:"): 
                    continue
                
                # 提取当前OPCODE
                current_op = line.split('(')[1].split(')')[0].strip()
                
                # 仅统计高频OPCODE的组合
                if prev_op in top_opcodes or current_op in top_opcodes:
                    pair = (prev_op, current_op)
                    pair_counter[pair] += 1
                
                prev_op = current_op  # 更新前序OPCODE

    # 转换为DataFrame
    df = pd.DataFrame(
        [{'OP1': k[0], 'OP2': k[1], 'Count': v} for k,v in pair_counter.items()],
        columns=['OP1', 'OP2', 'Count']
    ).sort_values('Count', ascending=False)

    # 过滤空值（首条指令无前序）
    df = df[df['OP1'].notnull()]  
    
    # 保存结果
    df.to_excel('statistics/opcode_pairs.xlsx', index=False)
    print(f"发现 {len(df)} 种有效组合，高频组合已保存到 statistics/opcode_pairs.xlsx")

if __name__ == "__main__":
    analyze_opcode_pairs()