#!/usr/bin/env python3
"""
COA Case Scraper with Claude Analysis
Searches Texas Court of Appeals for cases by bar number and analyzes briefs with Claude
"""

import json
import os
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import re
from urllib.parse import urljoin

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup
import requests
from tqdm import tqdm
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
import anthropic
from dotenv import load_dotenv
import argparse

# Load environment variables
load_dotenv()

def normalize_name_for_matching(name):
    """
    Normalize a name for matching purposes, handling different formats:
    - "Smith, John A. Jr." -> "john a smith jr"
    - "John A. Smith Jr." -> "john a smith jr"
    - "SMITH, JOHN ALAN JR" -> "john alan smith jr"
    """
    if not name or not isinstance(name, str):
        return ""
    
    # Store original to check for comma format
    original = name.strip()
    
    # Remove extra whitespace and convert to lowercase
    name = name.strip().lower()
    
    # Remove common punctuation except periods in middle initials
    name = re.sub(r'[,]', ' ', name)
    
    # Normalize multiple spaces to single space
    name = re.sub(r'\s+', ' ', name).strip()
    
    # Split into parts
    parts = name.split()
    if len(parts) < 2:
        return name
    
    # Handle suffixes (Jr, Sr, II, III, IV, etc.)
    suffixes = {'jr', 'sr', 'ii', 'iii', 'iv', 'v', 'junior', 'senior'}
    suffix_parts = []
    name_parts = []
    
    for part in parts:
        clean_part = part.replace('.', '')  # Remove periods for suffix check
        if clean_part in suffixes:
            suffix_parts.append(clean_part)
        else:
            name_parts.append(part)
    
    if len(name_parts) < 2:
        return ' '.join(parts)
    
    # Create normalized form: first_name middle_names last_name suffix
    # This handles both "Last, First Middle" and "First Middle Last" formats
    if ',' in original:
        # "Last, First Middle" format
        last_name = name_parts[0]
        first_and_middle = name_parts[1:]
        normalized = ' '.join(first_and_middle + [last_name])
    else:
        # "First Middle Last" format - keep as is
        normalized = ' '.join(name_parts)
    
    # Add suffixes at the end
    if suffix_parts:
        normalized += ' ' + ' '.join(suffix_parts)
    
    return normalized.strip()

def names_match(name1, name2):
    """
    Check if two names refer to the same person, handling different formats:
    - "Smith, John A. Jr." matches "John A. Smith Jr."
    - Case insensitive matching
    - Handles suffixes and middle names/initials
    - Middle names/initials are included in first name comparison
    """
    if not name1 or not name2:
        return False
    
    norm1 = normalize_name_for_matching(name1)
    norm2 = normalize_name_for_matching(name2)
    
    # Direct match
    if norm1 == norm2:
        return True
    
    # Split into components for more flexible matching
    parts1 = norm1.split()
    parts2 = norm2.split()
    
    if len(parts1) < 2 or len(parts2) < 2:
        return False
    
    # Extract components
    suffixes = {'jr', 'sr', 'ii', 'iii', 'iv', 'v', 'junior', 'senior'}
    
    def extract_name_components(parts):
        name_parts = [p for p in parts if p not in suffixes]
        suffix_parts = [p for p in parts if p in suffixes]
        
        if len(name_parts) >= 2:
            # Last part is last name, everything else is first + middle
            last = name_parts[-1]
            first_and_middle = name_parts[:-1]
            return first_and_middle, last, suffix_parts
        return [], None, suffix_parts
    
    first_middle1, last1, suffix1 = extract_name_components(parts1)
    first_middle2, last2, suffix2 = extract_name_components(parts2)
    
    if not first_middle1 or not last1 or not first_middle2 or not last2:
        return False
    
    # Last names must match
    if last1 != last2:
        return False
    
    # Suffixes should match if both have them (allow equivalent forms)
    if suffix1 and suffix2:
        # Normalize suffix equivalents
        def normalize_suffixes(suffix_list):
            normalized = []
            for s in suffix_list:
                if s in ['sr', 'senior']:
                    normalized.append('sr')
                elif s in ['jr', 'junior']:
                    normalized.append('jr')
                else:
                    normalized.append(s)
            return set(normalized)
        
        norm_suffix1 = normalize_suffixes(suffix1)
        norm_suffix2 = normalize_suffixes(suffix2)
        
        if norm_suffix1 != norm_suffix2:
            return False
    
    # Check first name + middle name compatibility
    # At minimum, first names must match
    if first_middle1[0] != first_middle2[0]:
        return False
    
    # If both have middle names/initials, they should be compatible
    if len(first_middle1) > 1 and len(first_middle2) > 1:
        # Both have middle names - check if they match or are compatible
        middle1 = first_middle1[1:]
        middle2 = first_middle2[1:]
        
        # Check if middle names/initials are compatible
        for m1, m2 in zip(middle1, middle2):
            # Remove periods for comparison
            clean_m1 = m1.replace('.', '')
            clean_m2 = m2.replace('.', '')
            
            # If one is an initial and other is full name, check if they match
            if len(clean_m1) == 1 and len(clean_m2) > 1:
                if clean_m1 != clean_m2[0]:
                    return False
            elif len(clean_m2) == 1 and len(clean_m1) > 1:
                if clean_m2 != clean_m1[0]:
                    return False
            elif clean_m1 != clean_m2:
                return False
    
    # If we get here, names are compatible
    return True

# Base directory for output files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Bar numbers to search for
BAR_NUMBERS = [
    "24032600",
    "24053705", 
    "24031632"
]

# SPA Lawyer mapping
SPA_LAWYERS = {
    "24031632": "Stacy Soule",
    "24053705": "John Messinger", 
    "24032600": "Emily Johnson-Liu"
}

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
        seen_cases = set()  # Track all cases we've seen
        prev_page_cases = set()  # Track cases from previous page to detect when pagination stops working
        
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
            
            # Check if the page content is the same as the previous page (pagination not working)
            current_page_cases = set(page_cases)
            if page_num > 1 and current_page_cases == prev_page_cases:
                print("🔄 Page content hasn't changed - pagination complete")
                break
            
            # Add only new cases to avoid duplicates
            new_cases_found = 0
            for case in page_cases:
                if case not in seen_cases:
                    seen_cases.add(case)
                    case_numbers.append(case)
                    new_cases_found += 1
            
            print(f"✅ Found {len(page_cases)} cases on page {page_num} ({new_cases_found} new)")
            
            # Update previous page cases for next comparison
            prev_page_cases = current_page_cases
            
            # If no new cases were found, we've likely reached the end
            if new_cases_found == 0:
                print("🔄 No new cases found on this page - pagination complete")
                break
            
            # Check for next page button using the exact selector that works
            next_buttons = driver.find_elements(By.CSS_SELECTOR, "input.rgPageNext[title='Next Page']")
            if not next_buttons or not next_buttons[0].is_enabled():
                print(f"🏁 No more pages - next button not found or disabled")
                break
            
            # Click next page
            print(f"➡️ Moving to page {page_num + 1}")
            try:
                driver.execute_script("arguments[0].click();", next_buttons[0])
            except Exception as e:
                print(f"❌ Error clicking next page: {str(e)}")
                break
            
            page_num += 1
            
            # Wait for new page to load
            try:
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_grdCases_ctl00"))
                )
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

