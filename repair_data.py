import pandas as pd
import os

CSV_SOURCE = "ProjectTrackerPP_Cleaned_NA.csv" 
OUTPUT_PARQUET = "ProjectTracker_Combined.parquet"

def repair_database():
    if not os.path.exists(CSV_SOURCE):
        print(f"Error: Could not find {CSV_SOURCE}")
        return

    print(f"Reading CSV file: {CSV_SOURCE}...")
    
    try:
        # 1. Force comma separation and strip spaces from headers
        df = pd.read_csv(CSV_SOURCE, sep=',', dtype=str, skipinitialspace=True)
        
        # 2. Clean up column names (removes quotes and extra spaces)
        df.columns = [c.strip().replace('"', '') for c in df.columns]

        # 3. FIX THE PRE-PROD COLUMN
        target_col = "Pre-Prod No."
        
        if target_col in df.columns:
            # Strip decimal points and whitespace
            df[target_col] = (
                df[target_col]
                .fillna('')
                .astype(str)
                .str.replace(r'\.0$', '', regex=True)
                .str.strip()
            )
            print(f"Success: Found and cleaned '{target_col}'")
        else:
            print("ERROR: Column 'Pre-Prod No.' still not recognized as a separate column.")
            print("Detected Columns:", df.columns.tolist()[:3], "... (shortened list)")
            return

        # 4. SAVE TO PARQUET (index=False is key)
        df.to_parquet(OUTPUT_PARQUET, index=False)
        
        print("-" * 30)
        print(f"Done! Created {OUTPUT_PARQUET}")
        print("First 5 IDs in the new file:", df[target_col].head().tolist())
        print("-" * 30)

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    repair_database()