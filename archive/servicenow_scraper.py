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
from dotenv import load_dotenv
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Load environment variables
load_dotenv()


class ServiceNowScraper:
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
        self.url = "https://www.servicenow.com/company/media/press-room.html"
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
    
    def _fetch_html_selenium(self, use_headless: bool = False, max_retries: int = 3) -> str:
        """Fetch HTML using undetected-chromedriver to bypass bot protection.
        
        Args:
            use_headless: Whether to use headless mode (default: False, uses visible browser)
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
        
        # Use non-headless mode (visible browser) by default
        headless_modes = [False] if not use_headless else [True, False]
        
        for attempt in range(max_retries):
            for current_headless in headless_modes:
                try:
                    if attempt > 0:
                        print(f"Retry attempt {attempt + 1}/{max_retries} (headless={current_headless})...")
                        time.sleep(2 ** attempt)  # Exponential backoff
                    
                    print(f"Initializing browser (headless={current_headless})...")
                    
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
                    if current_headless:
                        options.add_argument('--headless=new')
                    else:
                        options.add_argument('--start-maximized')
                    options.add_argument('--disable-blink-features=AutomationControlled')
                    options.add_argument('--no-sandbox')
                    options.add_argument('--disable-dev-shm-usage')
                    options.add_argument('--disable-gpu')
                    
                    # Set binary_location if we found Chrome
                    if chrome_path:
                        options.binary_location = chrome_path
                    
                    # Initialize driver
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
                            
                            # If we're in headless mode, try non-headless next
                            if current_headless:
                                print("[RETRY] Retrying with non-headless browser (better stealth)...")
                                break  # Break inner loop to try non-headless
                            else:
                                # Already tried non-headless, raise exception
                                raise Exception("Access denied by server even with non-headless browser")
                        
                        # Check if we have actual content - look for module_item or press-releases
                        module_items = driver.find_elements(By.CSS_SELECTOR, ".module_item, [class*='module_item']")
                        news_list = driver.find_elements(By.CSS_SELECTOR, "#newsList, [id='newsList']")
                        links = driver.find_elements(By.CSS_SELECTOR, "a[href*='press-releases'], a[href*='press-room'], a[href*='press']")
                        main_content = driver.find_elements(By.TAG_NAME, "main")
                        
                        if len(module_items) > 0 or len(news_list) > 0 or len(links) > 5 or len(main_content) > 0 or len(page_source) > 20000:
                            print(f"[OK] Content loaded successfully!")
                            break
                        
                        time.sleep(2)
                        waited += 2
                        if waited % 4 == 0:
                            print(f"  Still waiting... ({waited}s)")
                    
                    # Additional wait for JavaScript to fully render
                    time.sleep(4)
                    
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
                        
                        # If we're in headless mode and got access denied, try non-headless
                        if current_headless:
                            print("[RETRY] Retrying with non-headless browser (better stealth)...")
                            continue  # Continue to next iteration (non-headless)
                        else:
                            # Already tried non-headless, raise exception
                            raise Exception("Access denied by server even with non-headless browser")
                    
                    if len(html) < 10000:
                        print(f"[WARNING] Retrieved HTML seems too short ({len(html)} chars). The page might still be loading.")
                        print("Trying to wait a bit longer...")
                        time.sleep(5)
                        html = driver.page_source
                        print(f"Retrieved HTML after additional wait: {len(html)} characters")
                    
                    # If HTML is still extremely short after waiting, something is wrong
                    if len(html) < 1000:
                        raise Exception(f"Page did not load properly. Retrieved only {len(html)} characters. The page may be blocking automated access or the URL may be incorrect.")
                    
                    # Try to find press release links to verify we have content
                    temp_soup = BeautifulSoup(html, 'html.parser')
                    module_items = temp_soup.find_all('div', class_='module_item')
                    test_links = temp_soup.find_all('a', href=lambda x: x and ('press-releases' in x.lower() or 'press-room' in x.lower()))
                    print(f"[DEBUG] Found {len(module_items)} module_item elements in full HTML")
                    print(f"[DEBUG] Found {len(test_links)} press-release links in full HTML")
                    
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
                    
                    # If this was the last headless mode and we have more retries, continue
                    if current_headless == headless_modes[-1] and attempt < max_retries - 1:
                        continue
                    elif attempt < max_retries - 1:
                        # Wait before next retry
                        wait_time = 2 ** attempt
                        print(f"Waiting {wait_time} seconds before retry...")
                        time.sleep(wait_time)
        
        # All retries failed
        raise Exception(f"Failed to fetch HTML after {max_retries} attempts: {str(last_exception)}")
    
    def extract_article_links(self, html: str) -> List[Dict]:
        """
        Extract press release article links using BeautifulSoup.
        Targets module_item elements with module_date-time, module_headline-link structure.
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with basic article info (link, title, date, tags)
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Find all module_item elements (the new structure)
        module_items = soup.find_all('div', class_='module_item')
        
        print(f"[DEBUG] Found {len(module_items)} module_item elements")
        
        # Process each module item
        for idx, item in enumerate(module_items):
            # Extract date from module_date-time
            date_text = "N/A"
            date_elem = item.find('div', class_='module_date-time')
            if date_elem:
                date_text = date_elem.get_text(strip=True)
                # Convert MM/DD/YYYY format to a more standard format if needed
                # Keep original format for now
            
            # Extract link and title from module_headline-link
            headline_link = item.find('a', class_='module_headline-link')
            if not headline_link:
                # Fallback: try to find any link in the headline div
                headline_div = item.find('div', class_='module_headline')
                if headline_div:
                    headline_link = headline_div.find('a', href=True)
            
            if not headline_link:
                continue
            
            href = headline_link.get('href', '')
            if not href:
                continue
            
            # Make URL absolute
            if href.startswith('/'):
                full_url = f"https://www.servicenow.com{href}"
            elif href.startswith('http'):
                full_url = href
            else:
                # Relative URL
                full_url = f"https://www.servicenow.com/{href.lstrip('/')}"
            
            # Avoid duplicates
            if full_url in seen_links:
                continue
            seen_links.add(full_url)
            
            # Extract title from link text
            title = headline_link.get_text(strip=True)
            if not title or len(title) < 5:
                # Fallback: try title attribute
                title = headline_link.get('title', 'N/A')
            
            # Extract category from module_category (usually empty, but check anyway)
            category = ""
            category_elem = item.find('div', class_='module_category')
            if category_elem:
                category = category_elem.get_text(strip=True)
            
            # Extract tags (use category if available, otherwise default to Press Release)
            tags = [category] if category else ['Press Release']
            
            articles.append({
                'link': full_url,
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
        
        # Try to find the module_container--content (new structure)
        module_content = soup.find('div', id='newsList') or soup.find('div', class_=lambda x: x and 'module_container--content' in str(x))
        
        if module_content:
            # Extract the module content
            content_str = str(module_content)
        else:
            # Fallback: look for module_item elements
            module_items = soup.find_all('div', class_='module_item')
            if module_items:
                # Extract all module items
                items_html = [str(item) for item in module_items]
                content_str = '\n'.join(items_html)
            else:
                # Fallback: look for press-related content
                content_selectors = [
                    ('div', {'class': lambda x: x and any(keyword in str(x).lower() for keyword in ['press', 'release', 'listing', 'module'])}),
                    ('main', {}),
                    ('article', {}),
                    ('section', {'class': lambda x: x and any(keyword in str(x).lower() for keyword in ['press', 'release'])}),
                ]
                
                main_content = None
                for tag, attrs in content_selectors:
                    main_content = soup.find(tag, attrs)
                    if main_content:
                        break
                
                if main_content:
                    content_str = str(main_content)
                else:
                    # Fallback: extract all links and their context
                    body = soup.find('body')
                    if body:
                        # Get all links with their surrounding context
                        links_html = []
                        for link in body.find_all('a', href=lambda x: x and ('press-releases' in x.lower() or 'press-room' in x.lower()))[:100]:
                            parent = link.find_parent(['div', 'li', 'article', 'section'])
                            if parent:
                                links_html.append(str(parent))
                        content_str = '\n'.join(links_html) if links_html else str(body)
                    else:
                        content_str = html
        
        # If we still don't have good content, try to get the entire body with all links
        if len(content_str) < 5000 or "incapsula" in content_str.lower() or "imperva" in content_str.lower() or "cloudflare" in content_str.lower():
            body = soup.find('body')
            if body:
                # Get ALL links and their full context - be more aggressive
                all_links_context = []
                seen_contexts = set()  # Avoid duplicates
                
                for link in body.find_all('a', href=True):
                    href = link.get('href', '').lower()
                    link_text = link.get_text(strip=True)
                    
                    # Look for press-releases or press-room links
                    if 'press-releases' in href or 'press-room' in href or (link_text and len(link_text) > 15):
                        # Get parent with more context
                        parent = link.find_parent(['div', 'li', 'article', 'section', 'tr', 'td', 'p'])
                        if parent:
                            # Get even more context - the parent's parent
                            grandparent = parent.find_parent(['div', 'section', 'ul', 'ol', 'table', 'main', 'article'])
                            if grandparent:
                                context_str = str(grandparent)
                                if context_str not in seen_contexts and len(context_str) > 50:
                                    all_links_context.append(context_str)
                                    seen_contexts.add(context_str)
                            else:
                                context_str = str(parent)
                                if context_str not in seen_contexts and len(context_str) > 50:
                                    all_links_context.append(context_str)
                                    seen_contexts.add(context_str)
                
                if all_links_context:
                    content_str = '\n'.join(all_links_context)
                    print(f"[DEBUG] Extracted {len(all_links_context)} link contexts")
                else:
                    # Last resort: get entire body
                    content_str = str(body)
        
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
        prompt = f"""You are analyzing HTML from ServiceNow press room page (https://www.servicenow.com/company/media/press-room.html). Your task is to extract ALL press release articles from the page.

CRITICAL INSTRUCTIONS:
1. Extract ALL press release articles you can find on the page - be extremely thorough
2. Each press release article should become a separate entry
3. Do NOT extract filter links, navigation links, or category links
4. Do NOT extract year filter links (those with #2025, #2024, etc.)
5. Extract ALL press release articles you can find (typically 25-100+ on a listing page)
6. Look for ALL module_item elements - don't miss any
7. If articles are in a list or grid, extract EVERY single one

What to look for:
- Module items with class "module_item"
- Each module_item contains:
  * A div with class "module_date-time" containing the date (format: MM/DD/YYYY, e.g., "11/18/2025")
  * A div with class "module_headline" containing a link with class "module_headline-link"
  * The link href points to press release pages (containing "/press-releases/details/" or similar)
  * The link text is the article title
- Dates in formats like "11/18/2025", "11/06/2025", "10/29/2025", etc. (MM/DD/YYYY)
- Skip any links with just # (year filter links)
- Skip the search form and filter elements

For EACH press release article you find, extract:
- title: The headline or title from the module_headline-link text (required)
- date: Publication date from module_date-time (format as YYYY-MM-DD if possible, otherwise keep original format like "11/18/2025", use "N/A" if not found)
- link: Full URL from module_headline-link href (if relative, prepend https://www.servicenow.com. Use "N/A" only if absolutely no link exists)
- tags: List of tags/categories (default to ["Press Release"] if none found)

EXAMPLES of what to extract:
- Press releases with dates, titles, and links from module_item elements
- All articles in the module_container--content container (id="newsList")
- Links containing "/press-releases/details/" in the href

EXAMPLES of what to SKIP:
- Year filter links (URLs with just #2025, #2024, etc.)
- Navigation links
- Search form elements
- "SHOW MORE" buttons
- Links to /press-room.html without a specific article path

Return a JSON array with ALL press release articles found.

JSON structure:
[
  {{
    "title": "First Article Title",
    "date": "2025-11-06",
    "link": "https://www.servicenow.com/company/media/press-room/article-1.html",
    "tags": ["Press Release"]
  }},
  {{
    "title": "Second Article Title",
    "date": "2025-10-15",
    "link": "https://www.servicenow.com/company/media/press-room/article-2.html",
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
        print("Fetching HTML from ServiceNow press room page...")
        html = self.fetch_html()
        
        if debug:
            with open("debug_servicenow_full_html.html", "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[DEBUG] Full HTML saved to debug_servicenow_full_html.html ({len(html)} chars)")
        
        # First, try to extract article links directly
        print("Extracting article links directly from HTML...")
        direct_articles = self.extract_article_links(html)
        print(f"[DEBUG] Found {len(direct_articles)} article links using BeautifulSoup")
        
        print("Extracting HTML structure for LLM analysis...")
        html_structure = self.extract_html_structure(html)
        
        if debug:
            with open("debug_servicenow_extracted_html.html", "w", encoding="utf-8") as f:
                f.write(html_structure)
            print(f"[DEBUG] Extracted HTML saved to debug_servicenow_extracted_html.html ({len(html_structure)} chars)")
        
        # Count potential articles in HTML
        soup = BeautifulSoup(html_structure, 'html.parser')
        press_links = soup.find_all('a', href=lambda x: x and 'press-room' in x.lower())
        print(f"[DEBUG] Found {len(press_links)} potential press-room links in extracted HTML")
        
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
                if '/press-room/' in llm_link or '/company/media/press-room/' in llm_link:
                    # Make sure it's not just the main page or a filter link
                    if not llm_link.endswith('/press-room.html') and '#' not in llm_link:
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
    
    def save_to_json(self, articles: List[Dict], filename: str = "servicenow_articles.json"):
        """
        Save results to JSON file.
        
        Args:
            articles: List of article dictionaries
            filename: Output filename
        """
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(articles, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to {filename}")


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
        print("  3. Provide it as a command line argument: python servicenow_scraper.py your_api_key")
        return 1
    
    try:
        scraper = ServiceNowScraper(api_key=api_key)
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