def is_case_closed_mandate_issued(soup):
    """Check if case should be filtered out due to mandate being issued (top event)"""
    events_table = soup.find('table', {'id': 'ctl00_ContentPlaceHolder1_grdEvents_ctl00'})
    if events_table:
        # Find the first data row (skip header)
        for row in events_table.find_all('tr'):
            if row.find('th'):  # Skip header row
                continue
            cells = row.find_all('td')
            if len(cells) >= 2:
                event_type = cells[1].get_text(strip=True).lower()
                # Check for various mandate issued patterns
                if 'mandate issued' in event_type or 'mandate issd' in event_type:
                    return True
                break  # Only check the first event (most recent)
    return False

def download_brief_with_driver(driver, url, case_number, event_type, index, output_folder):
    """Download a brief document using the same browser session and save with formatted filename"""
    try:
        # Clean up event_type by removing ' FILED'
        clean_event_type = event_type.replace(' FILED', '').replace(' filed', '')
        
        # Create filename: {case_number} {event_type} {index}
        # Replace invalid filename characters
        safe_case_number = re.sub(r'[<>:"/\\|?*]', '_', case_number)
        safe_event_type = re.sub(r'[<>:"/\\|?*]', '_', clean_event_type)
        filename = f"{safe_case_number} {safe_event_type} {index}.pdf"
        
        # Create briefs subdirectory
        briefs_folder = os.path.join(output_folder, "briefs")
        os.makedirs(briefs_folder, exist_ok=True)
        
        filepath = os.path.join(briefs_folder, filename)
        
        # Get current page URL to use as referer
        current_page_url = driver.current_url
        
        # Get cookies and session info from the current browser session
        cookies = driver.get_cookies()
        user_agent = driver.execute_script("return navigator.userAgent;")
        
        # Create requests session with proper headers
        session = requests.Session()
        session.headers.update({
            'User-Agent': user_agent,
            'Referer': current_page_url,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
        })
        
        # Add all cookies from the browser session
        for cookie in cookies:
            session.cookies.set(
                cookie['name'], 
                cookie['value'], 
                domain=cookie.get('domain', ''),
                path=cookie.get('path', '/'),
                secure=cookie.get('secure', False),
                rest={'HttpOnly': cookie.get('httpOnly', False)}
            )
        
        # Make the request to download the PDF
        print(f"🔄 Downloading: {filename}")
        response = session.get(url, stream=True, timeout=30)
        response.raise_for_status()
        
        # Check content type
        content_type = response.headers.get('content-type', '').lower()
        content_length = response.headers.get('content-length', '0')
        
        if 'pdf' in content_type:
            print(f"✅ PDF confirmed (Content-Type: {content_type}, Size: {content_length} bytes)")
        elif len(response.content) > 1000 and response.content.startswith(b'%PDF'):
            print(f"✅ PDF detected by content signature (Size: {len(response.content)} bytes)")
        else:
            print(f"⚠️  Warning: May not be a PDF (Content-Type: {content_type}, Size: {content_length} bytes)")
            # Still save it - might be a valid PDF with wrong content-type
        
        # Save the file
        with open(filepath, 'wb') as f:
            if response.headers.get('content-length'):
                # Stream download for large files
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            else:
                # Write all content at once for smaller files
                f.write(response.content)
        
        file_size = os.path.getsize(filepath)
        print(f"✅ Downloaded: {filename} ({file_size} bytes)")
        
        return filepath
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error downloading {filename}: {str(e)}")
        return None
    except Exception as e:
        print(f"❌ Error downloading brief {filename}: {str(e)}")
        return None

def extract_case_details(driver, soup, case_number, output_folder=None, all_case_numbers=None):
    """Extract case details including parties, attorney information, and calendar events"""
    case_info = {
        'case_number': case_number,
        'parties': [],
        'attorneys': [],
        'documents': [],
        'calendar_events': [],
        'briefs_downloaded': []
    }
    
    # Don't filter for mandate here - do it later after concurrent PD case analysis
    case_info['filtered_out'] = False
    case_info['mandate_issued'] = is_case_closed_mandate_issued(soup)
    
    # Check if this is a COA case (starts with 2 digits)
    is_coa_case = bool(re.match(r'^\d{2}-', case_number))
    case_info['is_coa_case'] = is_coa_case
    
    # Extract party and attorney information from the party table
    try:
        # Look for the party table (contains both parties and their attorneys)
        parties_table = soup.find('table', {'id': 'ctl00_ContentPlaceHolder1_grdParty_ctl00'})
        if parties_table:
            for row in parties_table.find_all('tr'):
                if row.find('th'):  # Skip header row
                    continue
                cells = row.find_all('td')
                if len(cells) >= 3:
                    party_name = cells[0].get_text(strip=True)
                    party_type = cells[1].get_text(strip=True)
                    # Handle multiple representatives separated by <br> tags
                    rep_cell = cells[2]
                    rep_html = str(rep_cell)
                    # Split by <br> tags and clean up
                    rep_parts = rep_html.replace('<br>', '|SPLIT|').replace('<br/>', '|SPLIT|').replace('<br />', '|SPLIT|')
                    rep_text = BeautifulSoup(rep_parts, 'html.parser').get_text(strip=True)
                    rep_names = [name.strip() for name in rep_text.split('|SPLIT|') if name.strip()]
                    representative = ' | '.join(rep_names) if len(rep_names) > 1 else rep_names[0] if rep_names else ""
                    
                    if party_name:  # Only add if we have a party name
                        # Determine if this is a state party
                        is_state_party = (
                            party_type == 'Criminal - State of Texas' or 
                            'State of Texas' in party_name or
                            party_name.lower().startswith('state of texas')
                        )
                        
                        party_info = {
                            'name': party_name,
                            'type': party_type,
                            'representative': representative,
                            'is_state_party': is_state_party
                        }
                        case_info['parties'].append(party_info)
                        
                        # Extract attorney information from the representative field
                        if representative:
                            # Split by | separator (already cleaned up above)
                            attorney_names = representative.split(' | ')
                            for attorney_name in attorney_names:
                                attorney_name = attorney_name.strip()
                                if attorney_name and attorney_name not in [a['name'] for a in case_info['attorneys']]:
                                    # Try to extract bar number if present
                                    bar_number = ""
                                    for bar_num in BAR_NUMBERS:
                                        if bar_num in attorney_name:
                                            bar_number = bar_num
                                            break
                                    
                                    attorney_info = {
                                        'name': attorney_name,
                                        'bar_number': bar_number,
                                        'representing': party_name
                                    }
                                    case_info['attorneys'].append(attorney_info)
    except Exception as e:
        print(f"Error extracting parties for {case_number}: {str(e)}")
    
    # Extract document links
    case_info['documents'] = extract_document_links(soup, case_number)
    
    # Extract calendar events
    case_info['calendar_events'] = extract_calendar_events(soup, case_number)
    
    return case_info

