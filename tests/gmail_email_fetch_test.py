import time
from core.data_fetch import DataFetcher
# Gmail email fetch tests support Pulse intel triage and 🛡️ Shield security in email processing (Gmail email tests)
# additional Pulse private memory + Shield for Gmail email fetch

def test_gmail_fetch():
    """
    Test Gmail fetching using the existing DataFetcher class
    """
    start_time = time.time()
    
    print("Initializing DataFetcher...")
    fetcher = DataFetcher()
    
    # Define the folders/labels we want to check
    folders = ['INBOX', 'News', 'NaviSure Admin']
    
    print("Fetching recent emails...")
    # Use a timestamp from 24 hours ago to get recent emails
    last_run = int(time.time()) - (24 * 60 * 60)
    
    total_emails = 0
    for folder in folders:
        print(f"\nChecking folder: {folder}")
        # Modify the search query to include the folder/label
        query = f"after:{last_run}"
        if folder != 'INBOX':
            query += f" label:{folder}"
            
        # Get emails for this folder
        emails = fetcher.gmail.users().messages().list(
            userId='me',
            q=query
        ).execute().get('messages', [])
        
        print(f"Found {len(emails)} emails in {folder}")
        total_emails += len(emails)
        
        # Fetch details for each email
        for email in emails:
            details = fetcher.get_email_details(email['id'], 'gmail')
            if details:
                headers = {h['name']: h['value'] for h in details['payload']['headers']}
                print(f"\nFrom: {headers.get('From', '')}")
                print(f"Subject: {headers.get('Subject', '')}")
                print(f"Date: {headers.get('Date', '')}")
                print(f"Folder: {folder}")
                print(f"Snippet: {details.get('snippet', '')}")
                print("-" * 50)
    
    end_time = time.time()
    print(f"\nFetch completed in {end_time - start_time:.2f} seconds")
    print(f"Total emails found: {total_emails}")

if __name__ == "__main__":
    print("Starting Gmail email fetch test...")
    test_gmail_fetch() 