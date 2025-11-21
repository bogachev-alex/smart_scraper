"""
Scraper for extracting structured data from Analysys Mason Knowledge Centre.
Extracts: title, date, link, description, content_type, image_url, access_type
Scrapes from: https://www.analysysmason.com/knowledge-centre/?ac=DontRequiresSubscription&author=&page=1
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import time
import re
from typing import List, Dict, Optional
from pathlib import Path
from contextlib import redirect_stderr
from io import StringIO
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class AnalysysMasonScraper:
    def __init__(self, max_pages: int = 8):
        """
        Initialize the scraper.
        
        Args:
            max_pages: Maximum number of pages to scrape (default: 8)
        """
        self.base_url = "https://www.analysysmason.com/knowledge-centre/"
        self.max_pages = max_pages
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def _get_page_url(self, page: int) -> str:
        """
        Generate URL for a specific page.
        
        Args:
            page: Page number (1-indexed)
            
        Returns:
            Full URL for the page
        """
        return f"{self.base_url}?ac=DontRequiresSubscription&author=&page={page}"
    
    def fetch_html(self, url: str, use_selenium: bool = True) -> str:
        """
        Fetch HTML content from the Analysys Mason Knowledge Centre page.
        Uses Selenium to handle JavaScript-rendered content.
        
        Args:
            url: URL to fetch
            use_selenium: If True, use Selenium (default). If False, use requests.
        
        Returns:
            HTML content as string
        """
        if use_selenium:
            return self._fetch_html_selenium(url)
        else:
            return self._fetch_html_requests(url)
    
    def _fetch_html_requests(self, url: str) -> str:
        """Fetch HTML using requests library."""
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            raise Exception(f"Failed to fetch HTML: {str(e)}")
    
    def _fetch_html_selenium(self, url: str) -> str:
        """
        Fetch HTML using undetected-chromedriver to handle JavaScript rendering.
        
        Args:
            url: URL to fetch
            
        Returns:
            HTML content as string
        """
        driver = None
        try:
            print(f"Initializing browser (this may take a moment)...")
            options = uc.ChromeOptions()
            options.add_argument('--start-maximized')
            options.add_argument('--disable-blink-features=AutomationControlled')
            
            driver = uc.Chrome(options=options, version_main=None)
            
            print(f"Loading page: {url}")
            driver.get(url)
            
            # Wait for page content to load
            print("Waiting for page content to load...")
            max_wait = 30
            waited = 0
            while waited < max_wait:
                page_source = driver.page_source
                
                # Check if we have actual content - look for results__item elements
                results_items = driver.find_elements(By.CSS_SELECTOR, ".results__item")
                results_wrapper = driver.find_elements(By.CSS_SELECTOR, "#ResultListWrapper")
                
                if len(results_items) > 0 or len(results_wrapper) > 0 or len(page_source) > 50000:
                    print(f"[OK] Content loaded successfully! ({len(results_items)} articles found)")
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
            
            return html
        except Exception as e:
            raise Exception(f"Failed to fetch HTML with Selenium: {str(e)}")
        finally:
            if driver:
                try:
                    print("Closing browser...")
                    with redirect_stderr(StringIO()):
                        driver.quit()
                        time.sleep(1)
                except Exception:
                    pass
    
    def extract_articles(self, html: str) -> List[Dict]:
        """
        Extract articles from HTML.
        Targets results__item elements within the results container.
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with title, date, link, description, content_type, image_url, access_type
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Find all result items
        result_items = soup.find_all('div', class_='results__item')
        
        print(f"[DEBUG] Found {len(result_items)} result item(s)")
        
        for idx, item in enumerate(result_items):
            try:
                # Extract title and link
                title_elem = item.find('a', class_='results__title')
                if not title_elem:
                    continue
                
                title = title_elem.get_text(strip=True)
                link = title_elem.get('href', '')
                
                if not link:
                    continue
                
                # Make URL absolute if needed
                if link.startswith('/'):
                    full_url = f"https://www.analysysmason.com{link}"
                elif link.startswith('http'):
                    full_url = link
                else:
                    full_url = f"https://www.analysysmason.com/{link.lstrip('/')}"
                
                # Avoid duplicates
                if full_url in seen_links:
                    continue
                seen_links.add(full_url)
                
                # Extract date from results__list (first item)
                date_text = "N/A"
                results_list = item.find('ul', class_='results__list')
                if results_list:
                    list_items = results_list.find_all('li', class_='results__list-item')
                    if list_items:
                        # First item is usually the date
                        date_text = list_items[0].get_text(strip=True)
                
                # Extract content type from results__list (second item)
                content_type = "N/A"
                if results_list:
                    list_items = results_list.find_all('li', class_='results__list-item')
                    if len(list_items) >= 2:
                        # Second item is usually the content type
                        content_type_link = list_items[1].find('a')
                        if content_type_link:
                            content_type = content_type_link.get_text(strip=True)
                
                # Extract description
                description = "N/A"
                desc_elem = item.find('p', class_='results__text')
                if desc_elem:
                    description = desc_elem.get_text(strip=True)
                
                # Extract image URL from background-image style
                image_url = "N/A"
                img_elem = item.find('a', class_='results__img')
                if img_elem:
                    style = img_elem.get('style', '')
                    # Extract URL from background-image: url('...')
                    match = re.search(r"background-image:\s*url\(['\"]?([^'\"]+)['\"]?\)", style)
                    if match:
                        img_path = match.group(1)
                        # Make URL absolute if needed
                        if img_path.startswith('/'):
                            image_url = f"https://www.analysysmason.com{img_path}"
                        elif img_path.startswith('http'):
                            image_url = img_path
                        else:
                            image_url = f"https://www.analysysmason.com/{img_path.lstrip('/')}"
                
                # Extract access type (Free/Premium) from results__tag
                access_type = "N/A"
                tag_elem = item.find('a', class_='results__tag')
                if tag_elem:
                    access_type = tag_elem.get_text(strip=True)
                
                # Skip if no valid link or title
                if not link or title == "N/A" or len(title) < 5:
                    continue
                
                articles.append({
                    'title': title,
                    'date': date_text,
                    'link': full_url,
                    'description': description,
                    'content_type': content_type,
                    'image_url': image_url,
                    'access_type': access_type
                })
                
                print(f"[DEBUG] Extracted article {idx+1}: {title[:50]}...")
                
            except Exception as e:
                print(f"[WARNING] Error processing article {idx+1}: {e}")
                continue
        
        return articles
    
    def scrape(self, debug: bool = False) -> List[Dict]:
        """
        Main method to scrape multiple pages.
        
        Args:
            debug: If True, save extracted HTML to file for debugging
        
        Returns:
            List of structured article data from all pages
        """
        all_articles = []
        seen_links = set()
        
        # Determine project root for debug files
        script_dir = Path(__file__).parent
        if script_dir.name == "scrapers":
            project_root = script_dir.parent
        else:
            project_root = script_dir
        
        for page in range(1, self.max_pages + 1):
            print(f"\n{'='*80}")
            print(f"Scraping page {page}/{self.max_pages}")
            print(f"{'='*80}\n")
            
            url = self._get_page_url(page)
            print(f"Fetching HTML from Analysys Mason Knowledge Centre (page {page})...")
            html = self.fetch_html(url)
            
            if debug:
                # Create debug folder if it doesn't exist
                debug_dir = project_root / "debug"
                debug_dir.mkdir(exist_ok=True)
                
                # Save to debug folder with page number
                debug_filepath = debug_dir / f"debug_analysysmason_page_{page}_full_html.html"
                with open(debug_filepath, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"[DEBUG] Full HTML saved to {debug_filepath} ({len(html)} chars)")
            
            print("Extracting articles from HTML...")
            articles = self.extract_articles(html)
            
            # Filter out duplicates across pages
            unique_articles = []
            for article in articles:
                if article['link'] not in seen_links:
                    seen_links.add(article['link'])
                    unique_articles.append(article)
            
            print(f"Found {len(unique_articles)} unique articles from page {page}")
            all_articles.extend(unique_articles)
            
            # Add a small delay between pages to be respectful
            if page < self.max_pages:
                time.sleep(2)
        
        print(f"\n{'='*80}")
        print(f"Total unique articles found: {len(all_articles)}")
        print(f"{'='*80}\n")
        
        return all_articles
    
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
            print(f"  Title:        {article['title']}")
            print(f"  Date:          {article['date']}")
            print(f"  Content Type:  {article.get('content_type', 'N/A')}")
            print(f"  Access Type:   {article.get('access_type', 'N/A')}")
            print(f"  Link:          {article['link']}")
            print(f"  Description:   {article['description']}")
            if article.get('image_url') != "N/A":
                print(f"  Image URL:     {article['image_url']}")
            print("-" * 80)
    
    def save_to_json(self, articles: List[Dict], filename: str = "analysysmason_articles.json"):
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
    
    # Check for max pages argument
    max_pages = 8
    for arg in sys.argv:
        if arg.startswith("--pages="):
            try:
                max_pages = int(arg.split("=")[1])
            except ValueError:
                print(f"Invalid pages argument: {arg}")
    
    try:
        scraper = AnalysysMasonScraper(max_pages=max_pages)
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
        with redirect_stderr(StringIO()):
            time.sleep(0.3)
            gc.collect()
            time.sleep(0.3)
    
    return 0

if __name__ == "__main__":
    exit(main())

