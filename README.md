# SPA_Scrape

A Python project for searching Texas Court of Appeals cases by attorney bar numbers and extracting case information and documents.

## Features

- Searches for cases by specific attorney bar numbers across all Texas courts
- Excludes inactive cases (searches only active cases)
- Extracts detailed case information including parties and attorneys
- Extracts document links with metadata from both events and briefs tables
- Handles pagination automatically across multiple courts
- Outputs structured data in JSON format
- Generates comprehensive summary reports

## Target Bar Numbers

The script is currently configured to search for these bar numbers:
- 24032600
- 24053705
- 24031632

## Courts Searched

The script searches across all Texas Court of Appeals:
- 1st through 14th Courts of Appeals
- Texas Supreme Court

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
- Automatically search each court for cases where the specified bar numbers are counsel
- Filter to only active cases (excluding inactive cases)
- Extract case details including parties, attorneys, and documents
- Process all pages of results for each court
- Save comprehensive results to timestamped output folder

## Output

The scraper creates a timestamped folder containing:
- `cases_by_bar_number.json` - Cases organized by bar number
- `case_details.json` - Detailed information for all cases including documents
- `summary_report.txt` - Human-readable summary of results

## Output Structure

### cases_by_bar_number.json
```json
{
  "24032600": ["case1", "case2", ...],
  "24053705": ["case3", "case4", ...],
  "24031632": ["case5", "case6", ...]
}
```

### case_details.json
```json
[
  {
    "case_number": "01-23-00123-CV",
    "parties": ["Party information"],
    "attorneys": ["Attorney information"],
    "associated_bar_numbers": ["24032600"],
    "documents": [
      {
        "case_number": "01-23-00123-CV",
        "date": "2023-01-15",
        "event_type": "Brief Filed",
        "disposition": "",
        "description": "Appellant's Brief",
        "doc_type": "BRIEF",
        "media_id": "abc123",
        "url": "https://search.txcourts.gov/SearchMedia.aspx?...",
        "table_type": "briefs"
      }
    ]
  }
]
```

## Requirements

- Python 3.7+
- Chrome browser
- ChromeDriver (automatically managed by Selenium)

## Dependencies

- selenium - Web browser automation
- beautifulsoup4 - HTML parsing
- tqdm - Progress bars
- requests - HTTP requests

## Customization

To search for different bar numbers, modify the `BAR_NUMBERS` list in `COA_Scrape.py`:

```python
BAR_NUMBERS = [
    "your_bar_number_1",
    "your_bar_number_2",
    "your_bar_number_3"
]
``` 