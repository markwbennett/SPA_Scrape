#!./.venv/bin/python
import os
import json
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from tqdm import tqdm

# Base directory for output files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def setup_browser(headless=False):
    """Configure and return a Chrome browser instance"""
    options = webdriver.ChromeOptions()
    
    if headless:
        options.add_argument('--headless=new')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--window-size=1920,1080')
    
    driver = webdriver.Chrome(options=options)
    return driver

def get_case_numbers_from_page(soup):
    """Extract case numbers from search results page"""
    cases = []
    table = soup.find('table', {'id': 'ctl00_ContentPlaceHolder1_grdCases_ctl00'})
    if not table:
        return cases
        
    for row in table.find_all('tr'):
        link = row.find('a', href=True)
        if link and 'Case.aspx?cn=' in link['href']:
            case_number = link.text.strip()
            if case_number:  # Only add non-empty case numbers
                cases.append(case_number)
            
    return cases

def extract_document_links(soup, case_number):
    """Extract all document links from a case page with metadata"""
    document_links = []
    
    # Process events table
    events_table = soup.find('table', {'id': 'ctl00_ContentPlaceHolder1_grdEvents_ctl00'})
    if events_table:
        # Find all rows with events
        for row in events_table.find_all('tr'):
            # Skip header row
            if row.find('th'):
                continue
                
            # Extract event metadata
            cells = row.find_all('td')
            if len(cells) < 4:
                continue
                
            event_date = cells[0].text.strip()
            event_type = cells[1].text.strip()
            disposition = cells[2].text.strip()
            
            # Extract document links
            doc_cell = cells[3]
            doc_tables = doc_cell.find_all('table', {'class': 'docGrid'})
            
            for doc_table in doc_tables:
                for doc_row in doc_table.find_all('tr'):
                    doc_cells = doc_row.find_all('td')
                    if len(doc_cells) < 2:
                        continue
                    
                    link_cell = doc_cells[0]
                    desc_cell = doc_cells[1]
                    
                    link = link_cell.find('a', href=True)
                    if not link or 'SearchMedia.aspx' not in link['href']:
                        continue
                    
                    # Get document description
                    doc_description = desc_cell.text.strip()
                    
                    # Get document type from URL
                    doc_type = ""
                    try:
                        if 'DT=' in link['href']:
                            doc_type = link['href'].split('DT=')[1].split('&')[0]
                    except:
                        pass
                    
                    # Extract MediaID for deduplication
                    media_id = None
                    try:
                        if 'MediaID=' in link['href']:
                            media_id = link['href'].split('MediaID=')[1].split('&')[0]
                        elif 'MediaVersionID=' in link['href']:
                            media_id = link['href'].split('MediaVersionID=')[1].split('&')[0]
                    except:
                        media_id = link['href']
                    
                    # Add document link with metadata
                    document_links.append({
                        'case_number': case_number,
                        'date': event_date,
                        'event_type': event_type,
                        'disposition': disposition,
                        'description': doc_description,
                        'doc_type': doc_type,
                        'media_id': media_id,
                        'url': f"https://search.txcourts.gov/{link['href']}"
                    })
    
    # Process briefs table
    briefs_table = soup.find('table', {'id': 'ctl00_ContentPlaceHolder1_grdBriefs_ctl00'})
    if briefs_table:
        # Process similar to events table
        for row in briefs_table.find_all('tr'):
            # Skip header row
            if row.find('th'):
                continue
                
            # Extract event metadata
            cells = row.find_all('td')
            if len(cells) < 4:
                continue
                
            event_date = cells[0].text.strip()
            event_type = cells[1].text.strip()
            disposition = "" # Briefs don't typically have dispositions
            
            # Look for document links
            doc_tables = row.find_all('table', {'class': 'docGrid'})
            
            for doc_table in doc_tables:
                for doc_row in doc_table.find_all('tr'):
                    doc_cells = doc_row.find_all('td')
                    if len(doc_cells) < 2:
                        continue
                    
                    link_cell = doc_cells[0]
                    desc_cell = doc_cells[1]
                    
                    link = link_cell.find('a', href=True)
                    if not link or 'SearchMedia.aspx' not in link['href']:
                        continue
                    
                    # Get document description
                    doc_description = desc_cell.text.strip()
                    
                    # Get document type from URL
                    doc_type = ""
                    try:
                        if 'DT=' in link['href']:
                            doc_type = link['href'].split('DT=')[1].split('&')[0]
                    except:
                        pass
                    
                    # Extract MediaID for deduplication
                    media_id = None
                    try:
                        if 'MediaID=' in link['href']:
                            media_id = link['href'].split('MediaID=')[1].split('&')[0]
                        elif 'MediaVersionID=' in link['href']:
                            media_id = link['href'].split('MediaVersionID=')[1].split('&')[0]
                    except:
                        media_id = link['href']
                    
                    # Add document link with metadata
                    document_links.append({
                        'case_number': case_number,
                        'date': event_date,
                        'event_type': event_type,
                        'disposition': disposition,
                        'description': doc_description,
                        'doc_type': doc_type,
                        'media_id': media_id,
                        'url': f"https://search.txcourts.gov/{link['href']}"
                    })
    
    return document_links

