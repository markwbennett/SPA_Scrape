#!./.venv/bin/python
import os
import json
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from bs4 import BeautifulSoup
from tqdm import tqdm

# Base directory for output files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Bar numbers to search for
BAR_NUMBERS = [
    "24032600",
    "24053705", 
    "24031632"
]

# All Texas Court of Appeals codes
COURT_CODES = [
    "coa01",  # 1st Court of Appeals
    "coa02",  # 2nd Court of Appeals
    "coa03",  # 3rd Court of Appeals
    "coa04",  # 4th Court of Appeals
    "coa05",  # 5th Court of Appeals
    "coa06",  # 6th Court of Appeals
    "coa07",  # 7th Court of Appeals
    "coa08",  # 8th Court of Appeals
    "coa09",  # 9th Court of Appeals
    "coa10",  # 10th Court of Appeals
    "coa11",  # 11th Court of Appeals
    "coa12",  # 12th Court of Appeals
    "coa13",  # 13th Court of Appeals
    "coa14",  # 14th Court of Appeals
    "cossup"  # Supreme Court
]

def setup_browser(headless=False):
    """Configure and return a Chrome browser instance"""
    options = webdriver.ChromeOptions()
    
    if headless:
        options.add_argument('--headless=new')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--window-size=1920,1080')
    
    # Add options to handle potential issues
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver

def search_by_attorney_bar_number(driver, bar_number, court_code):
    """Search for cases by attorney bar number in a specific court"""
    print(f"Searching for bar number {bar_number} in court {court_code}")
    
    # Navigate to search page for specific court
    search_url = f"https://search.txcourts.gov/CaseSearch.aspx?coa={court_code}"
    driver.get(search_url)
    
    try:
        # Wait for page to load
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_txtAttyBarNumber"))
        )
        
        # Clear and enter bar number in attorney bar number field
        bar_number_field = driver.find_element(By.ID, "ctl00_ContentPlaceHolder1_txtAttyBarNumber")
        bar_number_field.clear()
        bar_number_field.send_keys(bar_number)
        
        # Set case status to "Active" only (exclude inactive cases)
        try:
            status_dropdown = Select(driver.find_element(By.ID, "ctl00_ContentPlaceHolder1_ddlCaseStatus"))
            status_dropdown.select_by_visible_text("Active")
        except:
            print(f"Warning: Could not set case status filter for {court_code}")
        
        # Click search button
        search_button = driver.find_element(By.ID, "ctl00_ContentPlaceHolder1_btnSearch")
        search_button.click()
        
        # Wait for results or no results message
        try:
            # Wait for either results table or no results message
            WebDriverWait(driver, 30).until(
                EC.any_of(
                    EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_grdCases_ctl00")),
                    EC.presence_of_element_located((By.CLASS_NAME, "rgNoRecords"))
                )
            )
        except:
            print(f"Timeout waiting for search results in {court_code}")
            return []
        
        # Check if no results
        no_results = driver.find_elements(By.CLASS_NAME, "rgNoRecords")
        if no_results:
            print(f"No cases found for bar number {bar_number} in {court_code}")
            return []
        
        # Extract case numbers from all pages
        case_numbers = []
        page_num = 1
        
        while True:
            print(f"Processing page {page_num} for {court_code}")
            
            # Get current page results
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            page_cases = get_case_numbers_from_page(soup)
            
            if not page_cases:
                print(f"No cases found on page {page_num}")
                break
                
            case_numbers.extend(page_cases)
            print(f"Found {len(page_cases)} cases on page {page_num}")
            
            # Check for next page
            next_buttons = driver.find_elements(By.CSS_SELECTOR, "input.rgPageNext[title='Next Page']")
            if not next_buttons or not next_buttons[0].is_enabled():
                print(f"No more pages for {court_code}")
                break
            
            # Click next page
            driver.execute_script("arguments[0].click();", next_buttons[0])
            page_num += 1
            
            # Wait for new page to load
            try:
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_grdCases_ctl00"))
                )
                time.sleep(2)  # Additional wait for page stability
            except:
                print(f"Timeout waiting for page {page_num} in {court_code}")
                break
        
        return case_numbers
        
    except Exception as e:
        print(f"Error searching {court_code} for bar number {bar_number}: {str(e)}")
        return []

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

