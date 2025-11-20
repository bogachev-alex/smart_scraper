# Complete List of Scrapers

This document provides a comprehensive list of all scrapers in the project with their details.

## Scrapers Overview

### 1. Amdocs Blog Scraper
- **File**: `scrapers/amdocs_blog_scraper.py`
- **URL**: https://www.amdocs.com/insights
- **Extracts**: title, date, link
- **Method**: Selenium (undetected-chromedriver) + BeautifulSoup
- **Requirements**: None
- **Output**: `data/amdocs_blog_articles.json`
- **Notes**: Uses Selenium to handle JavaScript-rendered content, clicks "Load more" button if available

### 2. Amdocs News Scraper
- **File**: `scrapers/amdocs_news_scraper.py`
- **URL**: https://www.amdocs.com/news-press
- **Extracts**: title, date, link, tags
- **Method**: LLM-based (OpenAI GPT-4o-mini) + BeautifulSoup + Selenium
- **Requirements**: OPENAI_API_KEY environment variable
- **Output**: `data/amdocs_news.json`
- **Notes**: Extracts only Press Release articles, uses LLM for extraction, handles Imperva/Incapsula protection

### 3. Amdocs Scraper (Insights)
- **File**: `scrapers/amdocs_scraper.py`
- **URL**: https://www.amdocs.com/insights
- **Extracts**: title, date, link
- **Method**: LLM-based (OpenAI GPT-4o-mini) + BeautifulSoup + Selenium
- **Requirements**: OPENAI_API_KEY environment variable
- **Output**: `data/amdocs_blog_articles.json`
- **Notes**: LLM-based extraction for insights blog page

### 4. Cisco Blog Scraper
- **File**: `scrapers/cisco_blog_scraper.py`
- **URL**: https://blogs.cisco.com/
- **Extracts**: title, date, link, description
- **Method**: Selenium (undetected-chromedriver) + BeautifulSoup
- **Requirements**: None
- **Output**: `data/cisco_blog_articles.json`
- **Notes**: Targets blog-card elements within cui section

### 5. Cisco Scraper (Press Releases)
- **File**: `scrapers/cisco_scraper.py`
- **URL**: https://newsroom.cisco.com/c/r/newsroom/en/us/press-releases.html
- **Extracts**: title, date, link, description
- **Method**: LLM-based (OpenAI GPT-4o-mini) + BeautifulSoup + Selenium
- **Requirements**: OPENAI_API_KEY environment variable
- **Output**: `data/cisco_articles.json`
- **Notes**: Targets cmp-articleitem elements, includes logging

### 6. Ericsson Blog Scraper
- **File**: `scrapers/ericsson_blog_scraper.py`
- **URL**: https://www.ericsson.com/en/blog?locs=68304
- **Extracts**: title, date, link
- **Method**: Selenium (undetected-chromedriver) + BeautifulSoup
- **Requirements**: None
- **Output**: `data/ericsson_blog_articles.json`
- **Notes**: Targets filtered-blogs > content-list > card structure

### 7. Ericsson News Scraper (Newsroom)
- **File**: `scrapers/ericsson_news_scraper.py`
- **URL**: https://www.ericsson.com/en/newsroom/latest-news?typeFilters=1,2,3,4&locs=68304
- **Extracts**: title, date, link, description
- **Method**: LLM-based (OpenAI GPT-4o-mini) + BeautifulSoup + Selenium
- **Requirements**: OPENAI_API_KEY environment variable
- **Output**: `data/ericsson_news.json`
- **Notes**: Multiple extraction strategies, targets news-list structure

### 8. HPE News Scraper
- **File**: `scrapers/hpe_news_scraper.py`
- **URL**: https://www.hpe.com/us/en/newsroom/press-hub.html
- **Extracts**: title, date, link
- **Method**: LLM-based (OpenAI GPT-4o-mini) + BeautifulSoup + Selenium
- **Requirements**: OPENAI_API_KEY environment variable
- **Output**: `data/hpe_news.json`
- **Notes**: Handles access denied errors, retries with non-headless mode

### 9. IBM News Scraper
- **File**: `scrapers/ibm_news_scraper.py`
- **URL**: https://newsroom.ibm.com/campaign
- **Extracts**: title, date, link, description
- **Method**: Selenium (undetected-chromedriver) + BeautifulSoup
- **Requirements**: None
- **Output**: `data/ibm_news.json` (also saves to CSV: `ibm_news.csv`)
- **Notes**: Targets wd_layout-simple wd_item_list structure

### 10. Nokia Blog Scraper
- **File**: `scrapers/nokia_blog_scraper.py`
- **URL**: https://www.nokia.com/blog/all-posts/
- **Extracts**: title, date, link
- **Method**: Selenium (undetected-chromedriver) + BeautifulSoup
- **Requirements**: None
- **Output**: `data/nokia_blog_articles.json`
- **Notes**: Supports pagination (--all-pages flag), targets blog-post-teaser elements

