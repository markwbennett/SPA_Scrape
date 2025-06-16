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

# Use "All Courts" option to search all 17 Texas courts at once
# (15 Courts of Appeals + Supreme Court + Court of Criminal Appeals)
USE_ALL_COURTS = True

def setup_browser(headless=False):
    """Configure and return a Chrome browser instance"""
    import tempfile
    import shutil
    
    options = webdriver.ChromeOptions()
    
    if headless:
        options.add_argument('--headless=new')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--window-size=1920,1080')
    
    # Create unique temporary directory for Chrome user data
    temp_dir = tempfile.mkdtemp(prefix='chrome_scraper_')
    
    # Add options to handle potential issues
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument(f'--user-data-dir={temp_dir}')
    options.add_argument('--no-first-run')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-dev-shm-usage')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver

def search_by_attorney_bar_number(driver, bar_number):
    """Search for cases by attorney bar number across all Texas courts"""
    print(f"\n🔍 Searching for bar number {bar_number} across all Texas courts")
    
    # Navigate to search page
    search_url = "https://search.txcourts.gov/CaseSearch.aspx"
    print(f"📄 Navigating to: {search_url}")
    driver.get(search_url)
    
    try:
        # Wait for page to load
        print("⏳ Waiting for search page to load...")
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_txtAttorneyNameOrBarNumber"))
        )
        print("✅ Search page loaded successfully")
        
        # Debug: Check what elements are actually on the page
        print("🔍 Debugging: Checking page elements...")
        page_title = driver.title
        print(f"📄 Page title: {page_title}")
        
        # Check if we can find key elements
        elements_to_check = [
            ("ctl00_ContentPlaceHolder1_txtAttorneyNameOrBarNumber", "Attorney bar number field"),
            ("ctl00_ContentPlaceHolder1_chkAllCourts", "All Courts checkbox"),
            ("ctl00_ContentPlaceHolder1_chkExcludeInactive", "Exclude inactive checkbox"),
            ("ctl00_ContentPlaceHolder1_btnSearch", "Search button")
        ]
        
        for element_id, description in elements_to_check:
            try:
                element = driver.find_element(By.ID, element_id)
                print(f"✅ Found: {description}")
            except:
                print(f"❌ Missing: {description} (ID: {element_id})")
        
        # Check "All Courts" checkbox to search across all 17 courts
        print("🏛️ Selecting 'All Courts' option...")
        try:
            all_courts_checkbox = driver.find_element(By.ID, "ctl00_ContentPlaceHolder1_chkAllCourts")
            if not all_courts_checkbox.is_selected():
                all_courts_checkbox.click()
                print("✅ Selected 'All Courts' option (17 courts)")
            else:
                print("✅ 'All Courts' option already selected")
        except Exception as e:
            print(f"❌ Warning: Could not select 'All Courts' checkbox: {str(e)}")
        
        # Clear and enter bar number in attorney bar number field
        print(f"📝 Entering bar number: {bar_number}")
        bar_number_field = driver.find_element(By.ID, "ctl00_ContentPlaceHolder1_txtAttorneyNameOrBarNumber")
        bar_number_field.clear()
        bar_number_field.send_keys(bar_number)
        print("✅ Bar number entered")
        
        # Check "Exclude" checkbox to exclude inactive cases
        print("🚫 Setting to exclude inactive cases...")
        try:
            exclude_inactive_checkbox = driver.find_element(By.ID, "ctl00_ContentPlaceHolder1_chkExcludeInactive")
            if not exclude_inactive_checkbox.is_selected():
                exclude_inactive_checkbox.click()
                print("✅ Selected 'Exclude' inactive cases option")
            else:
                print("✅ 'Exclude' inactive cases already selected")
        except Exception as e:
            print(f"❌ Warning: Could not select 'Exclude' inactive cases checkbox: {str(e)}")
        
        # Click search button
        print("🔍 Initiating search...")
        search_button = driver.find_element(By.ID, "ctl00_ContentPlaceHolder1_btnSearch")
        search_button.click()
        print("⏳ Search submitted, waiting for response...")
        time.sleep(3)  # Give the server time to process the request
        
        # Wait for results or no results message
        print("⏳ Waiting for search results...")
        try:
            # Wait for either results table or no results message
            WebDriverWait(driver, 60).until(  # Increased timeout to 60 seconds
                EC.any_of(
                    EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_grdCases_ctl00")),
                    EC.presence_of_element_located((By.CLASS_NAME, "rgNoRecords")),
                    EC.presence_of_element_located((By.XPATH, "//span[contains(text(), 'No records')]"))
                )
            )
            print("✅ Search results loaded")
            
            # Debug: Check what we got
            current_url = driver.current_url
            print(f"📍 Current URL: {current_url}")
            
        except Exception as e:
            print(f"❌ Timeout waiting for search results: {str(e)}")
            print(f"📍 Current URL: {driver.current_url}")
            return []
        
        # Check if no results
        no_results = driver.find_elements(By.CLASS_NAME, "rgNoRecords")
        if no_results:
            print(f"📭 No cases found for bar number {bar_number}")
            return []
        
        # Extract case numbers from all pages
        case_numbers = []
        page_num = 1
        
        # Try to get total count from page info
        try:
            # Look for pagination info that might show total results
            page_info_elements = driver.find_elements(By.CSS_SELECTOR, ".rgInfoPart, .rgWrap, .rgPager")
            for element in page_info_elements:
                text = element.text.strip()
                if "of" in text.lower() and any(char.isdigit() for char in text):
                    print(f"📊 Pagination info: {text}")
        except:
            pass
        
        while True:
            print(f"📄 Processing page {page_num}")
            
            # Get current page results
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            page_cases = get_case_numbers_from_page(soup)
            
            if not page_cases:
                print(f"📭 No cases found on page {page_num}")
                break
                
            case_numbers.extend(page_cases)
            print(f"✅ Found {len(page_cases)} cases on page {page_num}")
            
            # Check for next page - try multiple selectors
            next_button = None
            next_selectors = [
                "input.rgPageNext[title='Next Page']",
                "input[title='Next Page']",
                "a[title='Next Page']",
                ".rgPageNext",
                "input[value='Next']"
            ]
            
            for selector in next_selectors:
                next_buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                if next_buttons and next_buttons[0].is_enabled():
                    next_button = next_buttons[0]
                    print(f"✅ Found next page button with selector: {selector}")
                    break
            
            if not next_button:
                print(f"🏁 No more pages - pagination complete (tried {len(next_selectors)} selectors)")
                break
            
            # Click next page
            print(f"➡️ Moving to page {page_num + 1}")
            try:
                driver.execute_script("arguments[0].click();", next_button)
            except Exception as e:
                print(f"❌ Error clicking next page: {str(e)}")
                try:
                    next_button.click()
                except:
                    print("❌ Both JavaScript and regular click failed")
                    break
            page_num += 1
            
            # Wait for new page to load
            try:
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_grdCases_ctl00"))
                )
                time.sleep(2)  # Additional wait for page stability
            except:
                print(f"❌ Timeout waiting for page {page_num}")
                break
        
        print(f"📈 Pagination complete: Found {len(case_numbers)} total cases across {page_num} pages")
        return case_numbers
        
    except Exception as e:
        print(f"❌ Error searching for bar number {bar_number}: {str(e)}")
        # Save page source for debugging
        try:
            with open(f"error_page_source_{bar_number}.html", "w") as f:
                f.write(driver.page_source)
            print(f"📄 Page source saved: error_page_source_{bar_number}.html")
        except:
            pass
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
    print("🚀 Starting Texas Court of Appeals Case Scraper")
    print("=" * 60)
    
    # Create timestamped output folder
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_folder = os.path.join(BASE_DIR, f"attorney_cases_{timestamp}")
    os.makedirs(output_folder, exist_ok=True)
    
    print(f"📁 Output folder: {output_folder}")
    print(f"🎯 Target bar numbers: {', '.join(BAR_NUMBERS)}")
    print("🏛️ Searching across all 17 Texas courts:")
    print("   • 15 Courts of Appeals (1st-15th)")
    print("   • Supreme Court of Texas (SCOTX)")
    print("   • Court of Criminal Appeals (CCA)")
    print("🚫 Excluding inactive cases")
    print("=" * 60)
    
    # Start browser
    print("🌐 Starting Chrome browser (headless mode)...")
    driver = setup_browser(headless=True)
    print("✅ Browser started successfully")
    
    all_cases = {}
    all_case_details = []
    
    try:
        # Search all courts for each bar number
        for i, bar_number in enumerate(BAR_NUMBERS, 1):
            print(f"\n{'='*20} BAR NUMBER {i}/{len(BAR_NUMBERS)} {'='*20}")
            print(f"🎯 Target: {bar_number}")
            
            try:
                cases = search_by_attorney_bar_number(driver, bar_number)
                all_cases[bar_number] = cases
                print(f"✅ Search complete: Found {len(cases)} cases for {bar_number}")
                if i < len(BAR_NUMBERS):
                    print("⏳ Pausing 3 seconds before next search...")
                    time.sleep(3)  # Brief pause between bar number searches
            except Exception as e:
                print(f"❌ Error searching for bar number {bar_number}: {str(e)}")
                all_cases[bar_number] = []
                continue
        
        # Get all unique case numbers across all bar numbers
        all_unique_cases = set()
        for cases in all_cases.values():
            all_unique_cases.update(cases)
        
        print(f"\n📊 SEARCH SUMMARY")
        print("=" * 40)
        for bar_num, cases in all_cases.items():
            print(f"   {bar_num}: {len(cases)} cases")
        print(f"📈 Total unique cases: {len(all_unique_cases)}")
        print("=" * 40)
        
        if not all_unique_cases:
            print("❌ No cases found for any bar numbers. Exiting.")
            return
        
        # Now visit each case page and extract detailed information
        print(f"\n📋 EXTRACTING DETAILED CASE INFORMATION")
        print(f"🔍 Processing {len(all_unique_cases)} unique cases...")
        progress_bar = tqdm(list(all_unique_cases), desc="🔍 Processing cases", unit="case")
        
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
        print(f"\n💾 SAVING RESULTS")
        print("=" * 40)
        print(f"📁 Output folder: {output_folder}")
        
        # Save summary by bar number
        summary_file = os.path.join(output_folder, "cases_by_bar_number.json")
        with open(summary_file, 'w') as f:
            json.dump(all_cases, f, indent=2)
        print(f"✅ Saved: cases_by_bar_number.json")
        
        # Save detailed case information
        details_file = os.path.join(output_folder, "case_details.json")
        with open(details_file, 'w') as f:
            json.dump(all_case_details, f, indent=2)
        print(f"✅ Saved: case_details.json")
        
        # Create summary report
        report_file = os.path.join(output_folder, "summary_report.txt")
        total_docs = sum(len(case['documents']) for case in all_case_details)
        
        with open(report_file, 'w') as f:
            f.write(f"Attorney Case Search Report\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            f.write(f"Bar Numbers Searched: {', '.join(BAR_NUMBERS)}\n")
            f.write("Courts Searched: All 17 Texas courts (15 Courts of Appeals + Supreme Court + Court of Criminal Appeals)\n\n")
            
            f.write("Cases by Bar Number:\n")
            for bar_num, cases in all_cases.items():
                f.write(f"  {bar_num}: {len(cases)} cases\n")
            
            f.write(f"\nTotal Unique Cases: {len(all_unique_cases)}\n")
            f.write(f"Total Documents Found: {total_docs}\n")
        
        print(f"✅ Saved: summary_report.txt")
        print("=" * 40)
        
        print(f"\n🎉 SCRAPING COMPLETE!")
        print("=" * 60)
        print(f"📈 Results Summary:")
        print(f"   • {len(all_unique_cases)} unique cases found")
        print(f"   • {total_docs} documents extracted")
        print(f"   • Results saved to: {output_folder}")
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ Error during scraping: {str(e)}")
    finally:
        print("🌐 Closing browser...")
        driver.quit()
        print("✅ Browser closed")

if __name__ == "__main__":
    scrape_attorney_cases() 