def extract_case_details(soup, case_number):
    """Extract case details including parties and attorney information"""
    case_info = {
        'case_number': case_number,
        'parties': [],
        'attorneys': [],
        'documents': []
    }
    
    # Extract party information
    try:
        # Look for party information in various possible locations
        party_sections = soup.find_all('div', class_='panel-content')
        for section in party_sections:
            # Extract party names and roles
            party_rows = section.find_all('div', class_='row-fluid')
            for row in party_rows:
                party_text = row.get_text(strip=True)
                if any(keyword in party_text.lower() for keyword in ['appellant', 'appellee', 'petitioner', 'respondent']):
                    case_info['parties'].append(party_text)
    except Exception as e:
        print(f"Error extracting parties for {case_number}: {str(e)}")
    
    # Extract attorney information
    try:
        # Look for attorney information
        attorney_sections = soup.find_all('div', class_='span4')
        for section in attorney_sections:
            attorney_text = section.get_text(strip=True)
            if 'attorney' in attorney_text.lower() or any(bar_num in attorney_text for bar_num in BAR_NUMBERS):
                case_info['attorneys'].append(attorney_text)
    except Exception as e:
        print(f"Error extracting attorneys for {case_number}: {str(e)}")
    
    # Extract document links
    case_info['documents'] = extract_document_links(soup, case_number)
    
    return case_info

def extract_document_links(soup, case_number):
    """Extract all document links from a case page with metadata"""
    document_links = []
    
    # Process events table
    events_table = soup.find('table', {'id': 'ctl00_ContentPlaceHolder1_grdEvents_ctl00'})
    if events_table:
        for row in events_table.find_all('tr'):
            if row.find('th'):  # Skip header row
                continue
                
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
                    
                    document_links.append({
                        'case_number': case_number,
                        'date': event_date,
                        'event_type': event_type,
                        'disposition': disposition,
                        'description': doc_description,
                        'doc_type': doc_type,
                        'media_id': media_id,
                        'url': f"https://search.txcourts.gov/{link['href']}",
                        'table_type': 'events'
                    })
    
    # Process briefs table
    briefs_table = soup.find('table', {'id': 'ctl00_ContentPlaceHolder1_grdBriefs_ctl00'})
    if briefs_table:
        for row in briefs_table.find_all('tr'):
            if row.find('th'):  # Skip header row
                continue
                
            cells = row.find_all('td')
            if len(cells) < 4:
                continue
                
            event_date = cells[0].text.strip()
            event_type = cells[1].text.strip()
            disposition = ""  # Briefs don't typically have dispositions
            
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
                    
                    doc_description = desc_cell.text.strip()
                    
                    doc_type = ""
                    try:
                        if 'DT=' in link['href']:
                            doc_type = link['href'].split('DT=')[1].split('&')[0]
                    except:
                        pass
                    
                    media_id = None
                    try:
                        if 'MediaID=' in link['href']:
                            media_id = link['href'].split('MediaID=')[1].split('&')[0]
                        elif 'MediaVersionID=' in link['href']:
                            media_id = link['href'].split('MediaVersionID=')[1].split('&')[0]
                    except:
                        media_id = link['href']
                    
                    document_links.append({
                        'case_number': case_number,
                        'date': event_date,
                        'event_type': event_type,
                        'disposition': disposition,
                        'description': doc_description,
                        'doc_type': doc_type,
                        'media_id': media_id,
                        'url': f"https://search.txcourts.gov/{link['href']}",
                        'table_type': 'briefs'
                    })
    
    return document_links

