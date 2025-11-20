"""
Scraper for extracting structured data from Ericsson blog page.
Extracts: title, date, link
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

# Load environment variables
load_dotenv()

class EricssonBlogScraper:
    def __init__(self):
        """Initialize the scraper."""
        self.url = "https://www.ericsson.com/en/blog?locs=68304"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def fetch_html(self, use_selenium: bool = True) -> str:
        """
        Fetch HTML content from the Ericsson blog page.
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
            print("Initializing browser (this may take a moment)...")
            options = uc.ChromeOptions()
            options.add_argument('--start-maximized')
            options.add_argument('--disable-blink-features=AutomationControlled')
            
            driver = uc.Chrome(options=options, version_main=None)
            
            print("Loading page...")
            driver.get(self.url)
            
            # Wait for page content to load
            print("Waiting for page content to load...")
            max_wait = 30
            waited = 0
            while waited < max_wait:
                page_source = driver.page_source
                
                # Check if we have actual content - look for filtered-blogs div
                filtered_blogs = driver.find_elements(By.CSS_SELECTOR, ".filtered-blogs")
                cards = driver.find_elements(By.CSS_SELECTOR, ".card")
                
                if len(filtered_blogs) > 0 or len(cards) > 0 or len(page_source) > 20000:
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
            
            # Verify we have content
            temp_soup = BeautifulSoup(html, 'html.parser')
            test_cards = temp_soup.find_all('div', class_='card')
            print(f"[DEBUG] Found {len(test_cards)} card elements in full HTML")
            
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
    
    def extract_articles(self, html: str) -> List[Dict]:
        """
        Extract article data from HTML.
        Targets the structure: div.filtered-blogs > div.content-list.cards > div.card
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with title, date, link
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Find the main container
        filtered_blogs = soup.find('div', class_='filtered-blogs')
        if not filtered_blogs:
            print("[WARNING] Could not find div.filtered-blogs container")
            # Fallback: try to find cards directly
            cards = soup.find_all('div', class_='card')
        else:
            # Find the content-list cards container
            content_list = filtered_blogs.find('div', class_='content-list')
            if content_list:
                cards = content_list.find_all('div', class_='card')
            else:
                # Fallback: find cards within filtered-blogs
                cards = filtered_blogs.find_all('div', class_='card')
        
        print(f"[DEBUG] Found {len(cards)} card elements")
        
        # Process each card
        for idx, card in enumerate(cards):
            try:
                # Extract title from h4.card-title > a
                title = "N/A"
                title_elem = card.find('h4', class_='card-title')
                if title_elem:
                    title_link = title_elem.find('a')
                    if title_link:
                        title = title_link.get_text(strip=True)
                        # Extract link from the same <a> tag
                        href = title_link.get('href', '')
                    else:
                        href = ""
                else:
                    href = ""
                
                # If no title link found, try to find any link in the card
                if not href:
                    link_elem = card.find('a', href=True)
                    if link_elem:
                        href = link_elem.get('href', '')
                        # If we still don't have a title, try to get it from this link
                        if title == "N/A":
                            title = link_elem.get_text(strip=True)
                
                if not href:
                    continue
                
                # Make URL absolute
                if href.startswith('/'):
                    full_url = f"https://www.ericsson.com{href}"
                elif href.startswith('http'):
                    full_url = href
                else:
                    continue
                
                # Avoid duplicates
                if full_url in seen_links:
                    continue
                seen_links.add(full_url)
                
                # Extract date from p.card-description.date-author > span.date
                date_text = "N/A"
                date_author = card.find('p', class_='card-description')
                if date_author:
                    date_span = date_author.find('span', class_='date')
                    if date_span:
                        date_raw = date_span.get_text(strip=True)
                        # Parse date like "Nov 14, 2025" or "Nov 14 2025"
                        date_patterns = [
                            r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})',
                            r'(\d{4})-(\d{2})-(\d{2})',
                        ]
                        for pattern in date_patterns:
                            match = re.search(pattern, date_raw, re.IGNORECASE)
                            if match:
                                if len(match.groups()) == 3:
                                    if match.group(1).isdigit():
                                        # YYYY-MM-DD format
                                        date_text = date_raw
                                    else:
                                        # Month Day, Year format
                                        month = match.group(1)
                                        day = match.group(2)
                                        year = match.group(3)
                                        month_map = {
                                            'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
                                            'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
                                            'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12',
                                            'January': '01', 'February': '02', 'March': '03', 'April': '04',
                                            'May': '05', 'June': '06', 'July': '07', 'August': '08',
                                            'September': '09', 'October': '10', 'November': '11', 'December': '12'
                                        }
                                        month_num = month_map.get(month[:3], month)
                                        if month_num.isdigit():
                                            day_padded = day.zfill(2)
                                            date_text = f"{year}-{month_num}-{day_padded}"
                                        else:
                                            date_text = date_raw
                                break
                        if date_text == "N/A":
                            date_text = date_raw
                
                articles.append({
                    'title': title,
                    'date': date_text,
                    'link': full_url
                })
                
                print(f"[DEBUG] Extracted article {idx+1}: {title[:50]}...")
                
            except Exception as e:
                print(f"[WARNING] Error processing card {idx+1}: {e}")
                continue
        
        return articles
    
    def scrape(self, debug: bool = False) -> List[Dict]:
        """
        Main method to scrape the page.
        
        Args:
            debug: If True, save extracted HTML to file for debugging
        
        Returns:
            List of structured article data
        """
        print("Fetching HTML from Ericsson blog page...")
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
            debug_filepath = debug_dir / "debug_ericsson_blog_full_html.html"
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
    
    def save_to_json(self, articles: List[Dict], filename: str = "ericsson_blog_articles.json"):
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
        scraper = EricssonBlogScraper()
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

