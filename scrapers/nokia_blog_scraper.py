"""
Scraper for extracting structured data from Nokia blog page.
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

class NokiaBlogScraper:
    def __init__(self):
        """
        Initialize the scraper.
        """
        self.base_url = "https://www.nokia.com/blog/all-posts/"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def fetch_html(self, url: str = None, use_selenium: bool = True) -> str:
        """
        Fetch HTML content from the Nokia blog page.
        Uses Selenium to handle JavaScript-rendered content.
        
        Args:
            url: URL to fetch. If None, uses base_url with page 1.
            use_selenium: If True, use Selenium (default). If False, use requests.
        
        Returns:
            HTML content as string
        """
        if url is None:
            url = f"{self.base_url}?page=1/"
        
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
        """Fetch HTML using undetected-chromedriver to handle JavaScript rendering."""
        driver = None
        try:
            print("Initializing browser (this may take a moment)...")
            options = uc.ChromeOptions()
            options.add_argument('--start-maximized')
            options.add_argument('--disable-blink-features=AutomationControlled')
            
            driver = uc.Chrome(options=options, version_main=None)
            
            print(f"Loading page: {url}")
            driver.get(url)
            
            # Wait for page to load
            print("Waiting for page content to load...")
            time.sleep(5)
            
            # Wait for blog content to load
            max_wait = 30
            waited = 0
            while waited < max_wait:
                page_source = driver.page_source
                
                # Check if we have blog content - look for blog-post-list
                blog_list = driver.find_elements(By.CSS_SELECTOR, ".blog-post-list")
                blog_teasers = driver.find_elements(By.CSS_SELECTOR, ".blog-post-teaser")
                
                if len(blog_list) > 0 or len(blog_teasers) > 0 or len(page_source) > 50000:
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
            test_teasers = temp_soup.find_all('div', class_='blog-post-teaser')
            print(f"[DEBUG] Found {len(test_teasers)} blog teasers in full HTML")
            
            return html
        except Exception as e:
            raise Exception(f"Failed to fetch HTML with Selenium: {str(e)}")
        finally:
            if driver:
                try:
                    print("Closing browser...")
                    # Suppress stderr during cleanup to avoid harmless exception messages
                    with redirect_stderr(StringIO()):
                        try:
                            driver.quit()
                        except (OSError, Exception):
                            # Ignore cleanup errors - driver may already be closed
                            pass
                        time.sleep(1)  # Give time for cleanup
                        # Set driver to None to help with garbage collection
                        driver = None
                except Exception:
                    # Ignore cleanup errors - driver may already be closed
                    pass
    
    def extract_article_links(self, html: str) -> List[Dict]:
        """
        Extract article links using BeautifulSoup.
        Targets blog-post-teaser elements within blog-post-list container.
        
        Args:
            html: Raw HTML content
        
        Returns:
            List of dictionaries with title, date, and link
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Find the blog post list container
        blog_list = soup.find('div', class_='blog-post-list')
        
        if not blog_list:
            print("[WARNING] Could not find blog-post-list container, searching all blog-post-teaser elements...")
            # Fallback: find all blog-post-teaser elements
            blog_teasers = soup.find_all('div', class_='blog-post-teaser')
        else:
            # Find all blog teasers within the container
            blog_teasers = blog_list.find_all('div', class_='blog-post-teaser')
        
        print(f"[DEBUG] Found {len(blog_teasers)} blog teasers")
        
        # Process each blog teaser
        for teaser in blog_teasers:
            # Find the author-page-card div
            card = teaser.find('div', class_='author-page-card')
            if not card:
                continue
            
            # Find the anchor tag with the link
            a_tag = card.find('a', href=True)
            if not a_tag:
                continue
            
            # Extract link
            link = a_tag.get('href', '')
            if not link:
                continue
            
            # Make URL absolute if relative
            if link.startswith('/'):
                link = f"https://www.nokia.com{link}"
            elif not link.startswith('http'):
                link = f"https://www.nokia.com/{link.lstrip('/')}"
            
            # Avoid duplicates
            if link in seen_links:
                continue
            seen_links.add(link)
            
            # Extract title from author-page-card-title
            # The title is in <p class="author-page-card-title"> but may contain an image
            # We need to get the text content, ignoring the image
            title_p = card.find('p', class_='author-page-card-title')
            if title_p:
                # Get all text, but exclude text from nested images
                # Clone the element and remove images to get clean text
                title_clone = BeautifulSoup(str(title_p), 'html.parser')
                for img in title_clone.find_all('img'):
                    img.decompose()
                title = title_clone.get_text(strip=True)
            else:
                # Fallback: use alt text from image or link text
                img = card.find('img', class_='author-page-card-image')
                if img:
                    title = img.get('alt', '').strip()
                else:
                    title = a_tag.get_text(strip=True)
            
            # Skip if no valid title
            if not title or len(title) < 5:
                continue
            
            # Extract date - look for date patterns in teaser text
            date_text = "N/A"
            teaser_text = teaser.get_text()
            date_patterns = [
                r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',
                r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b',
                r'\b\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b',
                r'\b\d{4}-\d{2}-\d{2}\b',
                r'\b\d{1,2}/\d{1,2}/\d{4}\b',
            ]
            for pattern in date_patterns:
                match = re.search(pattern, teaser_text, re.IGNORECASE)
                if match:
                    date_text = match.group(0)
                    break
            
            articles.append({
                'title': title,
                'date': date_text,
                'link': link
            })
        
        print(f"[DEBUG] Extracted {len(articles)} unique articles")
        
        return articles
    
    def scrape_all_pages(self, max_pages: int = 10, debug: bool = False) -> List[Dict]:
        """
        Scrape all pages of the blog.
        
        Args:
            max_pages: Maximum number of pages to scrape
            debug: If True, save extracted HTML to file for debugging
        
        Returns:
            List of structured article data with title, date, and link
        """
        all_articles = []
        seen_links = set()
        page = 1
        
        while page <= max_pages:
            url = f"{self.base_url}?page={page}/"
            print(f"\n{'='*80}")
            print(f"Scraping page {page}: {url}")
            print(f"{'='*80}")
            
            try:
                html = self.fetch_html(url)
                
                if debug and page == 1:
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
                    debug_filepath = debug_dir / "debug_nokia_blog_full_html.html"
                    with open(debug_filepath, "w", encoding="utf-8") as f:
                        f.write(html)
                    print(f"[DEBUG] Full HTML saved to debug_nokia_blog_full_html.html ({len(html)} chars)")
                
                articles = self.extract_article_links(html)
                
                if not articles:
                    print(f"No articles found on page {page}. Stopping pagination.")
                    break
                
                # Add articles that haven't been seen
                new_articles = []
                for article in articles:
                    if article['link'] not in seen_links:
                        seen_links.add(article['link'])
                        new_articles.append(article)
                
                all_articles.extend(new_articles)
                print(f"Found {len(articles)} articles on page {page} ({len(new_articles)} new)")
                
                # If we got fewer articles than expected, might be last page
                if len(articles) < 10:  # Assuming at least 10 articles per page normally
                    print(f"Few articles found on page {page}. This might be the last page.")
                    # Still continue to next page to be sure, but break if next page is empty
                
                page += 1
                
                # Small delay between pages
                time.sleep(2)
                
            except Exception as e:
                print(f"Error scraping page {page}: {str(e)}")
                break
        
        print(f"\n{'='*80}")
        print(f"Final result: {len(all_articles)} unique blog articles found across {page-1} page(s)")
        print(f"{'='*80}")
        
        return all_articles
    
    def scrape(self, debug: bool = False, all_pages: bool = False) -> List[Dict]:
        """
        Main method to scrape the page.
        
        Args:
            debug: If True, save extracted HTML to file for debugging
            all_pages: If True, scrape all pages. If False, only scrape page 1.
        
        Returns:
            List of structured article data with title, date, and link
        """
        if all_pages:
            return self.scrape_all_pages(debug=debug)
        
        print("Fetching HTML from Nokia blog page...")
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
            debug_filepath = debug_dir / "debug_nokia_blog_full_html.html"
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
    
    def save_to_json(self, articles: List[Dict], filename: str = "nokia_blog_articles.json"):
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
    
    # Check for all-pages flag
    all_pages = "--all-pages" in sys.argv or "-a" in sys.argv
    
    try:
        scraper = NokiaBlogScraper()
        articles = scraper.scrape(debug=debug, all_pages=all_pages)
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
        # This is a known issue with undetected-chromedriver on Windows and can be safely ignored
        try:
            with redirect_stderr(StringIO()):
                time.sleep(0.3)
                # Force garbage collection to trigger cleanup while stderr is suppressed
                gc.collect()
                time.sleep(0.3)
        except Exception:
            # Ignore any errors during cleanup
            pass
    
    return 0

if __name__ == "__main__":
    exit(main())

