import pandas as pd
import requests
import json
import time
import os
from tqdm import tqdm

# --- 配置区 ---
ANKR_API_KEY = "c4d89c037b8cb36f3677733bc2f6de89378e95f415afc67e0d945d191f1b2fd3"
ANKR_URL = f"https://rpc.ankr.com/eth/{ANKR_API_KEY}"

INPUT_CSV_FILE = "transaction_hash.csv"
OUTPUT_CSV_FILE = "transaction_inputs.csv"
ERROR_LOG_FILE = "failed_hashes.txt"

BATCH_SIZE = 100
# --- 配置区结束 ---

def get_input_data_batch(tx_hashes):
    """
    (V6 - "调试输出版", 遇到未知响应时会打印详细的原始信息)
    """
    payload = []
    for i, tx_hash in enumerate(tx_hashes):
        payload.append({
            "jsonrpc": "2.0",
            "method": "eth_getTransactionByHash",
            "params": [tx_hash],
            "id": i
        })

    retries = 5
    while retries > 0:
        try:
            response = requests.post(ANKR_URL, json=payload, timeout=30)
            response.raise_for_status() 
            
            # 尝试解析JSON
            try:
                data = response.json()
            except json.JSONDecodeError:
                # 如果连JSON都无法解析，说明返回的是HTML或纯文本错误
                print("\n" + "#" * 70)
                print("### JSON DECODE ERROR - DEBUG INFORMATION ###")
                print("#" * 70)
                print(f"### For batch starting with hash: {tx_hashes[0]}")
                print(f"### Server returned non-JSON text. Raw Response Text Below: ###")
                print(response.text)
                print("#" * 70 + "\n")
                return {tx_hash: "Error: JSON Decode Error" for tx_hash in tx_hashes}

            # 严格检查服务器返回的是否是列表
            if not isinstance(data, list):
                print("\n" + "#" * 70)
                print("### UNEXPECTED DATA TYPE - DEBUG INFORMATION ###")
                print("#" * 70)
                print(f"### For batch starting with hash: {tx_hashes[0]}")
                print(f"### Expected a list, but got {type(data).__name__}. Raw Response Text Below: ###")
                print(response.text)
                print("#" * 70 + "\n")
                return {tx_hash: "Error: Unexpected server response" for tx_hash in tx_hashes}

            if data and data[0].get('error'):
                error_msg = data[0]['error'].get('message', '').lower()
                if 'rate limit' in error_msg or 'too many requests' in error_msg:
                    print(f"  [!!] Rate limited by API. Waiting 10 seconds... ({retries} retries left)")
                    time.sleep(10)
                    retries -= 1
                    continue

            results_map = {}
            for item in data:
                item_id = int(item['id'])
                original_hash = tx_hashes[item_id]
                if item.get('result'):
                    results_map[original_hash] = item['result'].get('input', 'Not Found')
                else:
                    error_message = item.get('error', {}).get('message', 'Unknown Error')
                    results_map[original_hash] = f"Error: {error_message}"
            return results_map

        except requests.exceptions.RequestException as e:
            print(f"  [!!] Network/HTTP Error: {e}")
            retries -= 1
            if retries > 0:
                print(f"  ...retrying in 5 seconds ({retries} retries left).")
                time.sleep(5)
            else:
                return {tx_hash: "Network Error" for tx_hash in tx_hashes}
    
    print("  [!!] Max retries exceeded for this batch.")
    return {tx_hash: "Failed after max retries" for tx_hash in tx_hashes}


def main():
    # main函数无需修改
    print("--- Starting Transaction Input Data Fetcher (Debug Edition) ---")
    try:
        df_full = pd.read_csv(INPUT_CSV_FILE)
        all_tx_hashes = df_full['tx_hash'].dropna().str.lower().str.strip().unique().tolist()
    except FileNotFoundError:
        print(f"[ERROR] Input file '{INPUT_CSV_FILE}' not found.")
        return
    processed_hashes = set()
    if os.path.exists(OUTPUT_CSV_FILE):
        print(f"[INFO] Output file '{OUTPUT_CSV_FILE}' found. Reading processed transactions...")
        try:
            df_processed = pd.read_csv(OUTPUT_CSV_FILE)
            if 'tx_hash' in df_processed.columns:
                processed_hashes = set(df_processed['tx_hash'].dropna().str.lower().str.strip())
                print(f"[INFO] {len(processed_hashes)} transactions already standardized and processed.")
        except pd.errors.EmptyDataError:
             print(f"[INFO] Output file is empty. Starting from scratch.")
        except Exception as e:
             print(f"[WARN] Could not read processed file properly: {e}. Starting from scratch.")
    hashes_to_process = [h for h in all_tx_hashes if h not in processed_hashes]
    if not hashes_to_process:
        print("[SUCCESS] All transactions have already been processed. Nothing to do.")
        return
    print(f"[INFO] Total: {len(all_tx_hashes)}, Processed: {len(processed_hashes)}, Remaining: {len(hashes_to_process)}")
    failed_hashes = []
    with tqdm(total=len(hashes_to_process), desc="Processing remaining transactions") as pbar:
        for i in range(0, len(hashes_to_process), BATCH_SIZE):
            batch_hashes = hashes_to_process[i:i + BATCH_SIZE]
            batch_results_map = get_input_data_batch(batch_hashes)
            batch_results_list = []
            for tx_hash in batch_hashes:
                input_data = batch_results_map.get(tx_hash, 'Failed to fetch')
                batch_results_list.append({'tx_hash': tx_hash, 'input_data': input_data})
                if 'Error' in str(input_data) or 'Failed' in str(input_data):
                    failed_hashes.append(tx_hash)
            if batch_results_list:
                output_df = pd.DataFrame(batch_results_list)
                output_df.to_csv(OUTPUT_CSV_FILE, mode='a', header=not os.path.exists(OUTPUT_CSV_FILE), index=False)
            pbar.update(len(batch_hashes))
    print("\n[OK] All remaining transactions have been processed.")
    if failed_hashes:
        print(f"[INFO] {len(failed_hashes)} hashes failed during this run. Check '{OUTPUT_CSV_FILE}' and '{ERROR_LOG_FILE}'.")
        with open(ERROR_LOG_FILE, 'a') as f:
            for tx_hash in failed_hashes:
                f.write(f"{tx_hash}\n")
    print("--- Script Finished ---")

if __name__ == "__main__":
    main()