"""
Scraper for extracting structured data from Salesforce blog page.
Extracts: title, date, link, authors, excerpt, category, topics
Targets: article.card.card--wide elements from https://www.salesforce.com/blog/recent-stories/
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

class SalesforceBlogScraper:
    def __init__(self):
        """
        Initialize the scraper.
        """
        self.url = "https://www.salesforce.com/blog/recent-stories/"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def fetch_html(self, use_selenium: bool = True) -> str:
        """
        Fetch HTML content from the Salesforce blog page.
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
            
            # Wait for blog articles to load
            max_wait = 30
            waited = 0
            while waited < max_wait:
                page_source = driver.page_source
                
                # Check if we have blog content - look for article cards
                articles = driver.find_elements(By.CSS_SELECTOR, "article.card.card--wide")
                container = driver.find_elements(By.CSS_SELECTOR, ".container")
                
                if len(articles) > 0 or len(container) > 0 or len(page_source) > 50000:
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
            test_articles = temp_soup.find_all('article', class_='card')
            print(f"[DEBUG] Found {len(test_articles)} article cards in full HTML")
            
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
        Targets article.card.card--wide elements.
        
        Args:
            html: Raw HTML content
        
        Returns:
            List of dictionaries with title, date, link, authors, excerpt, topics
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Find all article cards
        article_cards = soup.find_all('article', class_=lambda x: x and 'card' in str(x) and 'card--wide' in str(x))
        
        print(f"[DEBUG] Found {len(article_cards)} article cards")
        
        for card in article_cards:
            # Extract title and link from h2.card__title > a
            title_elem = card.find('h2', class_='card__title')
            if not title_elem:
                continue
            
            title_link = title_elem.find('a', href=True)
            if not title_link:
                continue
            
            title = title_link.get_text(strip=True)
            link = title_link.get('href', '')
            
            # Skip if no valid link or title
            if not link or not title or len(title) < 5:
                continue
            
            # Make URL absolute if relative
            if link.startswith('/'):
                link = f"https://www.salesforce.com{link}"
            elif not link.startswith('http'):
                link = f"https://www.salesforce.com/{link.lstrip('/')}"
            
            # Extract date from time.card__date
            date_text = "N/A"
            date_elem = card.find('time', class_='card__date')
            if date_elem:
                # Try datetime attribute first
                datetime_attr = date_elem.get('datetime', '')
                if datetime_attr:
                    date_text = datetime_attr
                else:
                    # Fallback to text content
                    date_text = date_elem.get_text(strip=True)
            
            # Extract authors from address.byline elements
            authors = []
            byline_elems = card.find_all('address', class_='byline')
            for byline in byline_elems:
                byline_link = byline.find('a', class_='byline__contents')
                if byline_link:
                    name_spans = byline_link.find_all('span', class_='byline__name')
                    if name_spans:
                        # Combine first and last name
                        full_name = ' '.join([span.get_text(strip=True) for span in name_spans])
                        if full_name:
                            authors.append(full_name)
            
            # Extract excerpt from div.card__excerpt > p.body-2
            excerpt = ""
            excerpt_elem = card.find('div', class_='card__excerpt')
            if excerpt_elem:
                excerpt_p = excerpt_elem.find('p', class_='body-2')
                if excerpt_p:
                    excerpt = excerpt_p.get_text(strip=True)
            
            # Extract category from div.card__taxonomies > a.sf-tag.topic
            category = "N/A"
            taxonomies_elem = card.find('div', class_='card__taxonomies')
            if taxonomies_elem:
                category_link = taxonomies_elem.find('a', class_=lambda x: x and 'sf-tag' in str(x) and 'topic' in str(x))
                if category_link:
                    category = category_link.get_text(strip=True)
            
            # Extract topics from ul.card__topics > li > a
            topics = []
            topics_elem = card.find('ul', class_='card__topics')
            if topics_elem:
                topic_links = topics_elem.find_all('a', class_='label-secondary')
                for topic_link in topic_links:
                    topic_text = topic_link.get_text(strip=True)
                    if topic_text:
                        topics.append(topic_text)
            
            # Avoid duplicates
            if link in seen_links:
                continue
            seen_links.add(link)
            
            articles.append({
                'title': title,
                'date': date_text,
                'link': link,
                'authors': authors,
                'excerpt': excerpt,
                'category': category,
                'topics': topics
            })
        
        print(f"[DEBUG] Extracted {len(articles)} unique articles")
        
        return articles
    
    def scrape(self, debug: bool = False) -> List[Dict]:
        """
        Main method to scrape the page.
        
        Args:
            debug: If True, save extracted HTML to file for debugging
        
        Returns:
            List of structured article data with title, date, link, authors, excerpt, topics
        """
        print("Fetching HTML from Salesforce blog page...")
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
            debug_filepath = debug_dir / "debug_salesforce_blog_full_html.html"
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
        print(f"  Title:    {article['title']}")
        print(f"  Date:     {article.get('date', 'N/A')}")
        print(f"  Category: {article.get('category', 'N/A')}")
        print(f"  Authors:  {', '.join(article.get('authors', [])) if article.get('authors') else 'N/A'}")
        print(f"  Topics:   {', '.join(article.get('topics', [])) if article.get('topics') else 'N/A'}")
        if article.get('excerpt'):
            excerpt = article['excerpt'][:100] + "..." if len(article['excerpt']) > 100 else article['excerpt']
            print(f"  Excerpt: {excerpt}")
        print(f"  Link:    {article['link']}")
        print("-" * 80)
    
    def save_to_json(self, articles: List[Dict], filename: str = "salesforce_blog_articles.json"):
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
        scraper = SalesforceBlogScraper()
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

