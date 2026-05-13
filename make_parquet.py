import pandas as pd

# 1. Load the CSV telling Python to split at the semicolon
df = pd.read_csv("ProjectTrackerPP_Cleaned_NA.csv", sep=';', low_memory=False)

# 2. Check if it worked (it should print a clean list of names)
print("Corrected Columns:", df.columns.tolist())

# 3. Save this properly formatted version
df.to_parquet("ProjectTracker_Combined.parquet")

print("Physical file 'ProjectTracker_Combined.parquet' is now corrected and saved!")