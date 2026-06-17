import sys
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
file_path = r"C:\Users\Family\Downloads\Yaa.xlsx"

df = pd.read_excel(file_path, sheet_name="Orders")
pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', None)
pd.set_option('display.width', 1000)

print(df)
