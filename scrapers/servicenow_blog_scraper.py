"""
Scraper for extracting structured data from ServiceNow blog product-news category.
Extracts: title, date, link
Only collects recent articles visible on the initial page load (does not click "Load More").
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import time
import re
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

class ServiceNowBlogScraper:
    def __init__(self):
        """
        Initialize the scraper.
        """
        self.url = "https://www.servicenow.com/blogs/category/product-news"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def fetch_html(self, use_selenium: bool = True) -> str:
        """
        Fetch HTML content from the ServiceNow blog page.
        Uses Selenium to handle JavaScript-rendered content.
        
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
        """Fetch HTML using undetected-chromedriver to handle JavaScript rendering."""
        driver = None
        try:
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
            time.sleep(5)  # Initial wait for page load
            
            # Wait for blog list to appear
            max_wait = 30
            waited = 0
            while waited < max_wait:
                page_source = driver.page_source
                
                # Check if we have the blog list content
                blog_list = driver.find_elements(By.CSS_SELECTOR, ".blog-list-wrapper, .blog-list, .card")
                links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/blogs/']")
                
                if len(blog_list) > 0 or len(links) > 5 or len(page_source) > 20000:
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
            
            # Verify we have content
            temp_soup = BeautifulSoup(html, 'html.parser')
            test_cards = temp_soup.find_all('div', class_='card')
            print(f"[DEBUG] Found {len(test_cards)} card elements in full HTML")
            
            return html
        except Exception as e:
            raise Exception(f"Failed to fetch HTML with Selenium: {str(e)}")
        finally:
            if driver:
                print("Closing browser...")
                try:
                    # Suppress stderr during cleanup to avoid harmless exception messages
                    with redirect_stderr(StringIO()):
                        driver.quit()
                        time.sleep(0.3)  # Give time for cleanup
                except Exception:
                    # Ignore cleanup errors - driver may already be closed
                    pass
    
    def extract_articles(self, html: str) -> List[Dict]:
        """
        Extract blog articles from HTML.
        Targets the blog-list structure with card elements.
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with title, date, link
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Find the blog list wrapper
        blog_list_wrapper = soup.find('div', class_='blog-list-wrapper')
        if not blog_list_wrapper:
            # Fallback: find blog-list directly
            blog_list_wrapper = soup.find('div', class_='blog-list')
        
        if blog_list_wrapper:
            # Find all card elements within the blog list
            cards = blog_list_wrapper.find_all('div', class_='card')
            print(f"[DEBUG] Found {len(cards)} card elements in blog list")
        else:
            # Fallback: find all cards on the page
            cards = soup.find_all('div', class_='card')
            print(f"[DEBUG] Found {len(cards)} card elements (fallback)")
        
        # Process each card
        for idx, card in enumerate(cards):
            # Find the link - look for href in card-thumbnail or card-text
            link_elem = None
            
            # Try card-thumbnail link first
            card_thumbnail = card.find('div', class_='card-thumbnail')
            if card_thumbnail:
                link_elem = card_thumbnail.find('a', href=True)
            
            # If not found, try card-text link
            if not link_elem:
                card_text = card.find('div', class_='card-text')
                if card_text:
                    link_elem = card_text.find('a', href=True)
            
            # If still not found, try any link in the card
            if not link_elem:
                link_elem = card.find('a', href=True)
            
            if not link_elem:
                continue
            
            href = link_elem.get('href', '')
            if not href:
                continue
            
            # Make URL absolute
            if href.startswith('/'):
                full_url = f"https://www.servicenow.com{href}"
            elif href.startswith('http'):
                full_url = href
            else:
                continue
            
            # Avoid duplicates
            if full_url in seen_links:
                continue
            seen_links.add(full_url)
            
            # Extract title from h5 in card-text
            title = "N/A"
            card_text = card.find('div', class_='card-text')
            if card_text:
                title_elem = card_text.find('h5')
                if title_elem:
                    title = title_elem.get_text(strip=True)
            
            # If no title found, try link text
            if title == "N/A" or len(title) < 5:
                link_text = link_elem.get_text(strip=True)
                if link_text and len(link_text) > 5:
                    title = link_text
                else:
                    # Try title attribute
                    title_attr = link_elem.get('title', '')
                    if title_attr and len(title_attr) > 5:
                        title = title_attr
                    else:
                        # Try alt attribute from image
                        img = card.find('img')
                        if img:
                            alt_text = img.get('alt', '')
                            if alt_text and len(alt_text) > 5:
                                title = alt_text
            
            # Extract date from card-date span
            date_text = "N/A"
            card_date = card.find('span', class_='card-date')
            if card_date:
                date_text = card_date.get_text(strip=True)
            
            # If no date found, try to find date patterns in card text
            if date_text == "N/A" or len(date_text) < 5:
                card_text_content = card.get_text()
                date_patterns = [
                    r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',
                    r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b',
                    r'\b\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b',
                    r'\b\d{4}-\d{2}-\d{2}\b',
                    r'\b\d{1,2}/\d{1,2}/\d{4}\b',
                ]
                for pattern in date_patterns:
                    match = re.search(pattern, card_text_content, re.IGNORECASE)
                    if match:
                        date_text = match.group(0)
                        break
            
            articles.append({
                'title': title,
                'date': date_text,
                'link': full_url
            })
            
            print(f"[DEBUG] Extracted article {idx+1}: {title[:50]}...")
        
        return articles
    
    def scrape(self, debug: bool = False) -> List[Dict]:
        """
        Main method to scrape the blog page.
        
        Args:
            debug: If True, save extracted HTML to file for debugging
        
        Returns:
            List of structured article data
        """
        print("Fetching HTML from ServiceNow blog page...")
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
            debug_filepath = debug_dir / "debug_servicenow_blog_full_html.html"
            with open(debug_filepath, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[DEBUG] Full HTML saved to {debug_filepath} ({len(html)} chars)")

        print("Extracting articles from HTML...")
        articles = self.extract_articles(html)
        print(f"Found {len(articles)} articles")
        
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
    
    def save_to_json(self, articles: List[Dict], filename: str = "servicenow_blog_articles.json"):
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
    
    # Check for debug flag
    debug = "--debug" in sys.argv or "-d" in sys.argv
    
    try:
        scraper = ServiceNowBlogScraper()
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

