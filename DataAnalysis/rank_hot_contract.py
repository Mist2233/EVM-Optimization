import pandas as pd

def analyze_hot_contracts():
    # 读取CSV文件（假设列名为小写to）
    df = pd.read_csv('200k_transactions.csv', usecols=['to'])
    
    # 空值处理：过滤无效地址
    valid_df = df[df['to'].notna() & (df['to'] != '')]
    
    # 统计调用次数
    count_series = valid_df['to'].value_counts().reset_index()
    count_series.columns = ['Contract Address', 'Call Count']
    
    # 计算占比
    total = count_series['Call Count'].sum()
    count_series['Percentage'] = count_series['Call Count'].apply(
        lambda x: f"{x/total:.2%}"
    )
    
    # 保存结果
    count_series.to_excel('statistics/hot_contracts_from_csv.xlsx', index=False)
    print(f"统计完成！共发现 {len(count_series)} 个有效合约地址")

if __name__ == "__main__":
    analyze_hot_contracts()