"""
Scraper for extracting structured data from Omdia search results.
Extracts: title, date, link, description, content_type, author, access_restriction, assets
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
from dotenv import load_dotenv
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Load environment variables
load_dotenv()

class OmdiaScraper:
    def __init__(self, base_url: str = "https://omdia.tech.informa.com/search"):
        """
        Initialize the scraper.
        
        Args:
            base_url: Base URL for Omdia search page
        """
        self.base_url = base_url
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def fetch_html(self, search_params: Optional[Dict] = None, use_selenium: bool = True) -> str:
        """
        Fetch HTML content from the Omdia search page.
        Uses Selenium to handle JavaScript-rendered content (AngularJS).
        
        Args:
            search_params: Optional dictionary of search parameters (e.g., {'page': 1, 'perPage': 20})
            use_selenium: If True, use Selenium (default). If False, use requests.
        
        Returns:
            HTML content as string
        """
        if use_selenium:
            return self._fetch_html_selenium(search_params)
        else:
            return self._fetch_html_requests(search_params)
    
    def _fetch_html_requests(self, search_params: Optional[Dict] = None) -> str:
        """Fetch HTML using requests library (may not work due to JS rendering)."""
        try:
            url = self.base_url
            if search_params:
                # Build query string
                query_parts = []
                for key, value in search_params.items():
                    query_parts.append(f"{key}={value}")
                if query_parts:
                    url += "?" + "&".join(query_parts)
            
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            raise Exception(f"Failed to fetch HTML: {str(e)}")
    
    def _fetch_html_selenium(self, search_params: Optional[Dict] = None) -> str:
        """Fetch HTML using undetected-chromedriver."""
        driver = None
        try:
            print("Initializing browser (this may take a moment)...")
            options = uc.ChromeOptions()
            options.add_argument('--start-maximized')
            options.add_argument('--disable-blink-features=AutomationControlled')
            
            driver = uc.Chrome(options=options, version_main=None)
            
            # Build URL with search parameters
            url = self.base_url
            if search_params:
                # Build hash fragment for AngularJS routing
                hash_parts = []
                for key, value in search_params.items():
                    hash_parts.append(f"{key}={value}")
                if hash_parts:
                    url += "#?" + "&".join(hash_parts)
            
            print(f"Loading page: {url}")
            driver.get(url)
            
            # Wait for page to load and AngularJS to render
            print("Waiting for page to load...")
            time.sleep(5)
            
            # Wait for search results to appear
            print("Waiting for search results to load...")
            max_wait = 30
            waited = 0
            while waited < max_wait:
                try:
                    # Check if search results are present
                    results = driver.find_elements(By.CSS_SELECTOR, ".search-result")
                    if len(results) > 0:
                        print(f"[OK] Content loaded successfully! Found {len(results)} search results")
                        break
                    
                    # Also check for "No Result Found" message
                    no_results = driver.find_elements(By.CSS_SELECTOR, ".no-result, [ng-if*='No Result']")
                    if len(no_results) > 0:
                        print("[INFO] No results found on this page")
                        break
                    
                except Exception:
                    pass
                
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
        Extract article data from HTML.
        Targets the structure: div.search-result
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with article data
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Find all search result divs
        search_results = soup.find_all('div', class_='search-result')
        
        print(f"[DEBUG] Found {len(search_results)} search result elements")
        
        # Process each result
        for idx, result in enumerate(search_results):
            try:
                # Extract title and link from heading
                title = "N/A"
                link = ""
                heading_elem = result.find('a', class_='search-result__heading')
                if heading_elem:
                    title = heading_elem.get_text(strip=True)
                    link = heading_elem.get('href', '')
                    if link and not link.startswith('http'):
                        link = f"https://omdia.tech.informa.com{link}"
                
                # Skip if no valid link found
                if not link or link in seen_links:
                    if link in seen_links:
                        continue
                    if not link:
                        continue
                
                seen_links.add(link)
                
                # Extract date
                date_text = "N/A"
                date_elem = result.find('time')
                if date_elem:
                    date_text = date_elem.get_text(strip=True)
                    # Also check datetime attribute
                    datetime_attr = date_elem.get('datetime', '')
                    if datetime_attr:
                        date_text = datetime_attr
                
                # Extract content type
                content_type = "N/A"
                content_type_elem = result.find('div', class_='search-result__content-type')
                if content_type_elem:
                    content_type = content_type_elem.get_text(strip=True)
                
                # Extract author
                author = "N/A"
                author_elem = result.find('div', class_='search-result__author')
                if author_elem:
                    # Extract author name from the span or link
                    author_span = author_elem.find('span')
                    if author_span:
                        author_link = author_span.find('a')
                        if author_link:
                            author = author_link.get_text(strip=True)
                        else:
                            author = author_span.get_text(strip=True)
                            # Remove "By " prefix if present
                            if author.startswith('By '):
                                author = author[3:].strip()
                
                # Extract description
                description = "N/A"
                desc_elem = result.find('p', class_='search-result__description')
                if desc_elem:
                    # Get text and clean up HTML tags
                    description = desc_elem.get_text(strip=True)
                    # Remove any nested <p> tags content that might be duplicated
                    description = re.sub(r'<p>.*?</p>', '', description, flags=re.DOTALL)
                    description = description.strip()
                
                # Extract access restriction
                access_restriction = "N/A"
                access_elem = result.find('p', class_='search-result__entitlement')
                if access_elem:
                    access_span = access_elem.find('span')
                    if access_span:
                        access_restriction = access_span.get_text(strip=True)
                
                # Extract assets/downloads
                assets = []
                assets_container = result.find('div', class_='search-result__assets')
                if assets_container:
                    asset_links = assets_container.find_all('a', class_='inf-sr-asset')
                    for asset_link in asset_links:
                        asset_name = asset_link.get_text(strip=True)
                        asset_url = asset_link.get('href', '')
                        if asset_url and not asset_url.startswith('http'):
                            asset_url = f"https://omdia.tech.informa.com{asset_url}"
                        
                        # Extract file details (size, extension)
                        file_details = asset_link.find('span', class_='file-details')
                        asset_size = "N/A"
                        asset_extension = "N/A"
                        if file_details:
                            size_elem = file_details.find('span', class_='ng-binding')
                            if size_elem:
                                asset_size = size_elem.get_text(strip=True)
                            # Extract extension from text
                            ext_match = re.search(r'\|\s*(\w+)', file_details.get_text())
                            if ext_match:
                                asset_extension = ext_match.group(1)
                        
                        assets.append({
                            'name': asset_name,
                            'url': asset_url,
                            'size': asset_size,
                            'extension': asset_extension
                        })
                
                # Check if it's free
                is_free = False
                free_label = result.find('div', class_='search-result__freelabel')
                if free_label:
                    is_free = True
                
                articles.append({
                    'title': title,
                    'date': date_text,
                    'link': link,
                    'description': description,
                    'content_type': content_type,
                    'author': author,
                    'access_restriction': access_restriction,
                    'is_free': is_free,
                    'assets': assets
                })
                
                print(f"[DEBUG] Extracted article {idx+1}: {title[:50]}...")
                
            except Exception as e:
                print(f"[WARNING] Error processing result {idx+1}: {e}")
                continue
        
        return articles
    
    def scrape(self, search_params: Optional[Dict] = None, max_pages: int = 1, debug: bool = False) -> List[Dict]:
        """
        Main method to scrape the page.
        
        Args:
            search_params: Optional dictionary of search parameters
            max_pages: Maximum number of pages to scrape (default: 1)
            debug: If True, save extracted HTML to file for debugging
        
        Returns:
            List of structured article data
        """
        all_articles = []
        
        # Default search parameters
        if search_params is None:
            search_params = {
                'page': 1,
                'sortBy': 'relevance',
                'sortOrder': 'desc',
                'entitledcontentonly': 1,
                'perPage': 20
            }
        
        for page_num in range(1, max_pages + 1):
            print(f"\n{'='*80}")
            print(f"Scraping page {page_num} of {max_pages}")
            print(f"{'='*80}\n")
            
            # Update page number
            current_params = search_params.copy()
            current_params['page'] = page_num
            
            print("Fetching HTML from Omdia search page...")
            html = self.fetch_html(search_params=current_params)
            
            if debug:
                # Determine project root
                script_dir = Path(__file__).parent
                if script_dir.name == "scrapers":
                    project_root = script_dir.parent
                else:
                    project_root = script_dir
                
                # Create debug folder if it doesn't exist
                debug_dir = project_root / "debug"
                debug_dir.mkdir(exist_ok=True)
                
                # Save to debug folder
                debug_filepath = debug_dir / f"debug_omdia_page_{page_num}_html.html"
                with open(debug_filepath, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"[DEBUG] Full HTML saved to {debug_filepath} ({len(html)} chars)")
            
            print("Extracting articles from HTML...")
            articles = self.extract_articles(html)
            print(f"Found {len(articles)} articles on page {page_num}")
            
            if not articles:
                print(f"[INFO] No articles found on page {page_num}. Stopping pagination.")
                break
            
            all_articles.extend(articles)
            
            # If we got fewer results than perPage, we're probably on the last page
            if len(articles) < current_params.get('perPage', 20):
                print(f"[INFO] Fewer results than expected. Likely reached last page.")
                break
            
            # Wait between pages to be respectful
            if page_num < max_pages:
                time.sleep(2)
        
        print(f"\nTotal articles scraped: {len(all_articles)}")
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
            print(f"  Title:       {article['title']}")
            print(f"  Date:        {article['date']}")
            print(f"  Type:        {article['content_type']}")
            print(f"  Author:      {article['author']}")
            print(f"  Free:        {article['is_free']}")
            print(f"  Access:      {article['access_restriction']}")
            print(f"  Link:        {article['link']}")
            if article['assets']:
                print(f"  Assets:      {len(article['assets'])} file(s)")
            print(f"  Description: {article['description'][:100]}..." if len(article['description']) > 100 else f"  Description: {article['description']}")
            print("-" * 80)
    
    def save_to_json(self, articles: List[Dict], filename: str = "omdia_articles.json"):
        """
        Save results to JSON file in the project root.
        
        Args:
            articles: List of article dictionaries
            filename: Output filename
        """
        # Determine project root
        script_dir = Path(__file__).parent
        if script_dir.name == "scrapers":
            project_root = script_dir.parent
        else:
            project_root = script_dir
        
        # Save to project root
        filepath = project_root / filename
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
    max_pages = 1
    for arg in sys.argv:
        if arg.startswith("--pages="):
            try:
                max_pages = int(arg.split("=")[1])
            except (ValueError, IndexError):
                pass
    
    try:
        scraper = OmdiaScraper()
        articles = scraper.scrape(max_pages=max_pages, debug=debug)
        scraper.display_results(articles)
        scraper.save_to_json(articles)
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        # Suppress stderr during cleanup
        with redirect_stderr(StringIO()):
            time.sleep(0.3)
            gc.collect()
            time.sleep(0.3)
    
    return 0

if __name__ == "__main__":
    exit(main())

