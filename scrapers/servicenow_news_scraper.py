"""
LLM-based scraper for extracting structured data from ServiceNow press room page.
Extracts: title, date, link, tags
"""

import requests
from bs4 import BeautifulSoup
from openai import OpenAI
import json
import os
import time
import re
from typing import List, Dict
from pathlib import Path
from dotenv import load_dotenv
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Load environment variables
load_dotenv()

class ServiceNowNewsScraper:
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
        self.url = "https://newsroom.servicenow.com/press-releases/default.aspx"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def fetch_html(self, use_selenium: bool = True) -> str:
        """
        Fetch HTML content from the ServiceNow press room page.
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
            print("Initializing browser (this may take a moment)...")
            
            # Find Chrome executable path
            import shutil
            chrome_path = None
            # Common Chrome installation paths on Windows
            possible_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
            ]
            
            for path in possible_paths:
                if os.path.exists(path):
                    chrome_path = path
                    break
            
            # If not found in common locations, try to find it
            if not chrome_path:
                chrome_path = shutil.which('chrome') or shutil.which('chromium') or shutil.which('google-chrome')
            
            # Create options
            options = uc.ChromeOptions()
            options.add_argument('--start-maximized')
            options.add_argument('--disable-blink-features=AutomationControlled')
            
            # Set binary_location if we found Chrome
            if chrome_path:
                options.binary_location = chrome_path
            
            # Initialize driver
            driver = uc.Chrome(options=options, version_main=None)
            
            print("Loading page...")
            driver.get(self.url)
            
            # Wait for content to load
            print("Waiting for page content to load...")
            max_wait = 15  # Reduced from 30 to 15 seconds
            waited = 0
            while waited < max_wait:
                page_source = driver.page_source
                
                # Check if we have actual content - look for module_item elements
                module_items = driver.find_elements(By.CSS_SELECTOR, ".module_item")
                module_content = driver.find_elements(By.CSS_SELECTOR, "#newsList")
                links = driver.find_elements(By.CSS_SELECTOR, "a.module_headline-link")
                
                if len(module_items) > 0 or len(module_content) > 0 or len(links) > 5 or len(page_source) > 50000:
                    print(f"[OK] Content loaded successfully!")
                    break
                
                time.sleep(1)  # Reduced from 2 to 1 second
                waited += 1
                if waited % 3 == 0:
                    print(f"  Still waiting... ({waited}s)")
            
            # Additional wait for JavaScript to fully render
            time.sleep(2)  # Reduced from 4 to 2 seconds
            
            html = driver.page_source
            print(f"Retrieved HTML: {len(html)} characters")
            
            if len(html) < 10000:
                print(f"[WARNING] Retrieved HTML seems too short ({len(html)} chars). The page might still be loading.")
                print("Trying to wait a bit longer...")
                time.sleep(3)  # Reduced from 5 to 3 seconds
                html = driver.page_source
                print(f"Retrieved HTML after additional wait: {len(html)} characters")
            
            # Try to find module items to verify we have content
            temp_soup = BeautifulSoup(html, 'html.parser')
            test_items = temp_soup.find_all('div', class_='module_item')
            print(f"[DEBUG] Found {len(test_items)} module_item elements in full HTML")
            
            return html
        except Exception as e:
            raise Exception(f"Failed to fetch HTML with Selenium: {str(e)}")
        finally:
            if driver:
                print("Closing browser...")
                driver.quit()
    
    def extract_article_links(self, html: str) -> List[Dict]:
        """
        Extract press release article links using BeautifulSoup.
        Targets module_item elements from newsroom.servicenow.com.
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with basic article info (link, title, date, tags)
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Find all module_item elements
        module_items = soup.find_all('div', class_='module_item')
        
        print(f"[DEBUG] Found {len(module_items)} module_item elements")
        
        # Process each module item
        for idx, item in enumerate(module_items):
            # Extract date from module_date-time
            date_text = "N/A"
            date_elem = item.find('div', class_='module_date-time')
            if date_elem:
                date_text = date_elem.get_text(strip=True)
            
            # Extract title and link from module_headline > a.module_headline-link
            title = "N/A"
            link = None
            headline_elem = item.find('div', class_='module_headline')
            if headline_elem:
                link_elem = headline_elem.find('a', class_='module_headline-link')
                if link_elem:
                    title = link_elem.get_text(strip=True)
                    href = link_elem.get('href', '')
                    
                    # Make URL absolute
                    if href.startswith('/'):
                        link = f"https://newsroom.servicenow.com{href}"
                    elif href.startswith('http'):
                        link = href
                    else:
                        # Relative URL
                        link = f"https://newsroom.servicenow.com/{href.lstrip('/')}"
            
            # Skip if no valid link or title
            if not link or not title or len(title) < 5:
                continue
            
            # Avoid duplicates
            if link in seen_links:
                continue
            seen_links.add(link)
            
            # Extract tags (default to Press Release)
            tags = ['Press Release']
            
            articles.append({
                'link': link,
                'title': title,
                'date': date_text,
                'tags': tags
            })
            
            print(f"[DEBUG] Extracted article {idx+1}: {title[:50]}...")
        
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
        
        # Try to find the module_container--content (newsList)
        news_list = soup.find('div', id='newsList')
        
        if news_list:
            # Extract all module_item elements
            content_str = str(news_list)
        else:
            # Fallback: look for module_item elements directly
            module_items = soup.find_all('div', class_='module_item')
            if module_items:
                items_html = [str(item) for item in module_items]
                content_str = '\n'.join(items_html)
            else:
                # Fallback: look for module_container
                module_container = soup.find('div', class_=lambda x: x and 'module_container' in str(x))
                if module_container:
                    content_str = str(module_container)
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
            List of dictionaries with title, date, link, tags
        """
        prompt = f"""You are analyzing HTML from ServiceNow newsroom page (https://newsroom.servicenow.com/press-releases/default.aspx). Your task is to extract ALL press release articles from the page.

CRITICAL INSTRUCTIONS:
1. Extract ALL press release articles you can find on the page - be extremely thorough
2. Each press release article should become a separate entry
3. Do NOT extract filter links, navigation links, or category links
4. Extract ALL press release articles you can find (typically 50-100+ on a listing page)
5. Look for ALL module_item elements - don't miss any
6. If articles are in a list, extract EVERY single one

What to look for:
- Module items with class "module_item"
- Date in div with class "module_date-time" (format: MM/DD/YYYY like "11/18/2025")
- Title and link in div.module_headline > a.module_headline-link
- Links that point to actual article pages (href containing "/press-releases/details/")
- Skip any filter or navigation elements
- Skip the year dropdown selector

For EACH press release article you find, extract:
- title: The headline or title from the module_headline-link (required)
- date: Publication date from module_date-time (format as YYYY-MM-DD if possible, otherwise keep original format like "11/18/2025", use "N/A" if not found)
- link: Full URL (if relative, prepend https://newsroom.servicenow.com. Use "N/A" only if absolutely no link exists)
- tags: List of tags/categories (default to ["Press Release"] if none found)

EXAMPLES of what to extract:
- All module_item elements with dates, titles, and links
- Press releases from the newsList container

EXAMPLES of what to SKIP:
- Year dropdown selector
- Navigation links
- Filter elements
- Links that don't point to actual articles

Return a JSON array with ALL press release articles found.

JSON structure:
[
  {{
    "title": "First Article Title",
    "date": "2025-11-18",
    "link": "https://newsroom.servicenow.com/press-releases/details/2025/article-1/default.aspx",
    "tags": ["Press Release"]
  }},
  {{
    "title": "Second Article Title",
    "date": "2025-11-06",
    "link": "https://newsroom.servicenow.com/press-releases/details/2025/article-2/default.aspx",
    "tags": ["Press Release"]
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
                    {"role": "system", "content": "You are a web scraping expert that extracts ALL articles from HTML. You MUST find every single press release article on the page. Return only valid JSON arrays with all articles found. Be extremely thorough - typical press listing pages have 25-100+ articles."},
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
                        "tags": article.get("tags", ["Press Release"]) if isinstance(article.get("tags"), list) else ["Press Release"]
                    }
                    structured_articles.append(structured_article)
            
            return structured_articles
            
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON response: {e}")
            print(f"Response was: {result_text}")
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
        print("Fetching HTML from ServiceNow newsroom page...")
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
            debug_filepath = debug_dir / "debug_servicenow_news_full_html.html"
            with open(debug_filepath, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[DEBUG] Full HTML saved to {debug_filepath} ({len(html)} chars)")

        # First, try to extract article links directly
        print("Extracting article links directly from HTML...")
        direct_articles = self.extract_article_links(html)
        print(f"[DEBUG] Found {len(direct_articles)} article links using BeautifulSoup")
        
        print("Extracting HTML structure for LLM analysis...")
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
            debug_filepath = debug_dir / "debug_servicenow_news_extracted_html.html"
            with open(debug_filepath, "w", encoding="utf-8") as f:
                f.write(html_structure)
            print(f"[DEBUG] Extracted HTML saved to {debug_filepath} ({len(html_structure)} chars)")

        # Count potential articles in HTML
        soup = BeautifulSoup(html_structure, 'html.parser')
        module_items = soup.find_all('div', class_='module_item')
        print(f"[DEBUG] Found {len(module_items)} potential module_item elements in extracted HTML")
        
        print("Analyzing content with LLM to extract detailed information...")
        llm_articles = self.analyze_with_llm(html_structure)
        print(f"[DEBUG] LLM found {len(llm_articles)} articles")
        
        # Combine results - prefer direct extraction, use LLM as supplement
        articles = []
        direct_links = {art['link'] for art in direct_articles}
        
        # Start with direct extraction results
        for art in direct_articles:
            articles.append({
                'title': art['title'],
                'date': art['date'],
                'link': art['link'],
                'tags': art.get('tags', ['Press Release'])
            })
        
        # Add any LLM results that weren't found by direct extraction
        for llm_art in llm_articles:
            llm_link = llm_art.get('link', '')
            # Only add if not already found and is a valid article link
            if llm_link not in direct_links:
                # Check if it's a valid article link
                is_valid = False
                if '/press-releases/details/' in llm_link or 'newsroom.servicenow.com' in llm_link:
                    # Make sure it's not just the main page or a filter link
                    if not llm_link.endswith('/default.aspx') and '#' not in llm_link:
                        is_valid = True
                
                if is_valid:
                    articles.append(llm_art)
        
        print(f"Final result: {len(articles)} press release articles found")
        if len(direct_articles) > 0:
            print(f"  - {len(direct_articles)} from direct extraction")
        if len(articles) > len(direct_articles):
            print(f"  - {len(articles) - len(direct_articles)} additional from LLM")
        
        return articles
    
    def display_results(self, articles: List[Dict]):
        """
        Display results in a structured format.
        
        Args:
            articles: List of article dictionaries
        """
        if not articles:
            print("\nNo articles found.")
            return
        
        print(f"\n{'='*80}")
        print(f"Found {len(articles)} article(s)")
        print(f"{'='*80}\n")
        
        for idx, article in enumerate(articles, 1):
            print(f"Article {idx}:")
            print(f"  Title: {article['title']}")
            print(f"  Date:  {article['date']}")
            print(f"  Link:  {article['link']}")
            print(f"  Tags:  {', '.join(article['tags']) if article['tags'] else 'N/A'}")
            print("-" * 80)
    
    def save_to_json(self, articles: List[Dict], filename: str = "servicenow_news.json"):
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
        print(f"Results saved to {filepath}")

def main():
    """Main entry point."""
    import sys
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
        print("  3. Provide it as a command line argument: python servicenow_news_scraper.py your_api_key")
        return 1
    
    try:
        scraper = ServiceNowNewsScraper(api_key=api_key)
        articles = scraper.scrape(debug=debug)
        scraper.display_results(articles)
        scraper.save_to_json(articles)
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())

