"""
Scraper for extracting structured data from IBM Think blog articles.
Extracts: title, date, link, description, format, tags
Supports multiple areas:
- Analytics: https://www.ibm.com/think/analytics
- Insights: https://www.ibm.com/think/insights
- Artificial Intelligence: https://www.ibm.com/think/artificial-intelligence
- Cloud: https://www.ibm.com/think/cloud
- Business Automation: https://www.ibm.com/think/business-automation
- Business Operations: https://www.ibm.com/think/business-operations
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import time
import re
from typing import List, Dict, Optional, Union
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

class IBMBlogScraper:
    def __init__(self, base_url: Optional[Union[str, List[str]]] = None):
        """
        Initialize the scraper.
        
        Args:
            base_url: Single URL string or list of URLs to scrape.
                     If None, defaults to all six areas (Analytics, Insights, AI, Cloud, Business Automation, Business Operations).
        """
        if base_url is None:
            # Default to all six areas
            self.urls = [
                "https://www.ibm.com/think/analytics",
                "https://www.ibm.com/think/insights",
                "https://www.ibm.com/think/artificial-intelligence",
                "https://www.ibm.com/think/cloud",
                "https://www.ibm.com/think/business-automation",
                "https://www.ibm.com/think/business-operations"
            ]
        elif isinstance(base_url, str):
            self.urls = [base_url]
        else:
            self.urls = base_url
        
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def fetch_html(self, url: str, use_selenium: bool = True) -> str:
        """
        Fetch HTML content from the IBM Think blog page.
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
                
                # Check if we have actual content - look for both structures
                media_rows = driver.find_elements(By.CSS_SELECTOR, ".ibm--horizontal-media-row")
                insights_items = driver.find_elements(By.CSS_SELECTOR, ".horizontal-media-group__item")
                hits_wrapper = driver.find_elements(By.CSS_SELECTOR, "#ibm-hits-wrapper")
                results_list = driver.find_elements(By.CSS_SELECTOR, ".horizontal-media-group__results-list")
                
                if len(media_rows) > 0 or len(insights_items) > 0 or len(hits_wrapper) > 0 or len(results_list) > 0 or len(page_source) > 50000:
                    total_items = len(media_rows) + len(insights_items)
                    print(f"[OK] Content loaded successfully! ({total_items} articles found)")
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
    
    def _extract_analytics_articles(self, soup: BeautifulSoup, seen_links: set) -> List[Dict]:
        """
        Extract articles from Analytics page structure (ibm--horizontal-media-row).
        
        Args:
            soup: BeautifulSoup object
            seen_links: Set of already seen links to avoid duplicates
            
        Returns:
            List of article dictionaries
        """
        articles = []
        article_rows = soup.find_all('a', class_='ibm--horizontal-media-row')
        
        print(f"[DEBUG] Found {len(article_rows)} Analytics article row(s)")
        
        for idx, row in enumerate(article_rows):
            try:
                # Extract link
                link = row.get('href', '')
                if not link:
                    continue
                
                # Make URL absolute if needed
                if link.startswith('/'):
                    full_url = f"https://www.ibm.com{link}"
                elif link.startswith('http'):
                    full_url = link
                else:
                    full_url = f"https://www.ibm.com/{link.lstrip('/')}"
                
                # Avoid duplicates
                if full_url in seen_links:
                    continue
                seen_links.add(full_url)
                
                # Extract date from meta section
                date_text = "N/A"
                meta = row.find('div', class_='ibm--horizontal-media-row__meta')
                if meta:
                    date_elem = meta.find('div', class_='ibm--horizontal-media-row__date')
                    if date_elem:
                        date_text = date_elem.get_text(strip=True)
                
                # Extract format/type
                format_text = "N/A"
                if meta:
                    format_elem = meta.find('div', class_='ibm--horizontal-media-row__format')
                    if format_elem:
                        format_text = format_elem.get_text(strip=True)
                
                # Extract title
                title = "N/A"
                content = row.find('div', class_='ibm--horizontal-media-row__content')
                if content:
                    heading = content.find('div', class_='ibm--horizontal-media-row__heading')
                    if heading:
                        title = heading.get_text(strip=True)
                
                # Extract description
                description = "N/A"
                if content:
                    desc_elem = content.find('p')
                    if desc_elem:
                        description = desc_elem.get_text(strip=True)
                
                # Extract tags/labels
                tags = []
                if content:
                    labels = content.find('div', class_='ibm--horizontal-media-row__labels')
                    if labels:
                        tag_spans = labels.find_all('span')
                        tags = [span.get_text(strip=True) for span in tag_spans if span.get_text(strip=True)]
                
                # Skip if no valid link or title
                if not link or title == "N/A" or len(title) < 5:
                    continue
                
                articles.append({
                    'title': title,
                    'date': date_text,
                    'link': full_url,
                    'description': description,
                    'format': format_text,
                    'tags': tags
                })
                
                print(f"[DEBUG] Extracted Analytics article {idx+1}: {title[:50]}...")
                
            except Exception as e:
                print(f"[WARNING] Error processing Analytics article row {idx+1}: {e}")
                continue
        
        return articles
    
    def _extract_insights_articles(self, soup: BeautifulSoup, seen_links: set) -> List[Dict]:
        """
        Extract articles from Insights page structure (horizontal-media-group__item).
        
        Args:
            soup: BeautifulSoup object
            seen_links: Set of already seen links to avoid duplicates
            
        Returns:
            List of article dictionaries
        """
        articles = []
        article_items = soup.find_all('div', class_='horizontal-media-group__item')
        
        print(f"[DEBUG] Found {len(article_items)} Insights article item(s)")
        
        for idx, item in enumerate(article_items):
            try:
                # Extract link from title-description section
                title_desc = item.find('div', class_='horizontal-media-group__item__title-description')
                if not title_desc:
                    continue
                
                link_elem = title_desc.find('h4', class_='heading-03')
                if not link_elem:
                    continue
                
                link_tag = link_elem.find('a')
                if not link_tag:
                    continue
                
                link = link_tag.get('href', '')
                if not link:
                    continue
                
                # Make URL absolute if needed
                if link.startswith('/'):
                    full_url = f"https://www.ibm.com{link}"
                elif link.startswith('http'):
                    full_url = link
                else:
                    full_url = f"https://www.ibm.com/{link.lstrip('/')}"
                
                # Avoid duplicates
                if full_url in seen_links:
                    continue
                seen_links.add(full_url)
                
                # Extract date and format from date-type section
                date_text = "N/A"
                format_text = "N/A"
                date_type = item.find('div', class_='horizontal-media-group__item__date-type')
                if date_type:
                    spans = date_type.find_all('span', class_='body-short-01')
                    if len(spans) >= 1:
                        date_p = spans[0].find('p')
                        if date_p:
                            date_text = date_p.get_text(strip=True)
                    if len(spans) >= 2:
                        format_p = spans[1].find('p')
                        if format_p:
                            format_text = format_p.get_text(strip=True)
                
                # Extract title
                title = link_tag.get_text(strip=True) if link_tag else "N/A"
                
                # Extract description
                description = "N/A"
                desc_span = title_desc.find('span', class_='hmg-paragraph')
                if desc_span:
                    desc_p = desc_span.find('p')
                    if desc_p:
                        description = desc_p.get_text(strip=True)
                
                # Skip if no valid link or title
                if not link or title == "N/A" or len(title) < 5:
                    continue
                
                articles.append({
                    'title': title,
                    'date': date_text,
                    'link': full_url,
                    'description': description,
                    'format': format_text,
                    'tags': []  # Insights structure doesn't have tags in the same way
                })
                
                print(f"[DEBUG] Extracted Insights article {idx+1}: {title[:50]}...")
                
            except Exception as e:
                print(f"[WARNING] Error processing Insights article item {idx+1}: {e}")
                continue
        
        return articles
    
    def extract_articles(self, html: str) -> List[Dict]:
        """
        Extract blog articles from HTML.
        Handles both Analytics (ibm--horizontal-media-row) and Insights (horizontal-media-group__item) structures.
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with title, date, link, description, format, tags
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Try both extraction methods
        analytics_articles = self._extract_analytics_articles(soup, seen_links)
        insights_articles = self._extract_insights_articles(soup, seen_links)
        
        articles.extend(analytics_articles)
        articles.extend(insights_articles)
        
        return articles
    
    def scrape(self, debug: bool = False) -> List[Dict]:
        """
        Main method to scrape the page(s).
        
        Args:
            debug: If True, save extracted HTML to file for debugging
        
        Returns:
            List of structured article data from all URLs
        """
        all_articles = []
        seen_links = set()
        
        # Determine project root for debug files
        script_dir = Path(__file__).parent
        if script_dir.name == "scrapers":
            project_root = script_dir.parent
        else:
            project_root = script_dir
        
        for url_idx, url in enumerate(self.urls):
            print(f"\n{'='*80}")
            print(f"Scraping URL {url_idx + 1}/{len(self.urls)}: {url}")
            print(f"{'='*80}\n")
            
            print("Fetching HTML from IBM Think blog page...")
            html = self.fetch_html(url)
            
            if debug:
                # Create debug folder if it doesn't exist
                debug_dir = project_root / "debug"
                debug_dir.mkdir(exist_ok=True)
                
                # Save to debug folder with URL identifier
                url_slug = url.split('/')[-1] if '/' in url else 'unknown'
                debug_filepath = debug_dir / f"debug_ibm_blog_{url_slug}_full_html.html"
                with open(debug_filepath, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"[DEBUG] Full HTML saved to {debug_filepath} ({len(html)} chars)")
            
            print("Extracting articles from HTML...")
            articles = self.extract_articles(html)
            
            # Filter out duplicates across URLs
            unique_articles = []
            for article in articles:
                if article['link'] not in seen_links:
                    seen_links.add(article['link'])
                    unique_articles.append(article)
            
            print(f"Found {len(unique_articles)} unique articles from this URL")
            all_articles.extend(unique_articles)
        
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
            print(f"  Title:       {article['title']}")
            print(f"  Date:        {article['date']}")
            print(f"  Format:      {article.get('format', 'N/A')}")
            print(f"  Link:        {article['link']}")
            print(f"  Description: {article['description']}")
            if article.get('tags'):
                print(f"  Tags:        {', '.join(article['tags'])}")
            print("-" * 80)
    
    def save_to_json(self, articles: List[Dict], filename: str = "ibm_blog_articles.json"):
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
        scraper = IBMBlogScraper()
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

