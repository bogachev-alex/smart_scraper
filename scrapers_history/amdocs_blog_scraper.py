"""
LLM-based scraper for extracting structured data from Amdocs insights blog page.
Extracts: title, date, link
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


class AmdocsBlogScraper:
    """LLM-based scraper for Amdocs Insights blog page"""
    
    def __init__(self, api_key: str = None, base_url: str = "https://www.amdocs.com/insights"):
        """
        Initialize the scraper with OpenAI API key.
        
        Args:
            api_key: OpenAI API key. If not provided, will try to get from environment.
            base_url: Base URL for the Amdocs insights page
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key is required. Provide it as argument or set OPENAI_API_KEY environment variable.")
        
        self.client = OpenAI(api_key=self.api_key)
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
    
    def _fetch_html_selenium(self, headless: bool = False) -> str:
        """Fetch HTML using Selenium to get fully rendered page (without clicking buttons)"""
        driver = None
        try:
            # Use undetected-chromedriver which is designed to bypass bot detection
            print("Initializing browser (this may take a moment)...")
            options = uc.ChromeOptions()
            options.add_argument('--start-maximized')
            options.add_argument('--disable-blink-features=AutomationControlled')
            
            if headless:
                options.add_argument('--headless')  # Run in background only if requested
            else:
                print("[INFO] Browser will open in visible mode (you can see and interact with it)")
            
            driver = uc.Chrome(options=options, version_main=None)
            
            print("Loading page...")
            driver.get(self.base_url)
            
            # Wait for initial page load
            print("Waiting for page to load...")
            time.sleep(5)  # Initial wait for page to start loading
            
            # Check if we're on a security check page (more specific detection)
            page_source_lower = driver.page_source.lower()
            # Only check for actual blocking pages, not just mentions of security services
            blocking_indicators = [
                'please wait while we verify you are human',
                'checking your browser before accessing',
                'ddos protection by cloudflare',
                'access denied',
                'security check',
                'verify you are human',
                'just a moment',
                'please wait'
            ]
            
            # Check if we're actually blocked (not just that security services are mentioned)
            is_blocked = False
            for indicator in blocking_indicators:
                if indicator in page_source_lower:
                    # Also check if we have actual content - if we do, it's not blocked
                    articles = driver.find_elements(By.CSS_SELECTOR, "article[about]")
                    links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/insights/']")
                    if len(articles) == 0 and len(links) < 3 and len(page_source) < 30000:
                        is_blocked = True
                        break
            
            if is_blocked:
                if not headless:
                    print("\n[WARNING] Security check detected!")
                    print("The page requires manual verification.")
                    print("A browser window should be open - please complete the security check manually.")
                    print("Waiting for you to complete the check (press Enter when done)...")
                    
                    # Keep browser open for manual interaction
                    input("Press Enter after completing the security check in the browser window...")
                    time.sleep(2)
                else:
                    print("\n[WARNING] Security check detected in headless mode!")
                    print("Waiting for automatic security check to complete...")
                    time.sleep(10)  # Wait for automatic checks
            else:
                print("[OK] No security check detected, page loaded normally")
            
            # Wait for actual content to load with smarter checking
            print("Waiting for page content to load...")
            max_wait = 15  # Reduced to 15 seconds
            waited = 0
            content_found = False
            
            while waited < max_wait:
                page_source = driver.page_source
                
                # Check if we have actual content - look for article elements
                articles = driver.find_elements(By.CSS_SELECTOR, "article[about]")
                links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/insights/']")
                main_content = driver.find_elements(By.CSS_SELECTOR, "[class*='views-infinite-scroll-content-wrapper']")
                
                if len(articles) > 0:
                    print(f"[OK] Found {len(articles)} article elements - content loaded!")
                    content_found = True
                    break
                elif len(links) > 5:
                    print(f"[OK] Found {len(links)} insights links - content loaded!")
                    content_found = True
                    break
                elif len(main_content) > 0:
                    print(f"[OK] Found main content container - content loaded!")
                    content_found = True
                    break
                elif len(page_source) > 20000:
                    print(f"[OK] Page has substantial content ({len(page_source)} chars) - proceeding...")
                    content_found = True
                    break
                
                time.sleep(2)
                waited += 2
                if waited % 6 == 0:  # Print every 6 seconds
                    print(f"  Still waiting for content... ({waited}s)")
            
            if not content_found:
                print(f"[WARNING] Content check timeout after {max_wait}s, proceeding with current page state...")
            
            # Additional wait for JavaScript to fully render (reduced from 4 to 2 seconds)
            time.sleep(2)
            
            html = driver.page_source
            print(f"Retrieved HTML: {len(html)} characters")
            
            # Final check - verify we have content, not just a blocking page
            temp_soup = BeautifulSoup(html, 'html.parser')
            test_articles = temp_soup.find_all('article', about=True)
            
            if len(test_articles) == 0 and len(html) < 30000:
                # Might be blocked, but don't force manual input - just warn
                blocking_indicators = [
                    'please wait while we verify you are human',
                    'checking your browser before accessing',
                    'ddos protection by cloudflare',
                    'access denied'
                ]
                html_lower = html.lower()
                if any(indicator in html_lower for indicator in blocking_indicators):
                    if not headless:
                        print("[WARNING] Page might be blocked. Check the browser window.")
                        print("If you see a security check, complete it and press Enter...")
                        print("Otherwise, just press Enter to continue...")
                        input("Press Enter to continue...")
                        time.sleep(2)
                        html = driver.page_source
                        print(f"Retrieved HTML after check: {len(html)} characters")
                    else:
                        print("[WARNING] Page might be blocked in headless mode. Content may be limited.")
            
            if len(html) < 10000:
                print(f"[WARNING] Retrieved HTML seems too short ({len(html)} chars). The page might still be loading.")
                print("Trying to wait a bit longer...")
                time.sleep(3)  # Reduced from 5 to 3 seconds
                html = driver.page_source
                print(f"Retrieved HTML after additional wait: {len(html)} characters")
            
            # Try to find article links to verify we have content
            temp_soup = BeautifulSoup(html, 'html.parser')
            test_articles = temp_soup.find_all('article', about=True)
            print(f"[DEBUG] Found {len(test_articles)} article elements in full HTML")
            
            return html
        except Exception as e:
            raise Exception(f"Failed to fetch HTML with Selenium: {str(e)}")
        finally:
            if driver:
                try:
                    print("Closing browser...")
                    driver.quit()
                except (OSError, Exception):
                    # Ignore cleanup errors (common on Windows with undetected_chromedriver)
                    pass
    
    def fetch_html(self, use_selenium: bool = True, headless: bool = False) -> str:
        """
        Fetch HTML content from the Amdocs insights page.
        
        Args:
            use_selenium: If True, use Selenium (default). If False, use requests.
            headless: If True, run browser in headless mode (only if use_selenium is True)
        
        Returns:
            HTML content as string
        """
        if use_selenium:
            try:
                html = self._fetch_html_selenium(headless=headless)
                if html:
                    return html
            except Exception as e:
                print(f"Selenium failed: {e}")
                print("Falling back to requests...")
        
        # Fallback to requests
        try:
            response = self.session.get(self.base_url, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            print(f"Error fetching page: {e}")
            return None
    
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
        
        # First, try to find all article elements directly
        article_elements = soup.find_all('article', about=True)
        
        if article_elements:
            print(f"[DEBUG] Found {len(article_elements)} article elements directly")
            articles_html = [str(article) for article in article_elements]
            content_str = '\n'.join(articles_html)
        else:
            # Try to find the views-infinite-scroll-content-wrapper container
            content_wrapper = soup.find('div', class_=lambda x: x and 'views-infinite-scroll-content-wrapper' in str(x))
            
            if content_wrapper:
                # Extract all article elements HTML
                article_elements = content_wrapper.find_all('article', about=True)
                if article_elements:
                    print(f"[DEBUG] Found {len(article_elements)} article elements in content wrapper")
                    articles_html = [str(article) for article in article_elements]
                    content_str = '\n'.join(articles_html)
                else:
                    # If no articles, use the wrapper itself
                    content_str = str(content_wrapper)
            else:
                # Fallback: look for the main container
                main_container = soup.find('div', class_=lambda x: x and 'coh-style-view-pagination' in str(x))
                if main_container:
                    # Find all article elements within the container
                    article_elements = main_container.find_all('article', about=True)
                    if article_elements:
                        print(f"[DEBUG] Found {len(article_elements)} article elements in main container")
                        articles_html = [str(article) for article in article_elements]
                        content_str = '\n'.join(articles_html)
                    else:
                        content_str = str(main_container)
                else:
                    # Try to find any div with insights-related content
                    insights_containers = soup.find_all('div', class_=lambda x: x and ('insights' in str(x).lower() or 'article' in str(x).lower()))
                    if insights_containers:
                        # Get the largest container (likely the main content)
                        largest = max(insights_containers, key=lambda x: len(str(x)))
                        article_elements = largest.find_all('article', about=True)
                        if article_elements:
                            print(f"[DEBUG] Found {len(article_elements)} article elements in insights container")
                            articles_html = [str(article) for article in article_elements]
                            content_str = '\n'.join(articles_html)
                        else:
                            content_str = str(largest)
                    else:
                        # Last resort: get body (but limit size)
                        body = soup.find('body')
                        if body:
                            content_str = str(body)
                            # Limit to first 200KB to avoid token limits
                            if len(content_str) > 200000:
                                content_str = content_str[:200000] + "..."
                        else:
                            content_str = html[:200000] + "..." if len(html) > 200000 else html
        
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
            List of dictionaries with title, date, link
        """
        prompt = f"""You are analyzing HTML from Amdocs insights blog page (https://www.amdocs.com/insights). Your task is to extract ALL blog articles from the page.

CRITICAL INSTRUCTIONS:
1. Extract ALL blog articles you can find on the page - be extremely thorough
2. Each article should be in an <article> element with an "about" attribute containing the link
3. Each article should become a separate entry
4. Do NOT extract filter links, navigation links, or category links
5. Extract ALL articles you can find (typically 10-50+ on a listing page)
6. Look for ALL article elements - don't miss any
7. If articles are in a list or grid, extract EVERY single one

What to look for:
- Article elements with <article about="/insights/..."> containing the link path
- Titles in <h5> elements with class containing "coh-style-title" within the article
- Dates in <p> elements with class containing "coh-style-amd-author" and "coh-ce-cpt_author-b7b53071" within the article
- Dates in formats like "17 Nov 2025", "Nov 17, 2025", "2025-11-17", etc.
- Links can be extracted from the "about" attribute of the <article> tag, or from <a> href within the article

For EACH article you find, extract:
- title: The headline or title from h5 element with class containing "coh-style-title" (required - use link text if no explicit title)
- date: Publication date from p element with class containing "coh-style-amd-author" (format as YYYY-MM-DD if possible, otherwise keep original format like "17 Nov 2025", use "N/A" if not found)
- link: Full URL from article "about" attribute or from a href (if relative, prepend https://www.amdocs.com. Use "N/A" only if absolutely no link exists)

EXAMPLES of what to extract:
- Articles with dates, titles, and links from the insights page
- Blog posts, articles, whitepapers, case studies, videos, etc. from the insights listing

EXAMPLES of what to SKIP:
- Filter links
- Navigation links
- Category/tag links
- Links that don't point to actual articles
- "Load more" buttons

Return a JSON array with ALL articles found.

JSON structure:
[
  {{
    "title": "First Article Title",
    "date": "2025-11-17",
    "link": "https://www.amdocs.com/insights/article/article-1"
  }},
  {{
    "title": "Second Article Title",
    "date": "2025-11-14",
    "link": "https://www.amdocs.com/insights/video/video-1"
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
                    {"role": "system", "content": "You are a web scraping expert that extracts ALL articles from HTML. You MUST find every single article on the page. Return only valid JSON arrays with all articles found. Be extremely thorough - typical blog listing pages have 10-50+ articles."},
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
            print(f"Response was: {result_text[:500]}...")
            return []
        except Exception as e:
            raise Exception(f"LLM analysis failed: {str(e)}")
    
    def scrape(self, debug: bool = False, headless: bool = False) -> List[Dict]:
        """
        Main scraping method using LLM-based extraction.
        
        Args:
            debug: If True, save extracted HTML to file for debugging
            headless: If True, run browser in headless mode
        
        Returns:
            List of article dictionaries
        """
        print(f"Fetching HTML from {self.base_url}...")
        html = self.fetch_html(headless=headless)
        
        if not html:
            print("Failed to fetch HTML")
            return []
        
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
            debug_filepath = debug_dir / "debug_amdocs_blog_full_html.html"
            with open(debug_filepath, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[DEBUG] Full HTML saved to {debug_filepath} ({len(html)} chars)")
        
        print("Extracting HTML structure for LLM analysis...")
        html_structure = self.extract_html_structure(html)
        
        if debug:
            script_dir = Path(__file__).parent
            if script_dir.name == "scrapers":
                project_root = script_dir.parent
            else:
                project_root = script_dir
            
            debug_dir = project_root / "debug"
            debug_dir.mkdir(exist_ok=True)
            
            debug_filepath = debug_dir / "debug_amdocs_blog_extracted_html.html"
            with open(debug_filepath, "w", encoding="utf-8") as f:
                f.write(html_structure)
            print(f"[DEBUG] Extracted HTML saved to {debug_filepath} ({len(html_structure)} chars)")
        
        # Count potential articles in HTML
        soup = BeautifulSoup(html_structure, 'html.parser')
        article_elements = soup.find_all('article', about=True)
        print(f"[DEBUG] Found {len(article_elements)} article elements in extracted HTML")
        
        print("Analyzing content with LLM to extract articles...")
        articles = self.analyze_with_llm(html_structure)
        print(f"Found {len(articles)} articles")
        
        return articles
    
    def save_to_json(self, articles: List[Dict], filename: str = 'amdocs_blog_articles.json'):
        """Save articles to JSON file in the data/ folder"""
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
        print(f"Saved {len(articles)} articles to {filepath}")


def main():
    """Main function to run the scraper"""
    import sys
    
    # Check for flags
    debug = "--debug" in sys.argv or "-d" in sys.argv
    headless = "--headless" in sys.argv or "-h" in sys.argv
    
    # Filter out flags from arguments when looking for API key
    args_without_flags = [arg for arg in sys.argv[1:] if arg not in ["--debug", "-d", "--headless", "-h"]]
    
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
        print("  3. Provide it as a command line argument: python amdocs_blog_scraper.py your_api_key")
        return 1
    
    try:
        scraper = AmdocsBlogScraper(api_key=api_key)
        articles = scraper.scrape(debug=debug, headless=headless)
        
        if articles:
            # Print first few articles as preview
            print("\n--- Preview of scraped articles ---")
            for i, article in enumerate(articles[:5], 1):
                print(f"\n{i}. {article['title']}")
                print(f"   Date: {article['date']}")
                print(f"   Link: {article['link']}")
            
            # Save to file
            scraper.save_to_json(articles)
        else:
            print("No articles found")
        
        return 0
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