def download_briefs_for_case(driver, soup, case_number, output_folder):
    """Download all briefs for a case with proper naming (excluding notices)"""
    downloaded_briefs = []
    
    # Process briefs table
    briefs_table = soup.find('table', {'id': 'ctl00_ContentPlaceHolder1_grdBriefs_ctl00'})
    if briefs_table:
        # Collect all brief events with dates to sort by oldest first
        brief_events = []
        
        for row in briefs_table.find_all('tr'):
            if row.find('th'):  # Skip header row
                continue
                
            cells = row.find_all('td')
            if len(cells) >= 2:
                event_date = cells[0].get_text(strip=True)
                event_type = cells[1].get_text(strip=True)
                
                # Find document links in this row
                doc_tables = row.find_all('table', {'class': 'docGrid'})
                for doc_table in doc_tables:
                    for doc_row in doc_table.find_all('tr'):
                        doc_cells = doc_row.find_all('td')
                        if len(doc_cells) >= 2:  # Need both link and description cells
                            link_cell = doc_cells[0]
                            desc_cell = doc_cells[1]
                            
                            link = link_cell.find('a', href=True)
                            if link and 'SearchMedia.aspx' in link['href']:
                                doc_description = desc_cell.get_text(strip=True)
                                doc_description_lower = doc_description.lower()
                                
                                # Include various brief types but exclude notices
                                is_brief = any(brief_type in doc_description_lower for brief_type in [
                                    'brief', 'reply brief', 'appellant brief', 'appellee brief', 
                                    'state brief', 'petitioner brief', 'respondent brief',
                                    'opening brief', 'closing brief', 'supplemental brief',
                                    'amicus brief', 'amicus curiae brief', 'sur-reply brief',
                                    'appellant\'s brief', 'appellee\'s brief', 'state\'s brief',
                                    'petitioner\'s brief', 'respondent\'s brief', 'reply'
                                ])
                                
                                is_notice = 'notice' in doc_description_lower
                                
                                if is_brief and not is_notice:
                                    brief_events.append({
                                        'date': event_date,
                                        'event_type': event_type,
                                        'url': f"https://search.txcourts.gov/{link['href']}",
                                        'description': doc_description
                                    })
                                    print(f"📄 Found brief: {doc_description} for {case_number}")
                                else:
                                    print(f"⏭️  Skipping non-brief: {doc_description} for {case_number}")
        
        # Sort by date (oldest first) and assign indices
        try:
            brief_events.sort(key=lambda x: datetime.strptime(x['date'], '%m/%d/%Y'))
        except:
            # If date parsing fails, keep original order
            pass
        
        # Download each brief with proper index
        for index, brief in enumerate(brief_events, 1):
            filepath = download_brief_with_driver(
                driver,
                brief['url'], 
                case_number, 
                brief['event_type'], 
                index, 
                output_folder
            )
            if filepath:
                downloaded_briefs.append({
                    'index': index,
                    'event_type': brief['event_type'],
                    'date': brief['date'],
                    'filepath': filepath,
                    'url': brief['url'],
                    'description': brief['description']
                })
    
    return downloaded_briefs

def extract_calendar_events(soup, case_number):
    """Extract calendar events from a case page"""
    calendar_events = []
    
    # Look for calendar table
    calendar_table = soup.find('table', {'id': 'ctl00_ContentPlaceHolder1_grdCalendar_ctl00'})
    if calendar_table:
        for row in calendar_table.find_all('tr'):
            if row.find('th'):  # Skip header row
                continue
                
            cells = row.find_all('td')
            if len(cells) >= 3:  # Calendar table has 3 columns: Set Date, Calendar Type, Reason Set
                set_date = cells[0].get_text(strip=True)
                calendar_type = cells[1].get_text(strip=True)
                reason_set = cells[2].get_text(strip=True)
                
                calendar_events.append({
                    'case_number': case_number,
                    'set_date': set_date,
                    'calendar_type': calendar_type,
                    'reason_set': reason_set
                })
    
    return calendar_events

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

def generate_pdf_report(all_case_details, output_folder):
    """Generate PDF report of non-state parties in COA cases who don't have CCA cases pending"""
    
    # Separate COA cases (case numbers start with digits) and CCA cases (start with PD)
    coa_cases = []
    cca_cases = []
    
    for case in all_case_details:
        case_number = case['case_number']
        if case_number.startswith('PD-'):
            cca_cases.append(case)
        elif case_number[0:2].isdigit():  # COA cases start with two digits
            coa_cases.append(case)
    
    # Get all parties who have CCA cases pending
    parties_with_cca_cases = set()
    for case in cca_cases:
        for party in case['parties']:
            if party['type'] != 'Criminal - State of Texas' and 'State of Texas' not in party['name']:
                parties_with_cca_cases.add(party['name'].upper().strip())
    
    # Find non-state parties in COA cases who don't have CCA cases
    coa_only_parties = []
    for case in coa_cases:
        for party in case['parties']:
            if (party['type'] != 'Criminal - State of Texas' and 
                'State of Texas' not in party['name'] and
                party['name'].upper().strip() not in parties_with_cca_cases):
                
                coa_only_parties.append({
                    'party_name': party['name'],
                    'party_type': party['type'],
                    'case_number': case['case_number'],
                    'representative': party['representative']
                })
    
    # Generate PDF report
    pdf_file = os.path.join(output_folder, "coa_only_parties_report.pdf")
    doc = SimpleDocTemplate(pdf_file, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=16,
        spaceAfter=30,
    )
    story.append(Paragraph("Non-State Parties in Court of Appeals Cases", title_style))
    story.append(Paragraph("(Who do not have pending Court of Criminal Appeals cases)", styles['Normal']))
    story.append(Spacer(1, 20))
    
    # Summary
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
    story.append(Paragraph(f"Total COA cases analyzed: {len(coa_cases)}", styles['Normal']))
    story.append(Paragraph(f"Total CCA cases analyzed: {len(cca_cases)}", styles['Normal']))
    story.append(Paragraph(f"Non-state parties in COA only: {len(coa_only_parties)}", styles['Normal']))
    story.append(Spacer(1, 20))
    
    if coa_only_parties:
        # Create table data
        table_data = [['Party Name', 'Party Type', 'Case Number', 'Representative']]
        
        for party in coa_only_parties:
            # Create clickable link to case page
            case_url = f"https://search.txcourts.gov/Case.aspx?cn={party['case_number']}"
            case_link = f'<a href="{case_url}" color="blue">{party["case_number"]}</a>'
            
            table_data.append([
                party['party_name'],
                party['party_type'],
                Paragraph(case_link, styles['Normal']),
                party['representative']
            ])
        
        # Create table
        table = Table(table_data, colWidths=[2*inch, 1.5*inch, 1.2*inch, 2*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        
        story.append(table)
    else:
        story.append(Paragraph("No parties found matching the criteria.", styles['Normal']))
    
    # Build PDF
    doc.build(story)
    print(f"✅ Generated PDF report: {pdf_file}")
    return pdf_file

def analyze_briefs_with_claude(brief_paths_and_descriptions, case_number):
    """Analyze multiple legal brief PDFs with Claude to extract legal issues"""
    try:
        # Get API key from environment variable
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            print("❌ ANTHROPIC_API_KEY not found in .env file")
            return []
        
        client = anthropic.Anthropic(api_key=api_key)
        
        # Prepare content array with all briefs
        content = []
        brief_descriptions = []
        
        # Read all PDF files and add them to content
        import base64
        for brief_path, brief_description in brief_paths_and_descriptions:
            try:
                with open(brief_path, 'rb') as f:
                    pdf_content = base64.b64encode(f.read()).decode('utf-8')
                
                content.append({
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_content
                    }
                })
                brief_descriptions.append(brief_description)
            except Exception as e:
                print(f"    ⚠️  Error reading {brief_path}: {e}")
                continue
        
        if not content:
            print(f"    ⚠️  No valid briefs to analyze for {case_number}")
            return []
        
        # Create the analysis prompt
        brief_list = "\n".join([f"- {desc}" for desc in brief_descriptions])
        
        content.append({
            "type": "text",
            "text": f"""You are a legal expert analyzing criminal appellate briefs from Texas courts. Please analyze ALL the briefs provided for case {case_number} and identify the distinct legal issues raised across all briefs.

The briefs included are:
{brief_list}

For each legal issue, provide:
1. A concise description of the issue (1-2 sentences)
2. The specific legal area (e.g., "Fourth Amendment Search and Seizure", "Ineffective Assistance of Counsel", "Sufficiency of Evidence", etc.)
3. Which brief(s) raised this issue

Focus on substantive legal arguments, not procedural matters. Consolidate similar issues from different briefs. Return your analysis in JSON format with an array of issues:

{{
  "issues": [
    {{
      "description": "Brief description of the legal issue",
      "legal_area": "Specific area of law",
      "source_briefs": ["brief description 1", "brief description 2"]
    }}
  ]
}}"""
        })
        
        # Create message with all PDF attachments
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4000,
            messages=[
                {
                    "role": "user",
                    "content": content
                }
            ]
        )
        
        response_text = message.content[0].text
        
        # Try to parse JSON response
        try:
            import json
            import re
            
            # First try to find JSON in markdown code blocks
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                if json_end != -1:
                    response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.rfind("```")
                if json_end != -1:
                    response_text = response_text[json_start:json_end].strip()
            
            # If no markdown blocks, try to extract JSON using regex
            if not response_text.strip().startswith('{'):
                json_match = re.search(r'\{.*?\}', response_text, re.DOTALL)
                if json_match:
                    response_text = json_match.group(0)
            
            # Clean up the JSON text
            response_text = response_text.strip()
            
            # Try parsing the JSON
            result = json.loads(response_text)
            return result.get('issues', [])
            
        except json.JSONDecodeError as e:
            print(f"    ⚠️  Error parsing Claude response for {case_number}: {str(e)}")
            print(f"    Response was: {response_text[:500]}...")
            
            # Try a more aggressive approach - look for the issues array specifically
            try:
                issues_match = re.search(r'"issues"\s*:\s*\[(.*?)\]', response_text, re.DOTALL)
                if issues_match:
                    issues_json = '{"issues":[' + issues_match.group(1) + ']}'
                    result = json.loads(issues_json)
                    return result.get('issues', [])
            except:
                pass
            
            return []
            
    except Exception as e:
        error_msg = str(e)
        print(f"    ⚠️  Error analyzing briefs with Claude for {case_number}: {error_msg}")
        
        # Check if it's a size limit error (various error messages)
        size_limit_keywords = ["too large", "limit", "size", "100 pdf pages", "maximum", "exceeded"]
        if any(keyword in error_msg.lower() for keyword in size_limit_keywords):
            print(f"    🔄 Input too large, falling back to smaller groups...")
            return None  # Signal to fallback to smaller processing
        
        return []

