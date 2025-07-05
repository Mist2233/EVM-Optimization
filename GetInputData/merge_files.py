import pandas as pd

# ---- Step 1: Load the CSV files ----
main_file = '200k_transactions.csv'
input_file = 'transaction_inputs.csv'

print(f"Load the main file: {main_file}...")
df_main = pd.read_csv(main_file)

print(f"Load the input data file: {input_file}...")
df_input = pd.read_csv(input_file)

print("Loading finished!")
print(f"{len(df_main)} rows in main file.")
print(f"{len(df_input)} rows in input file.")


# ---- Step 2: Merge Data ----
print("Merging starts...")

df_main['transactionHash'] = df_main['transactionHash'].str.lower()
df_input['tx_hash'] = df_input['tx_hash'].str.lower()

merged_df = pd.merge(df_main, df_input, how='left', left_on='transactionHash', right_on='tx_hash')

print("Merging completed!")

# ---- Step 3: Clean the table ----
merged_df = merged_df.drop(columns=['tx_hash'])

merged_df = merged_df.rename(columns={"input_data": "inputData"})

print("The table has been reorganized!")

# ---- Step 4: Store the file ----

output_file = "200k_transactions_with_inputs.csv"

print(f"Storing the output to {output_file}...")
merged_df.to_csv(output_file, index=False)

print("All done! Script finished!")