def scrape_attorney_cases():
    """Main function to scrape cases for specific attorney bar numbers"""
    # Create timestamped output folder
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_folder = os.path.join(BASE_DIR, f"attorney_cases_{timestamp}")
    os.makedirs(output_folder, exist_ok=True)
    
    print(f"Output folder: {output_folder}")
    print(f"Searching for bar numbers: {', '.join(BAR_NUMBERS)}")
    print(f"Searching across {len(COURT_CODES)} courts")
    
    # Start browser
    print("Starting browser...")
    driver = setup_browser(headless=False)
    
    all_cases = {}
    all_case_details = []
    
    try:
        # Search each court for each bar number
        for bar_number in BAR_NUMBERS:
            print(f"\n=== Searching for Bar Number: {bar_number} ===")
            bar_cases = []
            
            for court_code in COURT_CODES:
                try:
                    cases = search_by_attorney_bar_number(driver, bar_number, court_code)
                    if cases:
                        print(f"Found {len(cases)} cases in {court_code}")
                        bar_cases.extend(cases)
                    time.sleep(2)  # Brief pause between court searches
                except Exception as e:
                    print(f"Error searching {court_code}: {str(e)}")
                    continue
            
            # Remove duplicates
            unique_cases = list(set(bar_cases))
            all_cases[bar_number] = unique_cases
            print(f"Total unique cases for {bar_number}: {len(unique_cases)}")
        
        # Get all unique case numbers across all bar numbers
        all_unique_cases = set()
        for cases in all_cases.values():
            all_unique_cases.update(cases)
        
        print(f"\nTotal unique cases across all bar numbers: {len(all_unique_cases)}")
        
        # Now visit each case page and extract detailed information
        print("\nExtracting detailed case information...")
        progress_bar = tqdm(list(all_unique_cases), desc="Processing cases", unit="case")
        
        for case_number in progress_bar:
            progress_bar.set_description(f"Processing {case_number}")
            
            try:
                # Navigate to case page
                url = f"https://search.txcourts.gov/Case.aspx?cn={case_number}"
                driver.get(url)
                
                # Wait for page to load
                WebDriverWait(driver, 30).until(
                    EC.any_of(
                        EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_grdEvents_ctl00")),
                        EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_grdBriefs_ctl00")),
                        EC.presence_of_element_located((By.CLASS_NAME, "panel-content"))
                    )
                )
                
                # Parse page and extract details
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                case_details = extract_case_details(soup, case_number)
                
                # Add which bar numbers this case is associated with
                case_details['associated_bar_numbers'] = []
                for bar_num, cases in all_cases.items():
                    if case_number in cases:
                        case_details['associated_bar_numbers'].append(bar_num)
                
                all_case_details.append(case_details)
                
                # Update progress
                doc_count = len(case_details['documents'])
                progress_bar.set_postfix(docs=doc_count)
                
            except Exception as e:
                progress_bar.write(f"Error processing {case_number}: {str(e)}")
                continue
        
        progress_bar.close()
        
        # Save results
        print(f"\nSaving results to {output_folder}")
        
        # Save summary by bar number
        summary_file = os.path.join(output_folder, "cases_by_bar_number.json")
        with open(summary_file, 'w') as f:
            json.dump(all_cases, f, indent=2)
        
        # Save detailed case information
        details_file = os.path.join(output_folder, "case_details.json")
        with open(details_file, 'w') as f:
            json.dump(all_case_details, f, indent=2)
        
        # Create summary report
        report_file = os.path.join(output_folder, "summary_report.txt")
        with open(report_file, 'w') as f:
            f.write(f"Attorney Case Search Report\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            f.write(f"Bar Numbers Searched: {', '.join(BAR_NUMBERS)}\n")
            f.write(f"Courts Searched: {len(COURT_CODES)}\n\n")
            
            f.write("Cases by Bar Number:\n")
            total_docs = 0
            for bar_num, cases in all_cases.items():
                f.write(f"  {bar_num}: {len(cases)} cases\n")
            
            f.write(f"\nTotal Unique Cases: {len(all_unique_cases)}\n")
            
            # Count total documents
            for case in all_case_details:
                total_docs += len(case['documents'])
            
            f.write(f"Total Documents Found: {total_docs}\n")
        
        print(f"Search complete! Found {len(all_unique_cases)} unique cases with {total_docs} documents.")
        print(f"Results saved to: {output_folder}")
        
    except Exception as e:
        print(f"Error during scraping: {str(e)}")
    finally:
        print("Closing browser...")
        driver.quit()

if __name__ == "__main__":
    scrape_attorney_cases() 