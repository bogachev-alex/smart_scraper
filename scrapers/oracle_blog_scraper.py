"""
Scraper for extracting structured data from Oracle blog page.
Extracts: title, date, link
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import sys
import time
import re
from typing import List, Dict
from pathlib import Path
from contextlib import redirect_stderr
from io import StringIO
from dotenv import load_dotenv
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

# Load environment variables
load_dotenv()

class OracleBlogScraper:
    def __init__(self):
        """
        Initialize the scraper.
        """
        self.url = "https://blogs.oracle.com/"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def fetch_html(self, use_selenium: bool = True) -> str:
        """
        Fetch HTML content from the Oracle blog page.
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
            options = uc.ChromeOptions()
            options.add_argument('--start-maximized')
            options.add_argument('--disable-blink-features=AutomationControlled')
            
            driver = uc.Chrome(options=options, version_main=None)
            
            print("Loading page...")
            driver.get(self.url)
            
            # Wait for page to load
            print("Waiting for page content to load...")
            time.sleep(5)
            
            # Wait for blog sections to load
            max_wait = 30
            waited = 0
            while waited < max_wait:
                page_source = driver.page_source
                
                # Check if we have blog content - look for blogtile or cscroll-items
                blog_tiles = driver.find_elements(By.CSS_SELECTOR, ".blogtile, .cscroll-items")
                sections = driver.find_elements(By.CSS_SELECTOR, "section.rc90, section[class*='rc90']")
                
                if len(blog_tiles) > 0 or len(sections) > 0 or len(page_source) > 50000:
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
            
            if len(html) < 10000:
                print(f"[WARNING] Retrieved HTML seems too short ({len(html)} chars). The page might still be loading.")
                print("Trying to wait a bit longer...")
                time.sleep(5)
                html = driver.page_source
                print(f"Retrieved HTML after additional wait: {len(html)} characters")
            
            # Try to find blog posts to verify we have content
            temp_soup = BeautifulSoup(html, 'html.parser')
            test_links = temp_soup.find_all('div', class_='blogtile')
            print(f"[DEBUG] Found {len(test_links)} blog tiles in full HTML")
            
            return html
        except Exception as e:
            raise Exception(f"Failed to fetch HTML with Selenium: {str(e)}")
        finally:
            if driver:
                try:
                    print("Closing browser...")
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
        Targets blogtile elements within sections with class rc90.
        
        Args:
            html: Raw HTML content
        
        Returns:
            List of dictionaries with title and link
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Find all blog sections (rc90 class)
        blog_sections = soup.find_all('section', class_=lambda x: x and 'rc90' in str(x))
        
        print(f"[DEBUG] Found {len(blog_sections)} blog sections")
        
        # Process each section
        for section in blog_sections:
            # Find all blog tiles within this section
            # Blog tiles can be in ul.cscroll-items > li > div.cscroll-item-w1 > div.blogtile
            # Or directly in the section
            blog_tiles = section.find_all('div', class_='blogtile')
            
            for tile in blog_tiles:
                # Find the blogtile-w2 div which contains the title and link
                tile_w2 = tile.find('div', class_='blogtile-w2')
                if not tile_w2:
                    continue
                
                # Find the h3 > a element which contains title and link
                h3 = tile_w2.find('h3')
                if not h3:
                    continue
                
                a = h3.find('a', href=True)
                if not a:
                    continue
                
                # Extract title and link
                title = a.get_text(strip=True)
                link = a.get('href', '')
                
                # Skip if no valid link or title
                if not link or not title or len(title) < 5:
                    continue
                
                # Make URL absolute if relative
                if link.startswith('/'):
                    link = f"https://blogs.oracle.com{link}"
                elif not link.startswith('http'):
                    link = f"https://blogs.oracle.com/{link.lstrip('/')}"
                
                # Extract date - look for date patterns in tile text
                date_text = "N/A"
                tile_text = tile.get_text()
                date_patterns = [
                    r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',
                    r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b',
                    r'\b\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b',
                    r'\b\d{4}-\d{2}-\d{2}\b',
                    r'\b\d{1,2}/\d{1,2}/\d{4}\b',
                ]
                for pattern in date_patterns:
                    match = re.search(pattern, tile_text, re.IGNORECASE)
                    if match:
                        date_text = match.group(0)
                        break
                
                # Avoid duplicates
                if link in seen_links:
                    continue
                seen_links.add(link)
                
                articles.append({
                    'title': title,
                    'date': date_text,
                    'link': link
                })
        
        print(f"[DEBUG] Extracted {len(articles)} unique articles")
        
        return articles
    
    def scrape(self, debug: bool = False) -> List[Dict]:
        """
        Main method to scrape the page.
        
        Args:
            debug: If True, save extracted HTML to file for debugging
        
        Returns:
            List of structured article data with title and link
        """
        print("Fetching HTML from Oracle blog page...")
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
            debug_filepath = debug_dir / "debug_oracle_blog_full_html.html"
            with open(debug_filepath, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[DEBUG] Full HTML saved to {debug_filepath} ({len(html)} chars)")

        print("Extracting article links directly from HTML...")
        articles = self.extract_article_links(html)
        print(f"[DEBUG] Found {len(articles)} articles using BeautifulSoup")
        
        print(f"Final result: {len(articles)} blog articles found")
        
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
            print(f"  Date:  {article.get('date', 'N/A')}")
            print(f"  Link:  {article['link']}")
            print("-" * 80)
    
    def save_to_json(self, articles: List[Dict], filename: str = "oracle_blog_articles.json"):
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
    import gc
    
    # Check for debug flag
    debug = "--debug" in sys.argv or "-d" in sys.argv
    
    try:
        scraper = OracleBlogScraper()
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

