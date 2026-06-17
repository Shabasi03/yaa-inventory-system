import sys
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
file_path = r"C:\Users\Family\Downloads\Yaa.xlsx"

xl = pd.ExcelFile(file_path)
for sheet in xl.sheet_names:
    print(f"=== Sheet: {sheet} ===")
    df = pd.read_excel(file_path, sheet_name=sheet)
    print(df)
    print("\n")