### 11. Nokia News Scraper (Newsroom)
- **File**: `scrapers/nokia_news_scraper.py`
- **URL**: https://www.nokia.com/newsroom/?h=1&t=press%20releases&match=1
- **Extracts**: title, date, link
- **Method**: LLM-based (OpenAI GPT-4o-mini) + BeautifulSoup + Selenium
- **Requirements**: OPENAI_API_KEY environment variable
- **Output**: `data/nokia_news.json`
- **Notes**: Targets td_headlines structure, handles access denied with retries

### 12. Oracle Blog Scraper
- **File**: `scrapers/oracle_blog_scraper.py`
- **URL**: https://blogs.oracle.com/
- **Extracts**: title, date, link
- **Method**: Selenium (undetected-chromedriver) + BeautifulSoup
- **Requirements**: None
- **Output**: `data/oracle_blog_articles.json`
- **Notes**: Targets blogtile elements within rc90 sections

### 13. Oracle News Scraper (News)
- **File**: `scrapers/oracle_news_scraper.py`
- **URL**: https://www.oracle.com/news/
- **Extracts**: title, date, link
- **Method**: LLM-based (OpenAI GPT-4o-mini) + BeautifulSoup + Selenium
- **Requirements**: OPENAI_API_KEY environment variable
- **Output**: `data/oracle_news.json`
- **Notes**: Targets rc92w3 (news item) elements

### 14. Salesforce News Scraper
- **File**: `scrapers/salesforce_news_scraper.py`
- **URL**: https://www.salesforce.com/news/news-explorer/
- **Extracts**: title, date, link
- **Method**: LLM-based (OpenAI GPT-4o-mini) + BeautifulSoup + Selenium
- **Requirements**: OPENAI_API_KEY environment variable
- **Output**: `data/salesforce_news.json`
- **Notes**: Targets content-card article elements

### 15. ServiceNow Blog Scraper
- **File**: `scrapers/servicenow_blog_scraper.py`
- **URL**: https://www.servicenow.com/blogs/category/product-news
- **Extracts**: title, date, link
- **Method**: Selenium (undetected-chromedriver) + BeautifulSoup
- **Requirements**: None
- **Output**: `data/servicenow_blog_articles.json`
- **Notes**: Only collects articles visible on initial page load (does not click "Load More")

### 16. ServiceNow News Scraper (Press Room)
- **File**: `scrapers/servicenow_news_scraper.py`
- **URL**: https://www.servicenow.com/company/media/press-room.html
- **Extracts**: title, date, link, tags
- **Method**: LLM-based (OpenAI GPT-4o-mini) + BeautifulSoup + Selenium
- **Requirements**: OPENAI_API_KEY environment variable
- **Output**: `data/servicenow_news.json`
- **Notes**: Targets press-card-component and press-release-tiles elements

## Summary Statistics

- **Total Scrapers**: 16
- **LLM-based Scrapers**: 9 (require OPENAI_API_KEY)
- **Selenium-only Scrapers**: 7 (no API key required)
- **Companies Covered**: 9 (Amdocs, Cisco, Ericsson, HPE, IBM, Nokia, Oracle, Salesforce, ServiceNow)

## Common Features

### All Scrapers Include:
- Error handling and retry logic
- Duplicate detection
- URL normalization (relative to absolute)
- Date parsing and normalization
- JSON output to `data/` folder
- Debug mode support (--debug or -d flag)

### LLM-based Scrapers:
- Use OpenAI GPT-4o-mini model
- Combine direct BeautifulSoup extraction with LLM analysis
- Support multiple API key sources (OPENAI_API_KEY, OPENAI_API_KEY_1-10, command line)
- Extract HTML structure before LLM analysis

### Selenium Scrapers:
- Use undetected-chromedriver to bypass bot detection
- Support headless and non-headless modes
- Handle JavaScript-rendered content
- Wait for content to load before extraction

## Running Scrapers

### Basic Usage:
```bash
# Selenium-only scraper
python scrapers/amdocs_blog_scraper.py

# LLM-based scraper (requires API key)
python scrapers/cisco_scraper.py

# With debug mode
python scrapers/nokia_news_scraper.py --debug
```

### API Key Setup:
LLM-based scrapers require an OpenAI API key. Set it via:
1. Environment variable: `OPENAI_API_KEY`
2. Numbered environment variables: `OPENAI_API_KEY_1`, `OPENAI_API_KEY_2`, etc.
3. Command line argument: `python scraper.py your_api_key`
4. `.env` file: `OPENAI_API_KEY=your_key_here`

## Output Format

All scrapers output JSON files with the following structure:
```json
[
  {
    "title": "Article Title",
    "date": "2025-11-19",
    "link": "https://example.com/article",
    "description": "Optional description",
    "tags": ["Optional", "tags"]
  }
]
```

## Notes

- All scrapers save output to the `data/` folder
- Debug HTML files are saved to the `debug/` folder when using --debug flag
- Some scrapers support pagination (e.g., Nokia Blog Scraper with --all-pages)
- Scrapers handle various bot protection mechanisms (Cloudflare, Imperva, Incapsula)
- Date formats are normalized when possible, but original formats are preserved if parsing fails