def analyze_brief_with_claude(brief_path, case_number, brief_description):
    """Analyze a single legal brief PDF with Claude to extract legal issues"""
    try:
        # Get API key from environment variable
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            print("❌ ANTHROPIC_API_KEY not found in .env file")
            return []
        
        client = anthropic.Anthropic(api_key=api_key)
        
        # Read the PDF file as binary and encode as base64
        import base64
        with open(brief_path, 'rb') as f:
            pdf_content = base64.b64encode(f.read()).decode('utf-8')
        
        # Create message with PDF attachment
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_content
                            }
                        },
                        {
                            "type": "text",
                            "text": f"""You are a legal expert analyzing a criminal appellate brief from Texas courts. Please analyze this brief from case {case_number} ({brief_description}) and identify the distinct legal issues raised.

For each legal issue, provide:
1. A concise description of the issue (1-2 sentences)
2. The specific legal area (e.g., "Fourth Amendment Search and Seizure", "Ineffective Assistance of Counsel", "Sufficiency of Evidence", etc.)

Focus on substantive legal arguments, not procedural matters. Return your analysis in JSON format with an array of issues:

{{
  "issues": [
    {{
      "description": "Brief description of the legal issue",
      "legal_area": "Specific area of law"
    }}
  ]
}}"""
                        }
                    ]
                }
            ]
        )
        
        response_text = message.content[0].text
        
        # Try to parse JSON response
        try:
            import json
            import re
            
            # First try to find JSON in markdown code blocks
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                if json_end != -1:
                    response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.rfind("```")
                if json_end != -1:
                    response_text = response_text[json_start:json_end].strip()
            
            # If no markdown blocks, try to extract JSON using regex
            if not response_text.strip().startswith('{'):
                json_match = re.search(r'\{.*?\}', response_text, re.DOTALL)
                if json_match:
                    response_text = json_match.group(0)
            
            # Clean up the JSON text
            response_text = response_text.strip()
            
            # Try parsing the JSON
            result = json.loads(response_text)
            return result.get('issues', [])
            
        except json.JSONDecodeError as e:
            print(f"    ⚠️  Error parsing Claude response for {case_number}: {str(e)}")
            print(f"    Response was: {response_text[:500]}...")
            
            # Try a more aggressive approach - look for the issues array specifically
            try:
                issues_match = re.search(r'"issues"\s*:\s*\[(.*?)\]', response_text, re.DOTALL)
                if issues_match:
                    issues_json = '{"issues":[' + issues_match.group(1) + ']}'
                    result = json.loads(issues_json)
                    return result.get('issues', [])
            except:
                pass
            
            return []
            
    except Exception as e:
        print(f"    ⚠️  Error analyzing brief with Claude for {case_number}: {str(e)}")
        return []

