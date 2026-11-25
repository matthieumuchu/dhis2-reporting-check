"""Run the whole project.

Offline (default, uses the sample data):  python run_all.py
Live DHIS2 server:                         python run_all.py --live
"""
import subprocess
import sys

live = "--live" in sys.argv
steps = [["src/fetch.py"]] if live else [["src/generate_sample.py"], ["src/fetch.py", "--offline"]]
steps.append(["src/analyse.py"])
for step in steps:
    print(f"\n=== {' '.join(step)} ===")
    subprocess.run([sys.executable, *step], check=True)
print("\nDone. Open outputs/dhis2_reporting_dashboard.html and outputs/dhis2_reporting_report.xlsx.")
