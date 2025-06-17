# SPA_Scrape - Texas Court of Appeals Case Scraper

## Overview
This script searches Texas Court of Appeals for cases by attorney bar number and downloads relevant briefs for analysis. It focuses on COA cases (excluding PD cases) and uses Claude-4-Sonnet to analyze legal briefs and extract key legal issues.

## Features
- **Multi-Court Search**: Searches across all 17 Texas courts (14 Courts of Appeals + Supreme Court + Court of Criminal Appeals + 1 additional court)
- **Smart Brief Filtering**: Only downloads briefs for eligible COA cases where:
  - Case number begins with 2 digits (COA cases, not PD cases)
  - Defendant doesn't have simultaneous PD cases open
  - Court mandate has not been issued
  - Document is a brief (not a notice)
- **AI Analysis**: Uses Claude-4-Sonnet to analyze downloaded briefs and extract legal issues
- **Comprehensive Reporting**: Generates detailed PDF reports with case information and legal analysis

## Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Chrome WebDriver
Make sure you have Chrome installed and chromedriver in your PATH, or the script will attempt to download it automatically.

### 3. Set Up Claude API (Optional)
For AI analysis of briefs:
1. Copy `sample.env` to `.env`
2. Add your Anthropic API key to `.env`:
```
ANTHROPIC_API_KEY=your_actual_api_key_here
```

If no API key is provided, the script will skip AI analysis but still download briefs.

## Usage

### Basic Usage
```bash
python COA_Scrape.py
```

The script will search for cases using these default bar numbers:
- 24032600
- 24053705  
- 24031632

### Key Processing Phases

**Phase 1: Data Collection**
- Searches all courts for cases by bar number
- Extracts case details, parties, attorneys, documents
- Identifies active vs closed cases

**Phase 2: Brief Analysis & Filtering** 
- Analyzes relationships between COA and PD cases
- Downloads briefs only for eligible COA cases
- Filters out notices, downloads only briefs

**Phase 3: AI Analysis & Reporting**
- Sends PDF briefs directly to Claude-4-Sonnet for analysis
- Extracts legal issues and categorizes by area of law
- Generates comprehensive PDF report

## Output Files

### Directory Structure
```
data/
├── briefs/                    # Downloaded PDF briefs
│   ├── 01-24-00123-CR_brief_1.pdf
│   └── 02-24-00456-CR_brief_2.pdf
├── case_details.json         # Complete case data with analysis
└── comprehensive_case_report.pdf  # Professional summary report
```

### JSON Output
The `case_details.json` file contains:
- Complete case information for all found cases
- Brief download status and file paths
- Legal issues extracted by Claude (if API key provided)
- Detailed reasoning for brief download eligibility

### PDF Report
The comprehensive report includes:
- Case summaries with clickable court links
- Defendant names and defense counsel information  
- Legal issues organized by area of law
- Brief download statistics

## Legal Issue Categories
Claude analyzes briefs and categorizes issues such as:
- Fourth Amendment - Search and Seizure
- Sufficiency of Evidence
- Ineffective Assistance of Counsel
- Jury Selection and Voir Dire
- Sentencing and Punishment
- Miranda Rights and Confessions
- And many more...

## Error Handling
- Graceful handling of network timeouts and 403 errors
- Retry logic for failed downloads
- Comprehensive logging of all operations
- Continues processing even if individual cases fail

## Requirements
- Python 3.7+
- Chrome browser
- Internet connection
- Anthropic API key (optional, for AI analysis)

## Security Notes
- API keys are stored in `.env` file (not committed to git)
- All sensitive configuration excluded from version control
- Sample configuration provided in `sample.env` 