def analyze_case_briefs(case_details, output_folder):
    """Analyze all briefs for a case and extract legal issues"""
    case_number = case_details['case_number']
    briefs_downloaded = case_details.get('briefs_downloaded', [])
    
    if not briefs_downloaded:
        print(f"⏭️  No briefs to analyze for {case_number}")
        case_details['legal_issues'] = []
        return
    
    print(f"🔍 Analyzing {len(briefs_downloaded)} briefs for {case_number}")
    
    # Prepare list of valid briefs for analysis
    valid_briefs = []
    for brief in briefs_downloaded:
        # Handle both 'filepath' and 'file_path' keys for compatibility
        brief_path = brief.get('filepath') or brief.get('file_path')
        brief_description = brief['description']
        
        if not brief_path:
            print(f"    ⚠️  No file path found in brief data: {brief}")
            continue
        
        # Check if file exists
        if not os.path.exists(brief_path):
            print(f"    ⚠️  File not found: {brief_path}")
            continue
        
        valid_briefs.append((brief_path, brief_description))
    
    if not valid_briefs:
        print(f"    ⚠️  No valid briefs found for {case_number}")
        case_details['legal_issues'] = []
        return
    
    all_issues = []
    
    # Try to analyze briefs with progressive fallback
    def try_analyze_briefs_progressively(briefs_list):
        """Try to analyze briefs with progressive fallback to smaller groups"""
        if len(briefs_list) == 1:
            # Single brief - analyze individually
            brief_path, brief_description = briefs_list[0]
            print(f"    📄 Analyzing single brief: {brief_description}")
            issues = analyze_brief_with_claude(brief_path, case_number, brief_description)
            
            if issues:
                print(f"      ✅ Found {len(issues)} legal issues")
                for issue in issues:
                    issue['source_brief'] = brief_description
                return issues
            else:
                print(f"      ⚠️  No legal issues identified")
                return []
        
        # Try analyzing all briefs together
        print(f"    📄 Analyzing {len(briefs_list)} briefs together...")
        issues = analyze_briefs_with_claude(briefs_list, case_number)
        
        if issues is None:
            # Size limit error - try smaller groups
            if len(briefs_list) == 2:
                print(f"    🔄 Two briefs too large, analyzing individually...")
                # Analyze each brief individually
                all_individual_issues = []
                for brief_path, brief_description in briefs_list:
                    print(f"      📄 Analyzing: {brief_description}")
                    individual_issues = analyze_brief_with_claude(brief_path, case_number, brief_description)
                    
                    if individual_issues:
                        print(f"        ✅ Found {len(individual_issues)} legal issues")
                        for issue in individual_issues:
                            issue['source_brief'] = brief_description
                            all_individual_issues.append(issue)
                    else:
                        print(f"        ⚠️  No legal issues identified")
                return all_individual_issues
            else:
                # More than 2 briefs - try splitting into smaller groups
                print(f"    🔄 {len(briefs_list)} briefs too large, trying smaller groups...")
                mid_point = len(briefs_list) // 2
                first_half = briefs_list[:mid_point]
                second_half = briefs_list[mid_point:]
                
                print(f"    🔄 Trying first group of {len(first_half)} briefs...")
                first_issues = try_analyze_briefs_progressively(first_half)
                
                print(f"    🔄 Trying second group of {len(second_half)} briefs...")
                second_issues = try_analyze_briefs_progressively(second_half)
                
                return first_issues + second_issues
        elif issues:
            print(f"      ✅ Found {len(issues)} legal issues from combined analysis")
            return issues
        else:
            print(f"      ⚠️  No legal issues identified from combined analysis")
            return []
    
    if len(valid_briefs) > 0:
        print(f"  📄 Starting analysis of {len(valid_briefs)} briefs...")
        all_issues = try_analyze_briefs_progressively(valid_briefs)
    else:
        all_issues = []
    
    # Remove duplicate issues (for fallback individual analysis)
    unique_issues = []
    seen_descriptions = set()
    
    for issue in all_issues:
        desc_key = issue['description'].lower().strip()
        if desc_key not in seen_descriptions:
            seen_descriptions.add(desc_key)
            unique_issues.append(issue)
    
    case_details['legal_issues'] = unique_issues
    print(f"  📊 Total unique legal issues for {case_number}: {len(unique_issues)}")

def generate_comprehensive_case_report(coa_cases_with_briefs, output_folder):
    """Generate a comprehensive PDF report of COA cases with legal issues"""
    
    # Sort cases by cause number
    sorted_cases = sorted(coa_cases_with_briefs, key=lambda x: x['case_number'])
    
    pdf_file = os.path.join(output_folder, "comprehensive_case_report.pdf")
    doc = SimpleDocTemplate(pdf_file, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    story = []
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=18,
        spaceAfter=30,
        alignment=1,  # Center
    )
    story.append(Paragraph("Court of Appeals Cases - Legal Issues Analysis", title_style))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
    story.append(Spacer(1, 20))
    
    # Summary
    total_cases = len(sorted_cases)
    cases_with_briefs = len([c for c in sorted_cases if c.get('briefs_downloaded')])
    total_issues = sum(len(c.get('legal_issues', [])) for c in sorted_cases)
    
    summary_style = ParagraphStyle(
        'Summary',
        parent=styles['Normal'],
        fontSize=12,
        spaceAfter=10,
    )
    
    story.append(Paragraph(f"<b>Summary:</b>", summary_style))
    story.append(Paragraph(f"• Total COA Cases: {total_cases}", summary_style))
    story.append(Paragraph(f"• Cases with Downloaded Briefs: {cases_with_briefs}", summary_style))
    story.append(Paragraph(f"• Total Legal Issues Identified: {total_issues}", summary_style))
    story.append(Spacer(1, 30))
    
    # Cases
    case_style = ParagraphStyle(
        'CaseHeader',
        parent=styles['Heading2'],
        fontSize=14,
        spaceAfter=10,
        textColor=colors.darkblue,
    )
    
    defendant_style = ParagraphStyle(
        'Defendant',
        parent=styles['Normal'],
        fontSize=11,
        spaceAfter=5,
        textColor=colors.darkgreen,
    )
    
    issue_style = ParagraphStyle(
        'Issue',
        parent=styles['Normal'],
        fontSize=10,
        leftIndent=20,
        spaceAfter=5,
    )
    
    for i, case in enumerate(sorted_cases, 1):
        case_number = case['case_number']
        
        # Case header with link
        case_url = f"https://search.txcourts.gov/Case.aspx?cn={case_number}"
        case_link = f'<a href="{case_url}" color="blue"><u>{case_number}</u></a>'
        story.append(Paragraph(f"{i}. Case: {case_link}", case_style))
        
        # Find defendant and defense counsel
        defendant_name = "Unknown"
        defense_counsel = "Unknown"
        
        for party in case.get('parties', []):
            if not party.get('is_state_party', False):
                defendant_name = party['name']
                if party.get('representative'):
                    defense_counsel = party['representative']
                break
        
        story.append(Paragraph(f"<b>Defendant:</b> {defendant_name}", defendant_style))
        story.append(Paragraph(f"<b>Defense Counsel:</b> {defense_counsel}", defendant_style))
        
        # SPA Lawyer information
        spa_lawyers = case.get('spa_lawyers', [])
        if spa_lawyers:
            spa_lawyer_text = ', '.join(spa_lawyers)
            story.append(Paragraph(f"<b>SPA Lawyer:</b> {spa_lawyer_text}", defendant_style))
        
        # Briefs status
        briefs_downloaded = case.get('briefs_downloaded', [])
        if briefs_downloaded:
            story.append(Paragraph(f"<b>Briefs Downloaded:</b> {len(briefs_downloaded)} briefs", defendant_style))
            
            # Legal issues
            legal_issues = case.get('legal_issues', [])
            if legal_issues:
                story.append(Paragraph(f"<b>Legal Issues Identified ({len(legal_issues)}):</b>", defendant_style))
                
                for j, issue in enumerate(legal_issues, 1):
                    issue_text = f"{j}. <b>{issue.get('legal_area', 'General')}:</b> {issue.get('description', 'No description')}"
                    
                    # Handle both single source_brief and multiple source_briefs
                    if issue.get('source_briefs'):
                        # Multiple briefs from combined analysis
                        source_text = ', '.join(issue['source_briefs'])
                        issue_text += f" <i>(Sources: {source_text})</i>"
                    elif issue.get('source_brief'):
                        # Single brief from individual analysis
                        issue_text += f" <i>(Source: {issue['source_brief']})</i>"
                    
                    story.append(Paragraph(issue_text, issue_style))
            else:
                story.append(Paragraph("<b>Legal Issues:</b> No issues identified by analysis", defendant_style))
        else:
            story.append(Paragraph("<b>Briefs:</b> No briefs found or downloaded", defendant_style))
        
        # Add spacing between cases
        story.append(Spacer(1, 20))
        
        # Add page break every 3 cases to avoid overcrowding
        if i % 3 == 0 and i < len(sorted_cases):
            story.append(Spacer(1, 50))
    
    # Build PDF
    doc.build(story)
    print(f"✅ Generated comprehensive case report: {pdf_file}")
    return pdf_file

