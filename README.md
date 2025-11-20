# Smart Scraper - LLM-based Web Scraper

An intelligent web scraper that uses LLM (OpenAI) to extract structured data from HTML pages.

## Features

- Fetches HTML content from web pages using Selenium (handles JavaScript-rendered content)
- Uses OpenAI LLM to intelligently extract structured data
- Extracts: title, date, link (and optionally description/tags) from news/press articles
- Displays results in a structured format
- Saves results to JSON file
- Handles bot protection (Imperva/Incapsula/Cloudflare) with undetected-chromedriver

## Available Scrapers

This project includes scrapers for multiple newsroom pages:

1. **Ericsson News Scraper** (`ericsson_news_scraper.py`)
   - URL: https://www.ericsson.com/en/newsroom/latest-news
   - Extracts: title, date, link, description
   - Output: `ericsson_news.json`

2. **Nokia News Scraper** (`nokia_news_scraper.py`)
   - URL: https://www.nokia.com/newsroom/
   - Extracts: title, date, link
   - Output: `nokia_news.json`

3. **Amdocs Scraper** (`amdocs_news_scraper.py`)
   - URL: https://www.amdocs.com/news-press
   - Extracts: title, date, link, tags
   - Output: `amdocs_news.json`

4. **HPE News Scraper** (`hpe_news_scraper.py`)
   - URL: https://www.hpe.com/us/en/newsroom/press-hub.html
   - Extracts: title, date, link
   - Output: `hpe_news.json`

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

   Option 2: Pass API key as command line argument

## Usage

### Pipeline (Recommended)

The pipeline script runs all scrapers, combines results, and enhances articles with AI-generated tags and main ideas:

```bash
python pipeline.py
```

#### Using Multiple API Keys for Faster Processing

To accelerate article enhancement processing, you can use multiple OpenAI API keys. With 3-5 API keys, you can process articles in parallel, achieving 3-5x speedup.

**Option 1: Environment Variables (Recommended)**

Add multiple API keys to your `.env` file:

```env
OPENAI_API_KEY=sk-your-first-key-here
OPENAI_API_KEY_1=sk-your-first-key-here
OPENAI_API_KEY_2=sk-your-second-key-here
OPENAI_API_KEY_3=sk-your-third-key-here
```

Or use a comma-separated list:

```env
OPENAI_API_KEYS=sk-key1,sk-key2,sk-key3
```

**Option 2: Command Line**

```bash
python pipeline.py --api-keys "sk-key1,sk-key2,sk-key3"
```

**Benefits:**
- **3-5x faster processing** when using 3-5 API keys
- Parallel processing distributes requests across multiple keys
- Automatically handles rate limiting per key
- Backward compatible with single API key

**Example:**
```bash
# Single key (sequential processing)
python pipeline.py

# Multiple keys (parallel processing, 3-5x faster)
python pipeline.py --api-keys "sk-key1,sk-key2,sk-key3,sk-key4,sk-key5"
```

**Pipeline Options:**
- `--test`: Process only 3 articles per vendor (for testing)
- `--articles-per-vendor N`: Process N articles per vendor in test mode
- `--skip-scraping`: Skip scraping step (use existing JSON files)
- `--skip-combining`: Skip combining step (use existing unified JSON)
- `--skip-enhancement`: Skip enhancement step (only scrape and combine)

### Individual Scrapers

### HPE News Scraper
```bash
python scrapers/hpe_news_scraper.py
```

### Ericsson News Scraper
```bash
python scrapers/ericsson_news_scraper.py
```

### Nokia Scraper
```bash
python nokia_news_scraper.py
```

### Amdocs Scraper
```bash
python amdocs_news_scraper.py
```

For debugging (saves extracted HTML):
```bash
python scrapers/hpe_news_scraper.py --debug
```

### Security Check Handling

Some websites are protected by bot protection (Imperva/Incapsula/Cloudflare). The scrapers will:

1. **Automatically attempt to bypass** the security check using undetected-chromedriver
2. **If a security check page appears**, a browser window will open
3. **You may need to manually complete** the security check:
   - A browser window will open showing the security check page
   - Complete the checkbox/verification
   - Return to the terminal and press Enter when done
   - The scraper will continue automatically

The scraper will:
1. Open a Chrome browser window (may appear briefly)
2. Navigate to the target newsroom page
3. Wait for security checks to complete (or prompt you to complete manually)
4. Extract and clean the HTML structure
5. Use OpenAI LLM to analyze and extract structured data
6. Display results in the console
7. Save results to JSON file

## Output Format

Each article is extracted with the following structure:

**HPE/Nokia articles:**
- **title**: Article headline
- **date**: Publication date (YYYY-MM-DD format when possible)
- **link**: Full URL to the article

**Ericsson articles:**
- **title**: Article headline
- **date**: Publication date
- **link**: Full URL to the article
- **description**: Brief description or summary

**Amdocs articles:**
- **title**: Article headline
- **date**: Publication date
- **link**: Full URL to the article
- **tags**: List of relevant tags/categories

Example output (HPE):
```json
[
  {
    "title": "HPE and partners launch Quantum Scaling Alliance",
    "date": "2025-11-10",
    "link": "https://www.hpe.com/us/en/newsroom/press-release/2025/11/article.html"
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

