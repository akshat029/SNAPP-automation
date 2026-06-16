import os
import smartsheet
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("SMARTSHEET_TOKEN")

if not token:
    print("Error: SMARTSHEET_TOKEN not found in .env file.")
    exit(1)

client = smartsheet.Smartsheet(token)
client.errors_as_exceptions(True)

print("Fetching sheets...\n")
try:
    response = client.Sheets.list_sheets(include_all=True)
    
    found = False
    for sheet in response.data:
        if "trial cases" in sheet.name.lower():
            print(f"FOUND MATCH: '{sheet.name}' -> ID: {sheet.id}")
            found = True
        
    if not found:
        print("Exact match not found. Here are all your sheets:")
        print("-" * 50)
        for sheet in response.data:
            print(f"ID: {sheet.id:<20} Name: {sheet.name}")
            
except Exception as e:
    print(f"Error fetching sheets: {e}")
