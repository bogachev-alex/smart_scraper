"""
LLM-based scraper for extracting structured data from HPE newsroom page.
Extracts: title, date, link
Renamed from hpe_scraper.py to hpe_news_scraper.py
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


class HPENewsScraper:
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
        self.url = "https://www.hpe.com/us/en/newsroom/press-hub.html"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def fetch_html(self, use_selenium: bool = True) -> str:
        """
        Fetch HTML content from the HPE newsroom page.
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
        
        Args:
            max_retries: Maximum number of retry attempts
        """
        driver = None
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    wait_time = 2 ** attempt
                    print(f"Retry attempt {attempt + 1}/{max_retries}...")
                    time.sleep(wait_time)
                    print(f"Waiting {wait_time} seconds before retry...")
                
                print("Initializing browser...")
                options = uc.ChromeOptions()
                options.add_argument('--start-maximized')
                options.add_argument('--disable-blink-features=AutomationControlled')
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
                
                driver = uc.Chrome(options=options, version_main=None)
                
                print("Loading page...")
                driver.get(self.url)
                
                # Wait for content to load
                print("Waiting for page content to load...")
                max_wait = 30
                waited = 0
                while waited < max_wait:
                    page_source = driver.page_source
                    
                    # Check if we have actual content - look for items-wrapper or uc-card elements
                    items_wrapper = driver.find_elements(By.CSS_SELECTOR, ".items-wrapper, .items, .uc-card")
                    links = driver.find_elements(By.CSS_SELECTOR, "a[href*='newsroom'], a[href*='press'], a[href*='blog']")
                    main_content = driver.find_elements(By.TAG_NAME, "main")
                    
                    if len(items_wrapper) > 0 or len(links) > 5 or len(main_content) > 0 or len(page_source) > 20000:
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
                
                if len(html) < 10000:
                    print(f"[WARNING] Retrieved HTML seems too short ({len(html)} chars). The page might still be loading.")
                    print("Trying to wait a bit longer...")
                    time.sleep(5)
                    html = driver.page_source
                    print(f"Retrieved HTML after additional wait: {len(html)} characters")
                
                # Try to find article links to verify we have content
                temp_soup = BeautifulSoup(html, 'html.parser')
                test_links = temp_soup.find_all('a', href=lambda x: x and any(kw in x.lower() for kw in ['newsroom', 'press', 'blog']))
                print(f"[DEBUG] Found {len(test_links)} newsroom/press/blog links in full HTML")
                
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
                    continue
        
        # All retries failed
        raise Exception(f"Failed to fetch HTML after {max_retries} attempts: {str(last_exception)}")
    
    def extract_article_links(self, html: str) -> List[Dict]:
        """
        Extract article links using BeautifulSoup.
        Targets the items-wrapper > items > item structure with uc-card elements.
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with basic article info (link, title, date)
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Find the items-wrapper container
        items_wrapper = soup.find('div', class_='items-wrapper')
        if not items_wrapper:
            # Fallback: look for items container directly
            items_wrapper = soup.find('div', class_='items')
        
        if items_wrapper:
            # Find all item divs within the items container
            items = items_wrapper.find_all('div', class_='item')
            print(f"[DEBUG] Found {len(items)} item containers")
        else:
            # Fallback: find all uc-card elements
            items = soup.find_all('div', class_=lambda x: x and 'uc-card' in str(x))
            print(f"[DEBUG] Found {len(items)} uc-card containers (fallback)")
        
        # Process each item
        for idx, item in enumerate(items[:200]):  # Limit to first 200 to avoid duplicates
            # Find the uc-card-wrapper link
            card_link = item.find('a', class_='uc-card-wrapper')
            if not card_link:
                # Fallback: find any link with href containing newsroom
                card_link = item.find('a', href=lambda x: x and 'newsroom' in x.lower())
            
            if not card_link:
                continue
            
            href = card_link.get('href', '')
            if not href:
                continue
            
            # Make URL absolute
            if href.startswith('/'):
                full_url = f"https://www.hpe.com{href}"
            elif href.startswith('http'):
                full_url = href
            else:
                continue
            
            # Avoid duplicates
            if full_url in seen_links:
                continue
            seen_links.add(full_url)
            
            # Extract title from uc-card-title
            title = "N/A"
            title_elem = item.find('h5', class_='uc-card-title')
            if title_elem:
                title = title_elem.get_text(strip=True)
            
            # If no title found, try link text or title attribute
            if title == "N/A" or len(title) < 10:
                link_text = card_link.get_text(strip=True)
                if link_text and len(link_text) > 10:
                    title = link_text
                else:
                    title_attr = card_link.get('title', '')
                    if title_attr and len(title_attr) > 10:
                        title = title_attr
            
            # Extract date from uc-card-label
            date_text = "N/A"
            label_elem = item.find('div', class_='uc-card-label')
            if label_elem:
                # Look for date span - usually first span
                date_spans = label_elem.find_all('span')
                if date_spans:
                    # First span usually contains the date
                    date_text = date_spans[0].get_text(strip=True)
                    # Clean up date text (remove " | " separator if present)
                    if ' | ' in date_text:
                        date_text = date_text.split(' | ')[0]
            
            # If no date found in label, try to find date patterns in item text
            if date_text == "N/A" or len(date_text) < 5:
                item_text = item.get_text()
                date_patterns = [
                    r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b',
                    r'\b\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b',
                    r'\b\d{4}-\d{2}-\d{2}\b',
                    r'\b\d{1,2}/\d{1,2}/\d{4}\b',
                ]
                for pattern in date_patterns:
                    match = re.search(pattern, item_text, re.IGNORECASE)
                    if match:
                        date_text = match.group(0)
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
        
        # Try to find the items-wrapper container first
        items_wrapper = soup.find('div', class_='items-wrapper')
        if items_wrapper:
            content_str = str(items_wrapper)
        else:
            # Fallback: look for items container
            items_container = soup.find('div', class_='items')
            if items_container:
                content_str = str(items_container)
            else:
                # Try multiple strategies to find content
                content_selectors = [
                    ('main', {}),
                    ('div', {'class': lambda x: x and any(keyword in str(x).lower() for keyword in ['news', 'press', 'article', 'content', 'listing', 'newsroom', 'items'])}),
                    ('section', {'class': lambda x: x and any(keyword in str(x).lower() for keyword in ['news', 'press', 'article', 'newsroom'])}),
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
                        for link in body.find_all('a', href=True)[:50]:  # Limit to 50 links
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
                    
                    # Look for newsroom/press/blog/article links
                    if any(keyword in href for keyword in ['newsroom', 'press', 'blog', 'article', '/20']) or \
                       (link_text and len(link_text) > 15):  # Long link text might be article titles
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
        prompt = f"""You are analyzing HTML from HPE newsroom page (https://www.hpe.com/us/en/newsroom/press-hub.html). Your task is to extract ALL news articles from the page.

CRITICAL INSTRUCTIONS:
1. Extract ALL news articles you can find on the page - be extremely thorough
2. Each news article should become a separate entry
3. Do NOT extract filter links, navigation links, or category links
4. Extract ALL news articles you can find - there should be MANY articles (typically 20-100+ on a listing page)
5. Look for ALL article cards, containers, and links - don't miss any
6. If articles are in a list or grid, extract EVERY single one

What to look for:
- Article cards/containers with class "uc-card" or "item" within "items-wrapper" or "items" containers
- Links with class "uc-card-wrapper" that point to actual article pages (href containing "/newsroom/" with descriptive path)
- Titles/headlines in h5 elements with class "uc-card-title" within article containers
- Dates in div elements with class "uc-card-label" - look for the first span which contains the date (format like "Nov 10, 2025")
- Dates may be in formats like "Nov 10, 2025", "10 Nov 2025", "2025-11-10", "11/10/2025", etc.

For EACH news article you find, extract:
- title: The headline or title from h5.uc-card-title (required - use link text if no explicit title)
- date: Publication date from the first span in div.uc-card-label (format as YYYY-MM-DD if possible, otherwise keep original format like "Nov 10, 2025", use "N/A" if not found)
- link: Full URL from a.uc-card-wrapper href (if relative, prepend https://www.hpe.com. Use "N/A" only if absolutely no link exists)

EXAMPLES of what to extract:
- News articles with dates, titles, and links from the press hub
- Articles from the newsroom with full URLs

EXAMPLES of what to SKIP:
- Filter links
- Navigation links
- Category/tag links
- Links that just say "Press Hub" or "Newsroom" (those are navigation, not articles)

Return a JSON array with ALL news articles found.

JSON structure:
[
  {{
    "title": "First Article Title",
    "date": "2025-11-10",
    "link": "https://www.hpe.com/us/en/newsroom/press-release/2025/11/article-1.html"
  }},
  {{
    "title": "Second Article Title",
    "date": "2025-11-03",
    "link": "https://www.hpe.com/us/en/newsroom/blog-post/2025/11/article-2.html"
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
                    {"role": "system", "content": "You are a web scraping expert that extracts ALL articles from HTML. You MUST find every single news article on the page. Return only valid JSON arrays with all articles found. Be extremely thorough - typical news listing pages have 10-50+ articles."},
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
        print("Fetching HTML from HPE newsroom page...")
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
            debug_filepath = debug_dir / "debug_hpe_news_full_html.html"
            with open(debug_filepath, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[DEBUG] Full HTML saved to debug_hpe_news_full_html.html ({len(html)} chars)")
        
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
            debug_filepath = debug_dir / "debug_hpe_news_extracted_html.html"
            with open(debug_filepath, "w", encoding="utf-8") as f:
                f.write(html_structure)
            print(f"[DEBUG] Extracted HTML saved to debug_hpe_news_extracted_html.html ({len(html_structure)} chars)")
        
        # Count potential articles in HTML
        soup = BeautifulSoup(html_structure, 'html.parser')
        news_links = soup.find_all('a', href=lambda x: x and any(kw in x.lower() for kw in ['newsroom', 'press', 'blog']))
        print(f"[DEBUG] Found {len(news_links)} potential newsroom/press/blog links in extracted HTML")
        
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
            if llm_link not in direct_links:
                # Check if it's a valid article link
                is_valid = False
                if '/newsroom/' in llm_link or '/press-release/' in llm_link or '/blog-post/' in llm_link:
                    # Make sure it's not just a category page
                    if not llm_link.endswith('/newsroom') and not llm_link.endswith('/press-hub.html'):
                        is_valid = True
                
                if is_valid:
                    articles.append(llm_art)
        
        print(f"Final result: {len(articles)} news articles found")
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
    
    def save_to_json(self, articles: List[Dict], filename: str = "hpe_news.json"):
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
        print("  3. Provide it as a command line argument: python hpe_news_scraper.py your_api_key")
        return 1
    
    try:
        scraper = HPENewsScraper(api_key=api_key)
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

