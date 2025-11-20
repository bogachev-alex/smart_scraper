"""
LLM-based scraper for extracting structured data from Nokia newsroom page.
Extracts: title, date, link
Renamed from nokia_scraper.py to nokia_news_scraper.py
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
import warnings
import logging

# Suppress harmless warnings from undetected_chromedriver
warnings.filterwarnings('ignore', message='.*could not detect version_main.*')
logging.getLogger('undetected_chromedriver').setLevel(logging.ERROR)

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Load environment variables
load_dotenv()


class NokiaNewsScraper:
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
        self.url = "https://www.nokia.com/newsroom/?h=1&t=press%20releases&match=1"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def fetch_html(self, use_selenium: bool = True) -> str:
        """
        Fetch HTML content from the Nokia newsroom page.
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
    
    def _fetch_html_selenium(self, max_retries: int = 3) -> str:
        """Fetch HTML using undetected-chromedriver to bypass bot protection.
        Always uses non-headless mode.
        
        Args:
            max_retries: Maximum number of retry attempts
        """
        def detect_access_denied(html: str) -> bool:
            """Detect if HTML indicates access denied or blocking."""
            if not html:
                return False
            html_lower = html.lower()
            error_indicators = [
                'access denied', 'access forbidden', 'you don\'t have permission',
                'you do not have permission', '403 forbidden', 'forbidden', 'blocked',
                'errors.edgesuite.net', 'reference #', 'cloudflare', 'checking your browser',
                'ddos protection', 'captcha', 'bot detection', 'automated access',
                'please verify you are human'
            ]
            return any(indicator in html_lower for indicator in error_indicators)
        
        driver = None
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    print(f"Retry attempt {attempt + 1}/{max_retries}...")
                    time.sleep(2 ** attempt)  # Exponential backoff
                
                print(f"Initializing browser (headless=False)...")
                options = uc.ChromeOptions()
                options.add_argument('--start-maximized')
                options.add_argument('--disable-blink-features=AutomationControlled')
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
                options.add_argument('--disable-web-security')
                options.add_argument('--disable-features=IsolateOrigins,site-per-process')
                
                driver = uc.Chrome(options=options, version_main=None)
                
                print("Loading page...")
                driver.get(self.url)
                
                # Wait for content to load
                print("Waiting for page content to load...")
                max_wait = 30
                waited = 0
                while waited < max_wait:
                    page_source = driver.page_source
                    
                    # Check for access denied
                    if detect_access_denied(page_source):
                        print(f"[ERROR] Access denied detected in page source")
                        if driver:
                            try:
                                driver.quit()
                            except:
                                pass
                            driver = None
                        raise Exception("Access denied by server")
                        
                        # Check if we have actual content
                        articles = driver.find_elements(By.TAG_NAME, "article")
                        links = driver.find_elements(By.CSS_SELECTOR, "a[href*='newsroom'], a[href*='press'], a[href*='article']")
                        main_content = driver.find_elements(By.TAG_NAME, "main")
                        
                        if len(articles) > 0 or len(links) > 5 or len(main_content) > 0 or len(page_source) > 20000:
                            print(f"[OK] Content loaded successfully!")
                            break
                        
                        time.sleep(2)
                        waited += 2
                        if waited % 4 == 0:
                            print(f"  Still waiting... ({waited}s)")
                    
                    # Additional wait for JavaScript to fully render
                    time.sleep(3)
                    
                    html = driver.page_source
                    print(f"Retrieved HTML: {len(html)} characters")
                    
                    # Final check for access denied
                    if detect_access_denied(html):
                        print(f"[ERROR] Access denied detected in final HTML")
                        if driver:
                            try:
                                driver.quit()
                            except:
                                pass
                            driver = None
                        raise Exception("Access denied by server")
                    
                    if len(html) < 10000:
                        print(f"[WARNING] Retrieved HTML seems too short ({len(html)} chars). The page might still be loading.")
                        print("Trying to wait a bit longer...")
                        time.sleep(5)
                        html = driver.page_source
                        print(f"Retrieved HTML after additional wait: {len(html)} characters")
                        
                        # Check for errors again
                        if detect_access_denied(html):
                            print(f"[ERROR] Access denied detected after additional wait")
                            if driver:
                                try:
                                    driver.quit()
                                except:
                                    pass
                                driver = None
                            raise Exception("Access denied by server")
                    
                    # Try to find article links to verify we have content
                    temp_soup = BeautifulSoup(html, 'html.parser')
                    test_links = temp_soup.find_all('a', href=lambda x: x and any(kw in x.lower() for kw in ['newsroom', 'press', 'news']))
                    print(f"[DEBUG] Found {len(test_links)} newsroom/press links in full HTML")
                    
                    # Success - return HTML
                    if driver:
                        try:
                            driver.quit()
                        except:
                            pass
                    
                    return html
                    
            except Exception as e:
                last_exception = e
                print(f"Error during fetch attempt: {str(e)}")
                if driver:
                    try:
                        driver.quit()
                    except:
                        pass
                    driver = None
                
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
        
        # All retries failed
        raise Exception(f"Failed to fetch HTML after {max_retries} attempts: {str(last_exception)}")
    
    def extract_article_links(self, html: str) -> List[Dict]:
        """
        Extract press release article links using BeautifulSoup.
        Specifically targets the Nokia press releases structure with class 'td_headlines'.
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with basic article info (link, title, date)
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Find the container with press releases
        # Look for div with class 'ppmodule_headlines' or 'archive_item_container'
        container = soup.find('div', class_=lambda x: x and ('ppmodule_headlines' in str(x) or 'archive_item_container' in str(x)))
        
        if not container:
            # Fallback: look for all links with class 'td_headlines'
            article_links = soup.find_all('a', class_='td_headlines')
        else:
            # Find all article links within the container
            article_links = container.find_all('a', class_='td_headlines')
        
        print(f"[DEBUG] Found {len(article_links)} article links with class 'td_headlines'")
        
        # Process each article link
        for idx, link in enumerate(article_links):
            # Extract URL
            href = link.get('href', '')
            if not href:
                continue
            
            # Skip filter/search links
            if '?h=' in href or '?t=' in href or '?match=' in href:
                continue
            
            # Make URL absolute
            if href.startswith('/'):
                full_url = f"https://www.nokia.com{href}"
            elif href.startswith('http'):
                full_url = href
            else:
                continue
            
            # Avoid duplicates
            if full_url in seen_links:
                continue
            seen_links.add(full_url)
            
            # Extract title - try multiple sources
            title = "N/A"
            
            # 1. Try title attribute
            title_attr = link.get('title', '')
            if title_attr and len(title_attr) > 10:
                title = title_attr
            
            # 2. Try h3 inside pp_headline div
            if title == "N/A" or len(title) < 10:
                headline_div = link.find('div', class_='pp_headline')
                if headline_div:
                    h3 = headline_div.find('h3')
                    if h3:
                        title = h3.get_text(strip=True)
            
            # 3. Fallback to link text
            if title == "N/A" or len(title) < 10:
                link_text = link.get_text(strip=True)
                if link_text and len(link_text) > 10:
                    title = link_text
            
            # Extract date from pp_publishdate div
            date_text = "N/A"
            publishdate_div = link.find('div', class_='pp_publishdate')
            
            if publishdate_div:
                # Extract month, day, year
                month_elem = publishdate_div.find('div', class_='pp_date_month')
                day_elem = publishdate_div.find('div', class_='pp_date_day')
                year_elem = publishdate_div.find('div', class_='pp_date_year')
                
                month = month_elem.get_text(strip=True) if month_elem else ""
                day = day_elem.get_text(strip=True) if day_elem else ""
                year = year_elem.get_text(strip=True) if year_elem else ""
                
                # Clean day (remove comma if present)
                day = day.replace(',', '').strip()
                
                # Format date
                if month and day and year:
                    # Try to format as YYYY-MM-DD
                    month_map = {
                        'January': '01', 'February': '02', 'March': '03', 'April': '04',
                        'May': '05', 'June': '06', 'July': '07', 'August': '08',
                        'September': '09', 'October': '10', 'November': '11', 'December': '12',
                        'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
                        'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
                        'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
                    }
                    
                    month_num = month_map.get(month, month)
                    if month_num.isdigit():
                        day_padded = day.zfill(2)
                        date_text = f"{year}-{month_num}-{day_padded}"
                    else:
                        # Fallback to readable format
                        date_text = f"{month} {day}, {year}"
                elif year:
                    # At least we have the year
                    date_text = year
            
            # If date still not found, try regex patterns on the link text
            if date_text == "N/A":
                link_text = link.get_text()
                date_patterns = [
                    r'\b(\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b',
                    r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b',
                    r'\b\d{4}-\d{2}-\d{2}\b',
                    r'\b\d{1,2}/\d{1,2}/\d{4}\b',
                ]
                for pattern in date_patterns:
                    match = re.search(pattern, link_text, re.IGNORECASE)
                    if match:
                        date_text = match.group(1) if match.lastindex >= 1 else match.group(0)
                        break
            
            articles.append({
                'link': full_url,
                'title': title,
                'date': date_text
            })
            
            print(f"[DEBUG] Extracted article {idx+1}: {title[:50]}...")
        
        return articles
    
    def extract_html_structure(self, html: str) -> str:
        """
        Extract relevant HTML structure for LLM analysis.
        Specifically targets the Nokia press releases structure.
        
        Args:
            html: Raw HTML content
            
        Returns:
            Cleaned HTML structure as string
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style", "noscript"]):
            script.decompose()
        
        # Strategy 1: Look for the specific Nokia press releases container
        main_content = None
        
        # Try to find the ppmodule_headlines container
        main_content = soup.find('div', class_=lambda x: x and 'ppmodule_headlines' in str(x))
        
        # If not found, try archive_item_container
        if not main_content:
            main_content = soup.find('div', class_=lambda x: x and 'archive_item_container' in str(x))
        
        # If not found, try div_headlines
        if not main_content:
            main_content = soup.find('div', class_='div_headlines')
        
        # If still not found, try to find all td_headlines links and their container
        if not main_content:
            article_links = soup.find_all('a', class_='td_headlines')
            if article_links:
                # Get the parent container of the first link
                first_link = article_links[0]
                main_content = first_link.find_parent(['div', 'section', 'main'])
        
        # Fallback: Look for common news/press content selectors
        if not main_content:
            content_selectors = [
                ('main', {}),
                ('article', {}),
                ('div', {'class': lambda x: x and any(keyword in str(x).lower() for keyword in ['news', 'press', 'article', 'release', 'content', 'listing', 'newsroom'])}),
                ('section', {'class': lambda x: x and any(keyword in str(x).lower() for keyword in ['news', 'press', 'article', 'release', 'newsroom'])}),
            ]
            
            for tag, attrs in content_selectors:
                main_content = soup.find(tag, attrs)
                if main_content:
                    break
        
        if main_content:
            # Extract text and links from main content
            content_str = str(main_content)
        else:
            # Fallback: extract all td_headlines links and their context
            article_links = soup.find_all('a', class_='td_headlines')
            if article_links:
                links_html = []
                for link in article_links:
                    # Get the link and its immediate parent for context
                    parent = link.find_parent(['div', 'li', 'article', 'section'])
                    if parent:
                        links_html.append(str(parent))
                content_str = '\n'.join(links_html) if links_html else str(soup.find('body') or html)
            else:
                # Last resort: get body
                body = soup.find('body')
                content_str = str(body) if body else html
        
        # Limit content size to avoid token limits (keep first 150000 chars for better context)
        if len(content_str) > 150000:
            content_str = content_str[:150000] + "..."
        
        return content_str
    
    def analyze_with_llm(self, html_content: str) -> List[Dict]:
        """
        Use OpenAI LLM to extract structured data from HTML.
        
        Args:
            html_content: HTML content to analyze
            
        Returns:
            List of dictionaries with title, date, link
        """
        prompt = f"""You are analyzing HTML from Nokia newsroom page (https://www.nokia.com/newsroom/?h=1&t=press%20releases&match=1). Your task is to extract ALL press release articles from the page.

CRITICAL INSTRUCTIONS:
1. Extract ALL press release articles you can find on the page
2. Each press release article should become a separate entry
3. Do NOT extract filter links, navigation links, or category links
4. Do NOT extract links with query parameters like ?h=, ?t=, ?match= (these are filter/search links)
5. Extract ALL press release articles you can find (typically 10-50+ on a listing page)

What to look for:
- Article cards/containers that contain press release content
- Links within those containers that point to actual article pages (href containing "/newsroom/" with descriptive path)
- Titles/headlines in headings (<h1>, <h2>, <h3>, <h4>) within press release containers
- Dates in formats like "11 Nov 2025", "Nov 11, 2025", "2025-11-11", "11/11/2025", etc.
- Skip any links with query parameters like ?h=, ?t=, ?match= (these are filter links, not articles)

For EACH press release article you find, extract:
- title: The headline or title (required - use link text if no explicit title)
- date: Publication date (format as YYYY-MM-DD if possible, otherwise keep original format, use "N/A" if not found)
- link: Full URL (if relative, prepend https://www.nokia.com. Use "N/A" only if absolutely no link exists)

EXAMPLES of what to extract:
- Press releases with dates and titles
- Articles from the newsroom with full URLs

EXAMPLES of what to SKIP:
- Filter links (URLs with ?h=, ?t=, ?match=)
- Navigation links
- Category/tag links
- Links that just say "Press releases" (those are filters, not articles)
- Links to /newsroom without a specific article path

Return a JSON array with ALL press release articles found.

JSON structure:
[
  {{
    "title": "First Article Title",
    "date": "2025-11-11",
    "link": "https://www.nokia.com/newsroom/article-1"
  }},
  {{
    "title": "Second Article Title",
    "date": "2025-10-15",
    "link": "https://www.nokia.com/newsroom/article-2"
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
                    {"role": "system", "content": "You are a web scraping expert that extracts ALL articles from HTML. You MUST find every single press release article on the page. Return only valid JSON arrays with all articles found. Be extremely thorough - typical news listing pages have 10-50+ articles."},
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
                        "link": article.get("link", "N/A")
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
        print("Fetching HTML from Nokia newsroom page...")
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
            debug_filepath = debug_dir / "debug_nokia_full_html.html"
            with open(debug_filepath, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[DEBUG] Full HTML saved to debug_nokia_full_html.html ({len(html)} chars)")
        
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
            debug_filepath = debug_dir / "debug_nokia_extracted_html.html"
            with open(debug_filepath, "w", encoding="utf-8") as f:
                f.write(html_structure)
            print(f"[DEBUG] Extracted HTML saved to debug_nokia_extracted_html.html ({len(html_structure)} chars)")
        
        # Count potential articles in HTML
        soup = BeautifulSoup(html_structure, 'html.parser')
        news_links = soup.find_all('a', href=lambda x: x and any(kw in x.lower() for kw in ['newsroom', 'press', 'article']))
        print(f"[DEBUG] Found {len(news_links)} potential newsroom/press links in extracted HTML")
        
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
                'link': art['link']
            })
        
        # Add any LLM results that weren't found by direct extraction
        for llm_art in llm_articles:
            llm_link = llm_art.get('link', '')
            # Only add if not already found and is a valid article link
            if llm_link not in direct_links and '/newsroom/' in llm_link and '?h=' not in llm_link and '?t=' not in llm_link:
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
            print("-" * 80)
    
    def save_to_json(self, articles: List[Dict], filename: str = "nokia_news.json"):
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
        print(f"\nResults saved to {filepath}")


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
        print("  3. Provide it as a command line argument: python nokia_news_scraper.py your_api_key")
        return 1
    
    try:
        scraper = NokiaNewsScraper(api_key=api_key)
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

