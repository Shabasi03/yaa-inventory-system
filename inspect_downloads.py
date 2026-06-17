import os
import sys
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

downloads_dir = r"C:\Users\Family\Downloads"
out_path = "inspect_excel_output.txt"

with open(out_path, "w", encoding="utf-8") as f:
    f.write("=== SEARCHING EXCEL FILES FOR INVENTORY SHEETS ===\n\n")
    excel_files = [x for x in os.listdir(downloads_dir) if x.endswith(('.xlsx', '.xls', '.xlsm'))]
    
    for file in excel_files:
        path = os.path.join(downloads_dir, file)
        try:
            xl = pd.ExcelFile(path)
            f.write(f"File: {file} -> Sheets: {xl.sheet_names}\n")
            matches = []
            for sheet in xl.sheet_names:
                sheet_lower = sheet.lower()
                # Check for Arabic or English keywords
                keywords = ['product', 'customer', 'order', 'expense', 'income', 'sale', 'بضاعة', 'عملاء', 'زبائن', 'مبيعات', 'مصروفات', 'دخل', 'أرباح', 'شراء', 'بيع']
                if any(k in sheet_lower for k in keywords):
                    matches.append(sheet)
            
            if matches:
                f.write(f"  --> MATCHING SHEETS FOUND: {matches}\n")
                for sheet in matches:
                    df = pd.read_excel(path, sheet_name=sheet, nrows=5)
                    f.write(f"    Sheet: {sheet} (Shape: {df.shape})\n")
                    f.write(f"    Columns: {list(df.columns)}\n")
                    f.write("    Sample data:\n")
                    f.write(df.to_string() + "\n\n")
        except Exception as e:
            f.write(f"File: {file} -> Error reading: {e}\n\n")

print("Excel check complete. Output written to inspect_excel_output.txt")
