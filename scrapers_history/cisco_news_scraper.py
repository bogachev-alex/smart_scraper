"""
LLM-based scraper for extracting structured data from Cisco newsroom press releases page.
Extracts: title, date, link, description
Renamed from cisco_scraper.py to cisco_news_scraper.py
"""

import requests
from bs4 import BeautifulSoup
from openai import OpenAI
import json
import os
import sys
import time
import re
import logging
from datetime import datetime
from typing import List, Dict
from pathlib import Path
from contextlib import redirect_stderr
from io import StringIO
from dotenv import load_dotenv
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Load environment variables
load_dotenv()

# Setup logging
log_filename = f"cisco_news_scraper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# File handler - logs everything including DEBUG
file_handler = logging.FileHandler(log_filename, encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)

# Console handler - logs INFO and above (less verbose)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

# Add handlers
logger.addHandler(file_handler)
logger.addHandler(console_handler)


class CiscoNewsScraper:
    def __init__(self, api_key: str = None):
        """
        Initialize the scraper with OpenAI API key.
        
        Args:
            api_key: OpenAI API key. If not provided, will try to get from environment.
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key is required. Provide it as argument or set OPENAI_API_KEY environment variable.")
        
        self.client = OpenAI(api_key=self.api_key)
        self.url = "https://newsroom.cisco.com/c/r/newsroom/en/us/press-releases.html"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def fetch_html(self, use_selenium: bool = True) -> str:
        """
        Fetch HTML content from the Cisco press releases page.
        Uses Selenium to handle JavaScript-rendered content and bot protection.
        
        Args:
            use_selenium: If True, use Selenium (default). If False, use requests.
        
        Returns:
            HTML content as string
        """
        if use_selenium:
            return self._fetch_html_selenium()
        else:
            return self._fetch_html_requests()
    
    def _fetch_html_requests(self) -> str:
        """Fetch HTML using requests library."""
        try:
            response = requests.get(self.url, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            raise Exception(f"Failed to fetch HTML: {str(e)}")
    
    def _fetch_html_selenium(self) -> str:
        """Fetch HTML using undetected-chromedriver to bypass bot protection."""
        driver = None
        try:
            # Use undetected-chromedriver which is designed to bypass bot detection
            logger.info("Initializing browser (this may take a moment)...")
            options = uc.ChromeOptions()
            options.add_argument('--headless')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            
            driver = uc.Chrome(options=options, version_main=None)
            
            logger.info("Loading page...")
            driver.get(self.url)
            
            # Wait for content to load
            logger.info("Waiting for page content to load...")
            max_wait = 30
            waited = 0
            while waited < max_wait:
                page_source = driver.page_source
                
                # Check if we have actual content
                articles = driver.find_elements(By.CSS_SELECTOR, ".cmp-articleitem")
                links = driver.find_elements(By.CSS_SELECTOR, "a[href*='press-releases'], a[href*='/a/y']")
                main_content = driver.find_elements(By.CSS_SELECTOR, "section.cmp-articles")
                
                if len(articles) > 0 or len(links) > 5 or len(main_content) > 0 or len(page_source) > 20000:
                    logger.info("[OK] Content loaded successfully!")
                    break
                
                time.sleep(2)
                waited += 2
                if waited % 4 == 0:
                    logger.info(f"  Still waiting... ({waited}s)")
            
            # Additional wait for JavaScript to fully render
            time.sleep(3)
            
            html = driver.page_source
            logger.info(f"Retrieved HTML: {len(html)} characters")
            
            if len(html) < 10000:
                logger.warning(f"[WARNING] Retrieved HTML seems too short ({len(html)} chars). The page might still be loading.")
                logger.info("Trying to wait a bit longer...")
                time.sleep(5)
                html = driver.page_source
                logger.info(f"Retrieved HTML after additional wait: {len(html)} characters")
            
            # Try to find article links to verify we have content
            temp_soup = BeautifulSoup(html, 'html.parser')
            test_links = temp_soup.find_all('div', class_='cmp-articleitem')
            logger.debug(f"[DEBUG] Found {len(test_links)} article items in full HTML")
            
            return html
        except Exception as e:
            raise Exception(f"Failed to fetch HTML with Selenium: {str(e)}")
        finally:
            if driver:
                try:
                    logger.info("Closing browser...")
                    # Suppress stderr during cleanup to avoid harmless exception messages
                    with redirect_stderr(StringIO()):
                        driver.quit()
                        time.sleep(1)  # Give time for cleanup
                except Exception:
                    # Ignore cleanup errors - driver may already be closed
                    pass
    
    def extract_article_links(self, html: str) -> List[Dict]:
        """
        Extract article links using BeautifulSoup.
        Targets articles with class="cmp-articleitem" within section.cmp-articles.
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with basic article info (link, title, date, description)
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Find the main articles section
        articles_section = soup.find('section', class_='cmp-articles')
        if not articles_section:
            # Fallback: find all article items directly
            article_items = soup.find_all('div', class_='cmp-articleitem')
        else:
            # Find all article items within the section
            article_items = articles_section.find_all('div', class_='cmp-articleitem')
        
        logger.debug(f"[DEBUG] Found {len(article_items)} article items")
        
        # Process article elements
        for idx, article in enumerate(article_items):
            # Extract link
            link_url = None
            link_elem = article.find('a', {'data-link': 'page', 'data-id': 'link'})
            if link_elem and link_elem.get('href'):
                link_url = link_elem.get('href')
            else:
                # Try href attribute on the article div itself
                if article.get('href'):
                    link_url = article.get('href')
            
            if not link_url:
                continue
            
            # Make URL absolute
            if link_url.startswith('/'):
                full_url = f"https://newsroom.cisco.com{link_url}"
            elif link_url.startswith('http'):
                full_url = link_url
            else:
                continue
            
            # Avoid duplicates
            if full_url in seen_links:
                continue
            seen_links.add(full_url)
            
            # Extract title
            title = "N/A"
            title_elem = article.find('h1', {'data-elem': 'short_title'})
            if title_elem:
                title = title_elem.get_text(strip=True)
            
            # If no title found, try alternative methods
            if title == "N/A" or len(title) < 10:
                # Try to find any heading
                for heading in article.find_all(['h1', 'h2', 'h3', 'h4', 'h5']):
                    heading_text = heading.get_text(strip=True)
                    if heading_text and len(heading_text) > 10:
                        title = heading_text
                        break
            
            # Extract date
            date_text = "N/A"
            date_elem = article.find('div', {'data-elem': 'date'})
            if date_elem:
                date_text = date_elem.get_text(strip=True)
            
            # If no date found, try to find date patterns in article text
            if date_text == "N/A":
                article_text = article.get_text()
                date_patterns = [
                    r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}\b',
                    r'\b\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b',
                    r'\b\d{4}-\d{2}-\d{2}\b',
                ]
                for pattern in date_patterns:
                    match = re.search(pattern, article_text, re.IGNORECASE)
                    if match:
                        date_text = match.group(0)
                        break
            
            # Extract description
            description = "N/A"
            desc_elem = article.find('div', {'data-elem': 'description'})
            if desc_elem:
                description = desc_elem.get_text(strip=True)
            
            articles.append({
                'link': full_url,
                'title': title,
                'date': date_text,
                'description': description
            })
            
            logger.debug(f"[DEBUG] Extracted article {idx+1}: {title[:50]}...")
        
        return articles
    
    def extract_html_structure(self, html: str) -> str:
        """
        Extract relevant HTML structure for LLM analysis.
        Uses BeautifulSoup to clean and extract meaningful content.
        
        Args:
            html: Raw HTML content
            
        Returns:
            Cleaned HTML structure as string
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style", "noscript"]):
            script.decompose()
        
        # Find the main articles section
        articles_section = soup.find('section', class_='cmp-articles')
        
        if articles_section:
            # Extract all article items HTML
            article_items = articles_section.find_all('div', class_='cmp-articleitem')
            articles_html = [str(article) for article in article_items]
            content_str = '\n'.join(articles_html)
        else:
            # Fallback: look for article items directly
            article_items = soup.find_all('div', class_='cmp-articleitem')
            if article_items:
                articles_html = [str(article) for article in article_items]
                content_str = '\n'.join(articles_html)
            else:
                # Last resort: get body
                body = soup.find('body')
                content_str = str(body) if body else html
        
        # Limit content size to avoid token limits
        if len(content_str) > 150000:
            content_str = content_str[:150000] + "..."
        
        return content_str
    
    def analyze_with_llm(self, html_content: str) -> List[Dict]:
        """
        Use OpenAI LLM to extract structured data from HTML.
        
        Args:
            html_content: HTML content to analyze
            
        Returns:
            List of dictionaries with title, date, link, description
        """
        prompt = f"""You are analyzing HTML from Cisco newsroom press releases page (https://newsroom.cisco.com/c/r/newsroom/en/us/press-releases.html). Your task is to extract ALL press release articles from the page.

CRITICAL INSTRUCTIONS:
1. Extract ALL press release articles you can find on the page
2. Each article should be in a <div class="cmp-articleitem"> element within <section class="cmp-articles">
3. Each article should become a separate entry
4. Do NOT extract filter links, navigation links, or category links
5. Extract ALL articles you can find (typically 10-50+ on a listing page)

What to look for:
- Article items with class="cmp-articleitem" within section.cmp-articles
- Title in <h1 data-elem="short_title"> within the article item
- Date in <div data-elem="date"> within the article item
- Description in <div data-elem="description"> within the article item
- Link in the href attribute of <a data-link="page" data-id="link">, or in the href attribute of the article div itself
- Dates in formats like "Nov 12, 2025", "12 Nov 2025", "2025-11-12", etc.

For EACH article you find, extract:
- title: The headline or title from the h1[data-elem="short_title"] element (required)
- date: Publication date from div[data-elem="date"] element (format as YYYY-MM-DD if possible, otherwise keep original format, use "N/A" if not found)
- link: Full URL from href attribute (if relative, prepend https://newsroom.cisco.com. Use "N/A" only if absolutely no link exists)
- description: Description text from div[data-elem="description"] element (use "N/A" if not found)

EXAMPLES of what to extract:
- Articles with class="cmp-articleitem" that have titles, dates, links, and descriptions
- Press releases from the Cisco newsroom

EXAMPLES of what to SKIP:
- Filter links
- Navigation links
- Category/tag links
- Links that don't point to actual articles
- Template elements (those with data-id="article-template" or style="display: none")

Return a JSON array with ALL articles found.

JSON structure:
[
  {{
    "title": "First Article Title",
    "date": "2025-11-12",
    "link": "https://newsroom.cisco.com/content/r/newsroom/en/us/a/y2025/m11/article.html",
    "description": "Article description text"
  }},
  {{
    "title": "Second Article Title",
    "date": "2025-11-10",
    "link": "https://newsroom.cisco.com/content/r/newsroom/en/us/a/y2025/m11/article2.html",
    "description": "Another article description"
  }}
  // ... continue for ALL articles found
]

HTML Content:
{html_content}

Return ONLY valid JSON array. Extract EVERY article you can find. No explanations, no markdown, just the JSON array."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",  # Using gpt-4o-mini for cost efficiency, can be changed to gpt-4 if needed
                messages=[
                    {"role": "system", "content": "You are a web scraping expert that extracts ALL articles from HTML. You MUST find every single article on the page. Return only valid JSON arrays with all articles found. Be extremely thorough - typical news listing pages have 10-50+ articles."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=8000  # Increased to allow for many articles
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Remove markdown code blocks if present
            if result_text.startswith("```json"):
                result_text = result_text[7:]
            if result_text.startswith("```"):
                result_text = result_text[3:]
            if result_text.endswith("```"):
                result_text = result_text[:-3]
            result_text = result_text.strip()
            
            # Parse JSON
            articles = json.loads(result_text)
            
            # Ensure all articles have required fields
            structured_articles = []
            for article in articles:
                if isinstance(article, dict):
                    structured_article = {
                        "title": article.get("title", "N/A"),
                        "date": article.get("date", "N/A"),
                        "link": article.get("link", "N/A"),
                        "description": article.get("description", "N/A")
                    }
                    structured_articles.append(structured_article)
            
            return structured_articles
            
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON response: {e}")
            logger.error(f"Response was: {result_text}")
            return []
        except Exception as e:
            raise Exception(f"LLM analysis failed: {str(e)}")
    
    def scrape(self, debug: bool = False) -> List[Dict]:
        """
        Main method to scrape and analyze the page.
        
        Args:
            debug: If True, save extracted HTML to file for debugging
        
        Returns:
            List of structured article data
        """
        logger.info("Fetching HTML from Cisco press releases page...")
        html = self.fetch_html()
        
        if debug:
            # Determine project root (handle both root and scrapers/ subfolder)
            script_dir = Path(__file__).parent
            if script_dir.name == "scrapers":
                project_root = script_dir.parent
            else:
                project_root = script_dir
            
            # Create debug folder if it doesn't exist
            debug_dir = project_root / "debug"
            debug_dir.mkdir(exist_ok=True)
            
            # Save to debug folder
            debug_filepath = debug_dir / "debug_cisco_news_full_html.html"
            with open(debug_filepath, "w", encoding="utf-8") as f:
                f.write(html)
            logger.debug(f"[DEBUG] Full HTML saved to debug_cisco_news_full_html.html ({len(html)} chars)")
        
        # First, try to extract article links directly
        logger.info("Extracting article links directly from HTML...")
        direct_articles = self.extract_article_links(html)
        logger.debug(f"[DEBUG] Found {len(direct_articles)} article links using BeautifulSoup")
        
        logger.info("Extracting HTML structure for LLM analysis...")
        html_structure = self.extract_html_structure(html)
        
        if debug:
            # Determine project root (handle both root and scrapers/ subfolder)
            script_dir = Path(__file__).parent
            if script_dir.name == "scrapers":
                project_root = script_dir.parent
            else:
                project_root = script_dir
            
            # Create debug folder if it doesn't exist
            debug_dir = project_root / "debug"
            debug_dir.mkdir(exist_ok=True)
            
            # Save to debug folder
            debug_filepath = debug_dir / "debug_cisco_news_extracted_html.html"
            with open(debug_filepath, "w", encoding="utf-8") as f:
                f.write(html_structure)
            logger.debug(f"[DEBUG] Extracted HTML saved to debug_cisco_news_extracted_html.html ({len(html_structure)} chars)")
        
        # Count potential articles in HTML
        soup = BeautifulSoup(html_structure, 'html.parser')
        news_links = soup.find_all('div', class_='cmp-articleitem')
        logger.debug(f"[DEBUG] Found {len(news_links)} article items in extracted HTML")
        
        logger.info("Analyzing content with LLM to extract detailed information...")
        llm_articles = self.analyze_with_llm(html_structure)
        logger.debug(f"[DEBUG] LLM found {len(llm_articles)} articles")
        
        # Combine results - prefer direct extraction, use LLM as supplement
        articles = []
        direct_links = {art['link'] for art in direct_articles}
        
        # Start with direct extraction results
        for art in direct_articles:
            articles.append({
                'title': art['title'],
                'date': art['date'],
                'link': art['link'],
                'description': art['description']
            })
        
        # Add any LLM results that weren't found by direct extraction
        for llm_art in llm_articles:
            llm_link = llm_art.get('link', '')
            # Only add if not already found and is a valid article link
            if llm_link not in direct_links and llm_link != "N/A" and '/a/y' in llm_link:
                articles.append(llm_art)
        
        logger.info(f"Final result: {len(articles)} articles found")
        if len(direct_articles) > 0:
            logger.info(f"  - {len(direct_articles)} from direct extraction")
        if len(articles) > len(direct_articles):
            logger.info(f"  - {len(articles) - len(direct_articles)} additional from LLM")
        
        return articles
    
    def display_results(self, articles: List[Dict]):
        """
        Display results in a structured format.
        
        Args:
            articles: List of article dictionaries
        """
        if not articles:
            logger.info("\nNo articles found.")
            return
        
        logger.info(f"\n{'='*80}")
        logger.info(f"Found {len(articles)} article(s)")
        logger.info(f"{'='*80}\n")
        
        for idx, article in enumerate(articles, 1):
            logger.info(f"Article {idx}:")
            logger.info(f"  Title:       {article['title']}")
            logger.info(f"  Date:        {article['date']}")
            logger.info(f"  Link:        {article['link']}")
            logger.info(f"  Description: {article['description']}")
            logger.info("-" * 80)
    
    def save_to_json(self, articles: List[Dict], filename: str = "cisco_news.json"):
        """
        Save results to JSON file in the data/ folder.
        
        Args:
            articles: List of article dictionaries
            filename: Output filename
        """
        # Determine project root (handle both root and scrapers/ subfolder)
        script_dir = Path(__file__).parent
        if script_dir.name == "scrapers":
            project_root = script_dir.parent
        else:
            project_root = script_dir
        
        # Create data folder if it doesn't exist
        data_dir = project_root / "data"
        data_dir.mkdir(exist_ok=True)
        
        # Save to data folder
        filepath = data_dir / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(articles, f, indent=2, ensure_ascii=False)
        logger.info(f"\nResults saved to {filepath}")


def main():
    """Main entry point."""
    import sys
    import gc
    
    # Check for debug flag first (before parsing API key)
    debug = "--debug" in sys.argv or "-d" in sys.argv
    
    # Filter out debug flags from arguments when looking for API key
    args_without_flags = [arg for arg in sys.argv[1:] if arg not in ["--debug", "-d"]]
    
    # API key from environment variable first, then numbered keys, then command line
    api_key = os.getenv("OPENAI_API_KEY")
    
    # If not found, try numbered keys (OPENAI_API_KEY_1, OPENAI_API_KEY_2, etc.)
    if not api_key:
        i = 1
        while i <= 10:  # Check up to 10 numbered keys
            api_key = os.getenv(f"OPENAI_API_KEY_{i}")
            if api_key:
                print(f"Using OPENAI_API_KEY_{i} from environment")
                break
            i += 1
    
    # If still not found, try command line argument
    if not api_key and args_without_flags:
        api_key = args_without_flags[0]
    
    if not api_key:
        print("Error: OPENAI_API_KEY not found!")
        print("Please either:")
        print("  1. Set OPENAI_API_KEY or OPENAI_API_KEY_1 environment variable")
        print("  2. Create a .env file with OPENAI_API_KEY=your_key_here")
        print("  3. Provide it as a command line argument: python cisco_news_scraper.py your_api_key")
        return 1
    
    try:
        scraper = CiscoNewsScraper(api_key=api_key)
        articles = scraper.scrape(debug=debug)
        scraper.display_results(articles)
        scraper.save_to_json(articles)
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        # Suppress stderr during cleanup to avoid harmless exception messages from driver destructor
        # The exception occurs during garbage collection when Python destroys the driver object
        with redirect_stderr(StringIO()):
            time.sleep(0.3)
            # Force garbage collection to trigger cleanup while stderr is suppressed
            gc.collect()
            time.sleep(0.3)
    
    return 0


if __name__ == "__main__":
    exit(main())