def scrape_court_of_appeals():
    """Main function to scrape Texas Court of Appeals documents"""
    # Create timestamped output folder
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_folder = os.path.join(BASE_DIR, f"coa_scrape_{timestamp}")
    os.makedirs(output_folder, exist_ok=True)
    
    # Start browser
    print("Starting browser...")
    driver = setup_browser(headless=False)
    
    try:
        # Open search page
        print("Opening search page...")
        driver.get("https://search.txcourts.gov/CaseSearch.aspx?coa=cossup")
        
        # Wait for search page to load
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_grdCases_ctl00"))
        )
        
        # Let user perform search
        print("Please perform your search in the browser window...")
        print("Once you've submitted your search, the script will wait for results...")
        
        # Wait for search results to appear
        WebDriverWait(driver, 300).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "#ctl00_ContentPlaceHolder1_grdCases_ctl00 tr.rgRow, #ctl00_ContentPlaceHolder1_grdCases_ctl00 tr.rgAltRow"))
        )
        print("Search results found!")
        
        # Extract case numbers from search results
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        case_numbers = get_case_numbers_from_page(soup)
        
        # Check for additional pages of results
        seen_cases = set(case_numbers)
        current_page = 1
        prev_page_cases = set(case_numbers)  # To detect when page hasn't changed
        
        while True:
            # Check for next page button
            next_buttons = driver.find_elements(By.CSS_SELECTOR, "input.rgPageNext[title='Next Page']")
            if not next_buttons:
                print("No more pages (no next button)")
                break
                
            # Try to click next page
            print(f"Loading page {current_page + 1} of results...")
            driver.execute_script("arguments[0].click();", next_buttons[0])
            current_page += 1
            
            # Wait for new results to appear
            try:
                WebDriverWait(driver, 30).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, "#ctl00_ContentPlaceHolder1_grdCases_ctl00 tr.rgRow, #ctl00_ContentPlaceHolder1_grdCases_ctl00 tr.rgAltRow"))
                )
            except:
                print("Timeout waiting for next page results")
                break
            
            # Get new case numbers
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            new_cases = get_case_numbers_from_page(soup)
            
            # Check if the page content is the same as the previous page
            current_page_cases = set(new_cases)
            if current_page_cases == prev_page_cases:
                print("Page content hasn't changed - reached the end")
                break
                
            # Update previous page cases for next comparison
            prev_page_cases = current_page_cases
            
            # Add only new cases
            new_cases_found = 0
            for case in new_cases:
                if case not in seen_cases:
                    seen_cases.add(case)
                    case_numbers.append(case)
                    new_cases_found += 1
            
            print(f"Found {new_cases_found} new cases on page {current_page}")
            
            # If no new cases were found, we've likely reached the end
            if new_cases_found == 0:
                print("No new cases found on this page - reached the end")
                break
        
        print(f"Found {len(case_numbers)} cases.")
        
        # Now visit each case page and extract document links
        all_document_links = []
        
        print("Collecting document information...")
        # Initialize progress bar with cases
        progress_bar = tqdm(case_numbers, desc="Processing cases", unit="case")
        doc_counter = 0  # Counter for found documents
        
        for case_number in progress_bar:
            # Navigate to case page
            url = f"https://search.txcourts.gov/Case.aspx?cn={case_number}"
            driver.get(url)
            
            # Update progress bar description with current case
            progress_bar.set_description(f"Case {case_number}")
            
            # Wait for page to load (either events or briefs table should be present)
            try:
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 
                        "#ctl00_ContentPlaceHolder1_grdEvents_ctl00, #ctl00_ContentPlaceHolder1_grdBriefs_ctl00"))
                )
            except:
                progress_bar.write(f"Warning: Timeout loading case {case_number}")
                continue
            
            # Parse page
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Extract document links
            case_links = extract_document_links(soup, case_number)
            all_document_links.extend(case_links)
            
            # Update document counter and show in progress bar
            doc_counter += len(case_links)
            progress_bar.set_postfix(docs_found=doc_counter)
            
            # If we found documents, show a message
            if case_links:
                progress_bar.write(f"Found {len(case_links)} documents for case {case_number}")
        
        # Close the progress bar
        progress_bar.close()
        
        # Remove duplicates based on media_id
        unique_links = []
        seen_media_ids = set()
        
        for link in all_document_links:
            if link['media_id'] and link['media_id'] not in seen_media_ids:
                seen_media_ids.add(link['media_id'])
                unique_links.append(link)
        
        # Save to JSON file
        json_file = os.path.join(output_folder, "document_links.json")
        with open(json_file, 'w') as f:
            json.dump(unique_links, f, indent=2)
        
        # Also save as CSV for easy import
        csv_file = os.path.join(output_folder, "document_links.csv")
        with open(csv_file, 'w') as f:
            # Write header
            f.write("case_number,date,event_type,disposition,description,doc_type,media_id,url\n")
            
            # Write data
            for link in unique_links:
                f.write(f"{link['case_number']},{link['date']},{link['event_type'].replace(',', ' ')},"
                       f"{link['disposition'].replace(',', ' ')},{link['description'].replace(',', ' ')},"
                       f"{link['doc_type'].replace(',', ' ')},{link['media_id']},{link['url']}\n")
        
        # Save as HTML with clickable links
        html_file = os.path.join(output_folder, "document_links.html")
        with open(html_file, 'w') as f:
            # Write HTML header
            f.write("""<!DOCTYPE html>
<html>
<head>
    <title>Court of Appeals Documents</title>
    <link rel="stylesheet" type="text/css" href="https://cdn.datatables.net/1.13.6/css/jquery.dataTables.min.css">
    <script src="https://code.jquery.com/jquery-3.7.0.min.js"></script>
    <script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 20px;
            line-height: 1.6;
        }
        h1 {
            color: #2a5885;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th {
            background-color: #4CAF50;
            color: white;
            font-weight: bold;
            cursor: pointer;
        }
        th, td {
            padding: 8px;
            text-align: left;
            border: 1px solid #ddd;
        }
        tr:nth-child(even) {
            background-color: #f2f2f2;
        }
        a {
            color: #0066cc;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        .dataTables_filter {
            margin-bottom: 15px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Court of Appeals Documents</h1>
        <p>Generated on: """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + """</p>
        <p>Found """ + str(len(unique_links)) + """ documents across """ + str(len(case_numbers)) + """ cases.</p>
        
        <table id="documentTable" class="display">
            <thead>
                <tr>
                    <th>Case Number</th>
                    <th>Date</th>
                    <th>Event Type</th>
                    <th>Disposition</th>
                    <th>Description</th>
                    <th>Doc Type</th>
                    <th>Media ID</th>
                    <th>Document</th>
                </tr>
            </thead>
            <tbody>
""")
            
            # Write table rows
            for link in unique_links:
                f.write("                <tr>\n")
                f.write(f"                    <td>{link['case_number']}</td>\n")
                f.write(f"                    <td>{link['date']}</td>\n")
                f.write(f"                    <td>{link['event_type']}</td>\n")
                f.write(f"                    <td>{link['disposition']}</td>\n")
                f.write(f"                    <td>{link['description']}</td>\n")
                f.write(f"                    <td>{link['doc_type']}</td>\n")
                f.write(f"                    <td>{link['media_id']}</td>\n")
                f.write(f"                    <td><a href=\"{link['url']}\" target=\"_blank\">Open Document</a></td>\n")
                f.write("                </tr>\n")
            
            # Write HTML footer with JavaScript to initialize DataTable
            f.write("""            </tbody>
        </table>
    </div>
    
    <script>
        $(document).ready(function() {
            $('#documentTable').DataTable({
                paging: true,
                searching: true,
                ordering: true,
                info: true,
                pageLength: 25,
                lengthMenu: [[10, 25, 50, 100, -1], [10, 25, 50, 100, "All"]],
                language: {
                    search: "Filter records:"
                }
            });
        });
    </script>
</body>
</html>
""")
        
        # Create a human-readable summary
        summary_file = os.path.join(output_folder, "summary.txt")
        with open(summary_file, 'w') as f:
            f.write(f"Court of Appeals Document Scrape - {timestamp}\n")
            f.write("="*80 + "\n\n")
            
            f.write(f"Total cases found: {len(case_numbers)}\n")
            f.write(f"Total unique documents found: {len(unique_links)}\n\n")
            
            # Organize by case
            f.write("Documents by case:\n")
            f.write("="*80 + "\n\n")
            
            for case_number in sorted(case_numbers):
                case_docs = [link for link in unique_links if link['case_number'] == case_number]
                if case_docs:
                    f.write(f"Case: {case_number} - {len(case_docs)} documents\n")
                    f.write("-"*80 + "\n")
                    
                    for i, doc in enumerate(case_docs, 1):
                        f.write(f"{i}. Date: {doc['date']}, Event: {doc['event_type']}\n")
                        f.write(f"   Description: {doc['description']}\n")
                        if doc['disposition']:
                            f.write(f"   Disposition: {doc['disposition']}\n")
                        f.write(f"   URL: {doc['url']}\n\n")
                    
                    f.write("\n")
        
        print(f"\nFound {len(unique_links)} unique documents across {len(case_numbers)} cases.")
        print(f"Results saved to: {output_folder}")
        print(f"  - JSON: {json_file}")
        print(f"  - CSV: {csv_file}")
        print(f"  - HTML: {html_file}")
        print(f"  - Summary: {summary_file}")
        
    finally:
        # Close browser
        print("Closing browser...")
        driver.quit()

if __name__ == "__main__":
    scrape_court_of_appeals() 