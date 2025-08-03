import imaplib
import email
from datetime import datetime
import os
from dotenv import load_dotenv
import time

def fetch_recent_yahoo_emails(num_emails=10):
    """
    Fetch the most recent emails from Yahoo using IMAP.
    Returns a list of email details including sender, subject, and content.
    """
    # Load environment variables
    load_dotenv(os.path.join(os.path.dirname(__file__), "config", ".env"), override=True)
    
    # Yahoo account credentials
    yahoo_account = {
        'user': 'adamodeh81@yahoo.com',
        'pwd': os.getenv('YAHOO_APP_PASSWORD', '')
    }
    
    if not yahoo_account['pwd']:
        raise ValueError("YAHOO_APP_PASSWORD environment variable not set")
    
    emails = []
    start_time = time.time()
    
    try:
        print("Connecting to Yahoo IMAP server...")
        mail = imaplib.IMAP4_SSL('imap.mail.yahoo.com')
        
        print("Logging in...")
        mail.login(yahoo_account['user'], yahoo_account['pwd'])
        
        print("Selecting inbox...")
        mail.select('inbox')
        
        # Search for all emails and sort by date
        print("Searching for emails...")
        _, data = mail.search(None, 'ALL')
        email_ids = data[0].split()
        
        # Get the most recent emails
        recent_ids = email_ids[-num_emails:] if len(email_ids) > num_emails else email_ids
        
        print(f"Fetching {len(recent_ids)} most recent emails...")
        for num in recent_ids:
            try:
                _, msg_data = mail.fetch(num, '(RFC822)')
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                # Extract basic email information
                email_info = {
                    'id': num.decode(),
                    'date': msg['date'],
                    'from': msg['from'],
                    'subject': msg['subject'],
                    'content': ''
                }
                
                # Extract email content
                if msg.is_multipart():
                    content_parts = []
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            try:
                                content = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                                content_parts.append(content)
                            except Exception as e:
                                print(f"Error decoding part: {e}")
                    email_info['content'] = ' '.join(content_parts)
                else:
                    try:
                        email_info['content'] = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
                    except Exception as e:
                        print(f"Error decoding content: {e}")
                
                emails.append(email_info)
                print(f"Successfully fetched email: {email_info['subject']}")
                
            except Exception as e:
                print(f"Error processing email {num}: {e}")
                continue
        
        print("Logging out...")
        mail.logout()
        
    except Exception as e:
        print(f"Error during email fetch: {e}")
        return []
    
    end_time = time.time()
    print(f"\nFetch completed in {end_time - start_time:.2f} seconds")
    return emails

if __name__ == "__main__":
    print("Starting Yahoo email fetch test...")
    emails = fetch_recent_yahoo_emails()
    
    print("\nFetched Emails Summary:")
    print("-" * 50)
    for i, email in enumerate(emails, 1):
        print(f"\nEmail {i}:")
        print(f"From: {email['from']}")
        print(f"Subject: {email['subject']}")
        print(f"Date: {email['date']}")
        print(f"Content Preview: {email['content'][:200]}...")
        print("-" * 50) 