def load_existing_case_data(output_folder):
    """Load existing case data from JSON files if they exist"""
    details_file = os.path.join(output_folder, "case_details.json")
    existing_cases = {}
    
    if os.path.exists(details_file):
        try:
            with open(details_file, 'r') as f:
                case_details_list = json.load(f)
                # Convert list to dict keyed by case number for easy lookup
                for case in case_details_list:
                    existing_cases[case['case_number']] = case
            print(f"📂 Loaded {len(existing_cases)} existing cases from {details_file}")
        except Exception as e:
            print(f"⚠️  Error loading existing case data: {e}")
    
    return existing_cases

def case_needs_processing(case_number, existing_cases):
    """Check if a case needs processing or if it's already complete"""
    if case_number not in existing_cases:
        return True, "New case"
    
    existing_case = existing_cases[case_number]
    
    # Check if case was filtered out
    if existing_case.get('filtered_out', False):
        return False, f"Already filtered: {existing_case.get('filter_reason', 'Unknown')}"
    
    # Check if briefs were already downloaded
    briefs_downloaded = existing_case.get('briefs_downloaded', [])
    if briefs_downloaded:
        # Check if legal issues were already analyzed
        legal_issues = existing_case.get('legal_issues', [])
        if legal_issues:
            return False, f"Complete: {len(briefs_downloaded)} briefs, {len(legal_issues)} issues"
        else:
            return True, f"Needs analysis: {len(briefs_downloaded)} briefs downloaded"
    
    return True, "Needs brief download"

def briefs_already_downloaded(case_number, output_folder):
    """Check if briefs for this case are already downloaded"""
    briefs_folder = os.path.join(output_folder, "briefs")
    if not os.path.exists(briefs_folder):
        return False, []
    
    # Look for files that start with the case number
    downloaded_briefs = []
    for filename in os.listdir(briefs_folder):
        if filename.startswith(case_number) and filename.endswith('.pdf'):
            downloaded_briefs.append(filename)
    
    return len(downloaded_briefs) > 0, downloaded_briefs

