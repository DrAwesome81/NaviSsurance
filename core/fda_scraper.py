from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import pandas as pd
import time
import os
from datetime import datetime

# Check if within visiting hours (11 PM–5 AM EDT)
now = datetime.now().astimezone().hour
if not (23 <= now or now < 5):
    print("Outside FDA visiting hours (11 PM–5 AM EDT). Proceed with caution.")

# Setup Selenium with Brave
brave_path = "C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe"  # Adjust path if needed
options = webdriver.ChromeOptions()
options.binary_location = brave_path
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
driver.get("https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfPMN/pmn.cfm")
time.sleep(30)  # Respect hit-rate

# Search by product code
product_code = "LNH"  # Replace with desired code
driver.find_element(By.NAME, "PRODUCTCODE").send_keys(product_code)
driver.find_element(By.NAME, "STARTDATE").send_keys("01/01/2020")
driver.find_element(By.NAME, "ENDDATE").send_keys("06/05/2025")
driver.find_element(By.XPATH, "//input[@value='Search']").click()
time.sleep(30)

# Export spreadsheet
export_button = driver.find_element(By.XPATH, "//a[contains(text(), 'Export to Excel')]")  # Adjust XPath
export_button.click()
time.sleep(30)

# Handle pagination (>500 records)
page = 1
while True:
    try:
        next_button = driver.find_element(By.XPATH, "//a[contains(text(), 'Next')]")
        next_button.click()
        time.sleep(30)
        export_button = driver.find_element(By.XPATH, "//a[contains(text(), 'Export to Excel')]")
        export_button.click()
        time.sleep(30)
        page += 1
    except:
        break
driver.quit()

# Parse CSVs
download_dir = "C:/Users/adamo/Downloads"  # Adjust path
csv_files = [f for f in os.listdir(download_dir) if f.startswith("510k_export") and f.endswith(".csv")]
dfs = [pd.read_csv(os.path.join(download_dir, f)) for f in csv_files]
data = pd.concat(dfs, ignore_index=True)

# Calculate clearance time
data["DATE_RECEIVED"] = pd.to_datetime(data["DATE_RECEIVED"])
data["DECISIONDATE"] = pd.to_datetime(data["DECISIONDATE"])
data["CLEARANCE_DAYS"] = (data["DECISIONDATE"] - data["DATE_RECEIVED"]).dt.days
avg_days = data["CLEARANCE_DAYS"].mean()
print(f"Average clearance time for {product_code}: {avg_days:.1f} days")

# Save for NaviSsurance
data.to_csv(f"data/fda_510k/{product_code}_export.csv", index=False) 