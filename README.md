# Smart Scraper - LLM-based Web Scraper

An intelligent web scraper that uses LLM (OpenAI) to extract structured data from HTML pages.

## Features

- Fetches HTML content from web pages using Selenium (handles JavaScript-rendered content)
- Uses OpenAI LLM to intelligently extract structured data
- Extracts: title, date, link, and tags from news/press articles
- Displays results in a structured format
- Saves results to JSON file
- Handles bot protection (Imperva/Incapsula) with undetected-chromedriver

## Installation

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. **Important**: Make sure you have Google Chrome installed (required for Selenium)

3. Set up your OpenAI API key:

   Option 1: Create a `.env` file (recommended):
   ```
   OPENAI_API_KEY=your_api_key_here
   ```

   Option 2: The API key is currently hardcoded in `scraper.py` (for quick testing)

## Usage

Run the scraper:
```bash
python scraper.py
```

For debugging (saves extracted HTML):
```bash
python scraper.py --debug
```

### Security Check Handling

The Amdocs website is protected by Imperva (bot protection). The scraper will:

1. **Automatically attempt to bypass** the security check using undetected-chromedriver
2. **If a security check page appears**, a browser window will open
3. **You may need to manually complete** the security check:
   - A browser window will open showing the security check page
   - Complete the checkbox/verification
   - Return to the terminal and press Enter when done
   - The scraper will continue automatically

The scraper will:
1. Open a Chrome browser window (may appear briefly)
2. Navigate to https://www.amdocs.com/news-press
3. Wait for security checks to complete (or prompt you to complete manually)
4. Extract and clean the HTML structure
5. Use OpenAI LLM to analyze and extract structured data
6. Display results in the console
7. Save results to `amdocs_articles.json`

## Output Format

Each article is extracted with the following structure:
- **title**: Article headline
- **date**: Publication date (YYYY-MM-DD format when possible)
- **link**: Full URL to the article
- **tags**: List of relevant tags/categories (e.g., "Press Release", "News", "Awards")

Example output:
```json
[
  {
    "title": "Amdocs Announces New Partnership",
    "date": "2024-01-15",
    "link": "https://www.amdocs.com/news/press-release/partnership",
    "tags": ["Press Release", "Partnership"]
  }
]
```

## Requirements

- Python 3.7+
- Google Chrome browser (latest version recommended)
- OpenAI API key
- Internet connection

## Troubleshooting

- **Security check keeps appearing**: Complete it manually in the browser window that opens
- **No articles found**: The page structure may have changed, or content is still loading. Try running with `--debug` to inspect the extracted HTML
- **Browser doesn't open**: Make sure Chrome is installed and up to date

