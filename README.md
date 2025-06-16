# SPA_Scrape

A Python project for scraping Texas Court of Appeals documents and case information.

## Features

- Scrapes case information from Texas Court of Appeals website
- Extracts document links with metadata
- Handles pagination automatically
- Outputs structured data in JSON format
- Supports both headless and interactive browser modes

## Setup

1. Clone the repository
2. Create and activate virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

Run the main scraper:
```bash
python COA_Scrape.py
```

The script will:
- Open the Texas Court of Appeals search page
- Wait for you to perform your search
- Extract all case numbers from results
- Process each case to extract document links
- Save results to timestamped output folder

## Output

The scraper creates a timestamped folder containing:
- `case_numbers.json` - List of all case numbers found
- `documents.json` - Detailed document information with metadata
- Individual case files as needed

## Requirements

- Python 3.7+
- Chrome browser
- ChromeDriver (automatically managed by Selenium)

## Dependencies

- selenium - Web browser automation
- beautifulsoup4 - HTML parsing
- tqdm - Progress bars
- requests - HTTP requests 