def scrape_attorney_cases(analysis_only=False):
    """Main function to scrape cases for specific attorney bar numbers"""
    print("🚀 Starting Texas Court of Appeals Case Scraper")
    if analysis_only:
        print("🔬 ANALYSIS-ONLY MODE: Skipping search and brief download")
    print("=" * 60)
    
    # Create data output folder (overwrite previous versions)
    output_folder = os.path.join(BASE_DIR, "data")
    os.makedirs(output_folder, exist_ok=True)
    
    # Load existing case data
    existing_cases = load_existing_case_data(output_folder)
    
    print(f"📁 Output folder: {output_folder}")
    if not analysis_only:
        print(f"🎯 Target bar numbers: {', '.join(BAR_NUMBERS)}")
        print("🏛️ Searching across all 17 Texas courts:")
        print("   • 15 Courts of Appeals (1st-15th)")
        print("   • Supreme Court of Texas (SCOTX)")
        print("   • Court of Criminal Appeals (CCA)")
        print("🚫 Excluding inactive cases")
    print("=" * 60)
    
    # Start browser
    if not analysis_only:
        print("🌐 Starting Chrome browser (headless mode)...")
        driver = setup_browser(headless=True)
        print("✅ Browser started successfully")
    else:
        driver = None
    
    all_cases = {}
    all_case_details = []
    
    try:
        if analysis_only:
            # ANALYSIS-ONLY MODE: Load existing cases and jump to Claude analysis
            print("\n" + "="*60)
            print("🔬 ANALYSIS-ONLY MODE: LOADING EXISTING CASES")
            print("="*60)
            
            if not existing_cases:
                print("❌ No existing cases found. Run without --analysis-only first to collect cases.")
                return
            
            # Load all existing cases
            all_case_details = list(existing_cases.values())
            print(f"📂 Loaded {len(all_case_details)} existing cases")
            
            # Jump directly to Claude analysis phase
            print("\n" + "="*60)
            print("🔬 CLAUDE ANALYSIS PHASE")
            print("="*60)
            
            # Run Claude analysis
            eligible_coa_cases = run_claude_analysis(all_case_details, output_folder, analysis_only=True)
            
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
            total_docs = sum(len(case['documents']) for case in all_case_details if not case.get('filtered_out', False))
            total_calendar_events = sum(len(case['calendar_events']) for case in all_case_details if not case.get('filtered_out', False))
            total_briefs = sum(len(case.get('briefs_downloaded', [])) for case in all_case_details)
            total_legal_issues = sum(len(case.get('legal_issues', [])) for case in all_case_details)
            filtered_cases = sum(1 for case in all_case_details if case.get('filtered_out', False))
            active_cases = len(all_case_details) - filtered_cases
            
            with open(report_file, 'w') as f:
                f.write(f"Attorney Case Search Report\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                
                f.write(f"Bar Numbers Searched: {', '.join(BAR_NUMBERS)}\n")
                f.write("Courts Searched: All 17 Texas courts (15 Courts of Appeals + Supreme Court + Court of Criminal Appeals)\n\n")
                
                f.write("Cases by Bar Number:\n")
                for bar_num, cases in all_cases.items():
                    f.write(f"  {bar_num}: {len(cases)} cases\n")
                
                f.write(f"\nTotal Unique Cases Found: {len(all_unique_cases)}\n")
                f.write(f"Active Cases (processed): {active_cases}\n")
                f.write(f"Filtered Cases (mandate issued): {filtered_cases}\n")
                f.write(f"COA Cases: {len(coa_cases)}\n")
                f.write(f"PD Cases: {len(pd_cases)}\n")
                f.write(f"Eligible COA Cases for Brief Download: {len(eligible_coa_cases)}\n")
                f.write(f"Total Documents Found: {total_docs}\n")
                f.write(f"Total Calendar Events Found: {total_calendar_events}\n")
                f.write(f"Total Briefs Downloaded: {total_briefs}\n")
                f.write(f"Total Legal Issues Identified: {total_legal_issues}\n")
            
            print(f"✅ Saved: summary_report.txt")
            
            # Generate PDF report
            print(f"\n📄 GENERATING PDF REPORT")
            print("=" * 40)
            generate_pdf_report(all_case_details, output_folder)
            print("=" * 40)
            
            print(f"\n🎉 SCRAPING COMPLETE!")
            print("=" * 60)
            print(f"📈 Results Summary:")
            print(f"   • {len(all_unique_cases)} unique cases found")
            print(f"   • {active_cases} active cases processed")
            print(f"   • {filtered_cases} cases filtered (mandate issued)")
            print(f"   • {len(coa_cases)} COA cases")
            print(f"   • {len(pd_cases)} PD cases")
            print(f"   • {len(eligible_coa_cases)} eligible COA cases for brief download")
            print(f"   • {total_docs} documents extracted")
            print(f"   • {total_calendar_events} calendar events extracted")
            print(f"   • {total_briefs} briefs downloaded")
            print(f"   • {total_legal_issues} legal issues identified")
            print(f"   • Results saved to: {output_folder}")
            print("=" * 60)
            
        else:
            # NORMAL MODE: Search, collect, and download briefs
            # PHASE 1: Search all courts for each bar number
            print("\n" + "="*60)
            print("📋 PHASE 1: COLLECTING CASE DATA")
            print("="*60)
            
            for i, bar_number in enumerate(BAR_NUMBERS, 1):
                print(f"\n{'='*20} BAR NUMBER {i}/{len(BAR_NUMBERS)} {'='*20}")
                print(f"🎯 Target: {bar_number}")
                
                try:
                    cases = search_by_attorney_bar_number(driver, bar_number)
                    all_cases[bar_number] = cases
                    print(f"✅ Search complete: Found {len(cases)} cases for {bar_number}")
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
            
            # Filter cases that need processing
            cases_to_process = []
            skipped_cases = []
            
            for case_number in all_unique_cases:
                needs_processing, reason = case_needs_processing(case_number, existing_cases)
                if needs_processing:
                    cases_to_process.append(case_number)
                else:
                    skipped_cases.append((case_number, reason))
            
            print(f"\n📊 PROCESSING ANALYSIS:")
            print(f"   • Cases to process: {len(cases_to_process)}")
            print(f"   • Cases to skip: {len(skipped_cases)}")
            
            # Debug: Show which cases are being skipped and why
            if skipped_cases:
                print(f"\n🔍 DEBUG - Cases being skipped:")
                for case_number, reason in skipped_cases:
                    print(f"   • {case_number}: {reason}")
            
            # Add existing cases to all_case_details
            for case_number, existing_case in existing_cases.items():
                if case_number in all_unique_cases:
                    # Set today's date for first_analyzed for all existing cases
                    existing_case['first_analyzed'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    all_case_details.append(existing_case)
            
            # Extract detailed information for cases that need processing
            if cases_to_process:
                print(f"\n🔍 Processing {len(cases_to_process)} cases that need updates...")
                progress_bar = tqdm(cases_to_process, desc="🔍 Processing cases", unit="case")
                
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
                        
                        # Parse page and extract details (WITHOUT downloading briefs)
                        soup = BeautifulSoup(driver.page_source, 'html.parser')
                        
                        case_details = extract_case_details(driver, soup, case_number, output_folder=None, all_case_numbers=all_unique_cases)
                        
                        # Add which bar numbers this case is associated with and SPA lawyer
                        case_details['associated_bar_numbers'] = []
                        case_details['spa_lawyers'] = []
                        for bar_num, cases in all_cases.items():
                            if case_number in cases:
                                case_details['associated_bar_numbers'].append(bar_num)
                                if bar_num in SPA_LAWYERS:
                                    case_details['spa_lawyers'].append(SPA_LAWYERS[bar_num])
                        
                        # Add first analyzed timestamp for new cases
                        case_details['first_analyzed'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        
                        all_case_details.append(case_details)
                        
                        # Update progress
                        doc_count = len(case_details['documents'])
                        progress_bar.set_postfix(docs=doc_count)
                        
                    except Exception as e:
                        progress_bar.write(f"Error processing {case_number}: {str(e)}")
                        continue
                
                progress_bar.close()
            else:
                print("📭 No cases need processing - all cases are up to date")
            
            # PHASE 2: Analyze cases and download briefs for eligible COA cases
            print("\n" + "="*60)
            print("📋 PHASE 2: ANALYZING CASES AND DOWNLOADING BRIEFS")
            print("="*60)
            
            # Separate COA and PD cases
            coa_cases = [case for case in all_case_details if case.get('is_coa_case', False)]
            pd_cases = [case for case in all_case_details if case['case_number'].startswith('PD-')]
            
            print(f"📊 Case breakdown:")
            print(f"   • COA cases: {len(coa_cases)}")
            print(f"   • PD cases: {len(pd_cases)}")
            print(f"   • Other cases: {len(all_case_details) - len(coa_cases) - len(pd_cases)}")
            
            # Get all non-state parties from PD cases
            pd_non_state_parties = []
            for case in pd_cases:
                if not case.get('filtered_out', False):  # Only active PD cases
                    for party in case.get('parties', []):
                        if not party.get('is_state_party', False):
                            pd_non_state_parties.append(party['name'])
            
            print(f"🔍 Found {len(pd_non_state_parties)} unique non-state parties in active PD cases")
            
            # Determine which COA cases should have briefs downloaded
            eligible_coa_cases = []
            for case in coa_cases:
                # Check for non-state parties first
                non_state_parties = [p for p in case.get('parties', []) if not p.get('is_state_party', False)]
                if not non_state_parties:
                    case['brief_download_reason'] = "No non-state parties found"
                    case['filtered_out'] = True
                    case['filter_reason'] = 'No non-state parties'
                    continue
                
                # Check if any non-state parties have concurrent PD cases (BEFORE mandate check)
                parties_with_pd_cases = []
                for party in non_state_parties:
                    coa_party_name = party['name']
                    # Check if this COA party matches any PD party
                    for pd_party_name in pd_non_state_parties:
                        if names_match(coa_party_name, pd_party_name):
                            parties_with_pd_cases.append(f"{coa_party_name} (matches PD: {pd_party_name})")
                            break  # Found a match, no need to check other PD parties
                
                if parties_with_pd_cases:
                    case['brief_download_reason'] = f"Parties have concurrent PD cases: {', '.join(parties_with_pd_cases)}"
                    case['filtered_out'] = True
                    case['filter_reason'] = 'Concurrent PD cases'
                    continue
                
                # Check if last calendar date was over a year ago
                calendar_events = case.get('calendar_events', [])
                if calendar_events:
                    # Find the most recent calendar date
                    most_recent_date = None
                    for event in calendar_events:
                        event_date_str = event.get('date', '').strip()
                        if event_date_str:
                            try:
                                # Parse date in MM/DD/YYYY format
                                event_date = datetime.strptime(event_date_str, '%m/%d/%Y')
                                if most_recent_date is None or event_date > most_recent_date:
                                    most_recent_date = event_date
                            except ValueError:
                                continue
                    
                    if most_recent_date:
                        one_year_ago = datetime.now() - timedelta(days=365)
                        if most_recent_date < one_year_ago:
                            case['brief_download_reason'] = f"Last calendar date was over a year ago ({most_recent_date.strftime('%m/%d/%Y')})"
                            case['filtered_out'] = True
                            case['filter_reason'] = 'Stale case (>1 year)'
                            continue
                
                # Check if mandate has been issued (after PD case check and date check)
                if case.get('mandate_issued', False):
                    case['brief_download_reason'] = "Mandate has been issued"
                    case['filtered_out'] = True
                    case['filter_reason'] = 'Mandate issued'
                    continue
                
                # This case is eligible for brief download
                case['brief_download_reason'] = f"Eligible: COA case with {len(non_state_parties)} non-state parties, no concurrent PD cases, mandate not issued, recent activity"
                eligible_coa_cases.append(case)
            
            print(f"\n📥 BRIEF DOWNLOAD ANALYSIS:")
            print(f"   • Eligible COA cases: {len(eligible_coa_cases)}")
            print(f"   • Filtered COA cases: {len(coa_cases) - len(eligible_coa_cases)}")
            
            # Download briefs for eligible cases
            if eligible_coa_cases:
                print(f"\n🔄 Downloading briefs for {len(eligible_coa_cases)} eligible COA cases...")
                brief_progress = tqdm(eligible_coa_cases, desc="📥 Downloading briefs", unit="case")
                
                for case in brief_progress:
                    case_number = case['case_number']
                    brief_progress.set_description(f"Downloading briefs for {case_number}")
                    
                    try:
                        # Check if briefs are already downloaded
                        already_downloaded, existing_briefs = briefs_already_downloaded(case_number, output_folder)
                        if already_downloaded:
                            brief_progress.write(f"📁 Briefs already downloaded for {case_number}: {len(existing_briefs)} files")
                            # Create brief info from existing files
                            case['briefs_downloaded'] = []
                            for brief_file in existing_briefs:
                                case['briefs_downloaded'].append({
                                    'filepath': os.path.join(output_folder, "briefs", brief_file),
                                    'description': brief_file.replace(case_number + "_", "").replace(".pdf", ""),
                                    'case_number': case_number
                                })
                            brief_progress.set_postfix(briefs=len(existing_briefs))
                            continue
                        
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
                        
                        # Parse page and download briefs
                        soup = BeautifulSoup(driver.page_source, 'html.parser')
                        print(f"📥 Downloading briefs for {case_number}: {case['brief_download_reason']}")
                        
                        # Check for Anders briefs BEFORE downloading
                        has_anders_brief = False
                        
                        # Check brief descriptions in the docGrid table
                        doc_grid = soup.find('table', {'id': 'ctl00_ContentPlaceHolder1_grdBriefs_ctl00'})
                        if doc_grid:
                            rows = doc_grid.find_all('tr')
                            for row in rows[1:]:  # Skip header row
                                cells = row.find_all('td')
                                if len(cells) >= 2:
                                    description = cells[1].get_text(strip=True).lower()
                                    if 'anders' in description:
                                        has_anders_brief = True
                                        break
                        
                        if has_anders_brief:
                            case['brief_download_reason'] = "Case contains Anders brief - filtered out"
                            case['filtered_out'] = True
                            case['filter_reason'] = 'Anders brief'
                            case['briefs_downloaded'] = []
                            brief_progress.set_postfix(briefs=0)
                            continue
                        
                        briefs_downloaded = download_briefs_for_case(driver, soup, case_number, output_folder)
                        case['briefs_downloaded'] = briefs_downloaded
                        
                        brief_progress.set_postfix(briefs=len(briefs_downloaded))
                        
                    except Exception as e:
                        brief_progress.write(f"Error downloading briefs for {case_number}: {str(e)}")
                        case['briefs_downloaded'] = []
                        continue
                
                brief_progress.close()
            
            # PHASE 3: Analyze briefs with Claude and generate comprehensive report
            print("\n" + "="*60)
            print("📋 PHASE 3: ANALYZING BRIEFS WITH CLAUDE")
            print("="*60)
            
            # Run Claude analysis
            eligible_coa_cases = run_claude_analysis(all_case_details, output_folder, analysis_only=False)
        
        # Save results (common to both modes)
        details_file = os.path.join(output_folder, "case_details.json")
        with open(details_file, 'w') as f:
            json.dump(all_case_details, f, indent=2)
        print(f"✅ Saved: case_details.json")
        
    except Exception as e:
        print(f"❌ Error during scraping: {str(e)}")
    finally:
        if driver:
            print("🌐 Closing browser...")
            driver.quit()
            print("✅ Browser closed")

def run_claude_analysis(all_case_details, output_folder, analysis_only=False):
    """Run Claude analysis on cases with briefs"""
    
    # Separate COA and PD cases for analysis-only mode
    if analysis_only:
        coa_cases = [case for case in all_case_details if case.get('is_coa_case', False)]
        eligible_coa_cases = [case for case in coa_cases if case.get('briefs_downloaded') and not case.get('filtered_out', False)]
    else:
        # In normal mode, eligible_coa_cases is already determined
        eligible_coa_cases = [case for case in all_case_details if case.get('briefs_downloaded') and not case.get('filtered_out', False)]
    
    print(f"🔍 Found {len(eligible_coa_cases)} cases with briefs for analysis")
    
    # Check if API key is available
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        print("⚠️  ANTHROPIC_API_KEY environment variable not set")
        print("⚠️  Skipping Claude analysis. Set the API key to enable brief analysis.")
        print("⚠️  Export ANTHROPIC_API_KEY=your_api_key_here")
        return eligible_coa_cases
    
    print(f"🤖 Analyzing briefs with Claude for {len(eligible_coa_cases)} cases...")
    
    analysis_progress = tqdm(eligible_coa_cases, desc="🤖 Analyzing with Claude", unit="case")
    
    for case in analysis_progress:
        case_number = case['case_number']
        analysis_progress.set_description(f"Analyzing {case_number}")
        
        try:
            # Check if legal issues are already analyzed
            existing_issues = case.get('legal_issues', [])
            if existing_issues:
                analysis_progress.write(f"🧠 Legal issues already analyzed for {case_number}: {len(existing_issues)} issues")
                analysis_progress.set_postfix(issues=len(existing_issues))
                continue
            
            analyze_case_briefs(case, output_folder)
            
            # Save updated case details to JSON immediately after analysis
            details_file = os.path.join(output_folder, "case_details.json")
            with open(details_file, 'w') as f:
                json.dump(all_case_details, f, indent=2)
            
            # Update progress with issue count
            issue_count = len(case.get('legal_issues', []))
            analysis_progress.set_postfix(issues=issue_count)
            
        except Exception as e:
            analysis_progress.write(f"Error analyzing briefs for {case_number}: {str(e)}")
            case['legal_issues'] = []
            continue
    
    analysis_progress.close()
    
    # Generate comprehensive case report
    print(f"\n📄 GENERATING COMPREHENSIVE CASE REPORT")
    print("=" * 40)
    generate_comprehensive_case_report(eligible_coa_cases, output_folder)
    print("=" * 40)
    
    return eligible_coa_cases

def main():
    """Main function with argument parsing"""
    parser = argparse.ArgumentParser(description='Texas Court of Appeals Case Scraper')
    parser.add_argument('--analysis-only', action='store_true', 
                       help='Run only Claude analysis on existing cases (skip search and brief download)')
    
    args = parser.parse_args()
    
    if args.analysis_only:
        scrape_attorney_cases(analysis_only=True)
    else:
        scrape_attorney_cases(analysis_only=False)

if __name__ == "__main__":
    main() 