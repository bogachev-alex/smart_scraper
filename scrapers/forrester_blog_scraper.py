"""
Scraper for extracting structured data from Forrester blog page.
Extracts: title, date, link, description, author, type
Scrapes from: https://www.forrester.com/blogs/
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
from datetime import datetime, timedelta
try:
    from dateutil import parser as date_parser
    HAS_DATEUTIL = True
except ImportError:
    HAS_DATEUTIL = False
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

class ForresterBlogScraper:
    def __init__(self, stop_date: Optional[datetime] = None):
        """
        Initialize the scraper.
        
        Args:
            stop_date: Stop loading more posts when reaching this date or earlier.
                      If None, defaults to June 1, 2025.
        """
        self.url = "https://www.forrester.com/blogs/"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        # Default stop date: June 1, 2025
        self.stop_date = stop_date or datetime(2025, 6, 1)
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """
        Parse date string to datetime object.
        Handles both relative dates ("4 hours ago", "1 day ago") and absolute dates ("November 13, 2025").
        
        Args:
            date_str: Date string to parse
            
        Returns:
            datetime object or None if parsing fails
        """
        if not date_str or date_str == "N/A":
            return None
        
        date_str = date_str.strip()
        now = datetime.now()
        
        # Handle relative dates
        if "ago" in date_str.lower():
            # Pattern: "X hours ago", "X days ago", "X weeks ago", "X months ago"
            match = re.search(r'(\d+)\s+(hour|hours|day|days|week|weeks|month|months)\s+ago', date_str.lower())
            if match:
                amount = int(match.group(1))
                unit = match.group(2).rstrip('s')  # Remove plural
                
                if unit == "hour":
                    return now - timedelta(hours=amount)
                elif unit == "day":
                    return now - timedelta(days=amount)
                elif unit == "week":
                    return now - timedelta(weeks=amount)
                elif unit == "month":
                    # Approximate months as 30 days
                    return now - timedelta(days=amount * 30)
        
        # Handle absolute dates
        # Try common date formats manually first
        date_formats = [
            "%B %d, %Y",      # "November 13, 2025"
            "%b %d, %Y",       # "Nov 13, 2025"
            "%m/%d/%Y",        # "11/13/2025"
            "%Y-%m-%d",        # "2025-11-13"
            "%d %B %Y",        # "13 November 2025"
            "%d %b %Y",        # "13 Nov 2025"
        ]
        for fmt in date_formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        # If dateutil is available, try it as a fallback
        if HAS_DATEUTIL:
            try:
                parsed_date = date_parser.parse(date_str)
                return parsed_date
            except (ValueError, TypeError):
                pass
        
        return None
    
    def _check_if_reached_stop_date(self, html: str) -> bool:
        """
        Check if we've reached the stop date by parsing dates from the HTML.
        
        Args:
            html: HTML content to check
            
        Returns:
            True if we've reached or passed the stop date
        """
        soup = BeautifulSoup(html, 'html.parser')
        posts_container = soup.find('div', id='all-posts')
        if not posts_container:
            return False
        
        post_blocks = posts_container.find_all('div', class_=lambda x: x and 'post-block' in str(x) and 'insight' in str(x))
        
        # Check the last 10 posts to see if we've reached the stop date
        # We check multiple posts to account for any out-of-order dates or relative dates
        posts_to_check = post_blocks[-10:] if len(post_blocks) >= 10 else post_blocks
        
        found_stop_date = False
        for block in posts_to_check:
            # Skip promo blocks
            if block.get('data-type') == 'promo':
                continue
            
            meta = block.find('div', class_='post-block__meta')
            if meta:
                date_span = meta.find('span', class_='post-block__date')
                if date_span:
                    date_str = date_span.get_text(strip=True)
                    parsed_date = self._parse_date(date_str)
                    
                    if parsed_date:
                        # If we find an absolute date (not relative like "4 hours ago")
                        # and it's on or before the stop date, we've reached our target
                        if "ago" not in date_str.lower() and parsed_date <= self.stop_date:
                            print(f"  Found article dated {date_str} ({parsed_date.strftime('%Y-%m-%d')}), which is on or before stop date {self.stop_date.strftime('%Y-%m-%d')}")
                            found_stop_date = True
                            break
        
        return found_stop_date
    
    def fetch_html(self, load_all_pages: bool = True, max_clicks: int = 50) -> str:
        """
        Fetch HTML content from the Forrester blog page.
        Uses Selenium to handle JavaScript-rendered content and "More posts" button.
        
        Args:
            load_all_pages: If True, click "More posts" button to load all content
            max_clicks: Maximum number of "More posts" button clicks
        
        Returns:
            HTML content as string
        """
        return self._fetch_html_selenium(load_all_pages=load_all_pages, max_clicks=max_clicks)
    
    def _fetch_html_selenium(self, load_all_pages: bool = True, max_clicks: int = 50) -> str:
        """
        Fetch HTML using undetected-chromedriver to handle JavaScript rendering
        and "More posts" button clicking.
        
        Args:
            load_all_pages: If True, click "More posts" button to load all content
            max_clicks: Maximum number of "More posts" button clicks
        
        Returns:
            HTML content as string
        """
        driver = None
        try:
            print("Initializing browser (this may take a moment)...")
            options = uc.ChromeOptions()
            options.add_argument('--start-maximized')
            options.add_argument('--disable-blink-features=AutomationControlled')
            
            driver = uc.Chrome(options=options, version_main=None)
            
            print(f"Loading page: {self.url}")
            driver.get(self.url)
            
            # Wait for page content to load
            print("Waiting for page content to load...")
            max_wait = 30
            waited = 0
            while waited < max_wait:
                page_source = driver.page_source
                
                # Check if we have actual content - look for posts-container
                posts_container = driver.find_elements(By.CSS_SELECTOR, "#all-posts")
                post_blocks = driver.find_elements(By.CSS_SELECTOR, ".post-block.insight")
                
                if len(posts_container) > 0 or len(post_blocks) > 0 or len(page_source) > 50000:
                    print(f"[OK] Content loaded successfully! ({len(post_blocks)} posts found)")
                    break
                
                time.sleep(2)
                waited += 2
                if waited % 4 == 0:
                    print(f"  Still waiting... ({waited}s)")
            
            # Additional wait for JavaScript to fully render
            time.sleep(3)
            
            # Handle "More posts" button clicking
            if load_all_pages:
                print(f"Loading posts until reaching {self.stop_date.strftime('%B %d, %Y')} or earlier...")
                clicks = 0
                last_post_count = len(driver.find_elements(By.CSS_SELECTOR, ".post-block.insight"))
                
                while clicks < max_clicks:
                    try:
                        # Check if we've reached the stop date before clicking
                        current_html = driver.page_source
                        if self._check_if_reached_stop_date(current_html):
                            print(f"  Reached stop date ({self.stop_date.strftime('%Y-%m-%d')}). Stopping.")
                            break
                        
                        # Look for "More posts" button - try multiple selectors
                        load_more_button = None
                        try:
                            # Primary selector: XPath to handle class with dash
                            load_more_button = driver.find_element(By.XPATH, "//div[contains(@class, 'loadmore') and contains(@class, 'forr-cta') and contains(@class, '-primary')]")
                        except NoSuchElementException:
                            # Fallback: try finding by text content
                            try:
                                load_more_button = driver.find_element(By.XPATH, "//div[contains(@class, 'loadmore')]//span[contains(text(), 'More')]")
                                # Get parent div
                                if load_more_button:
                                    load_more_button = load_more_button.find_element(By.XPATH, "./ancestor::div[contains(@class, 'loadmore')]")
                            except NoSuchElementException:
                                pass
                        
                        if load_more_button and load_more_button.is_displayed():
                            # Scroll to button
                            driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", load_more_button)
                            time.sleep(2)
                            
                            # Click using JavaScript to avoid interception
                            driver.execute_script("arguments[0].click();", load_more_button)
                            clicks += 1
                            
                            print(f"  Clicked 'More posts' button (click {clicks}/{max_clicks})...")
                            
                            # Wait for new content to load
                            time.sleep(4)
                            
                            # Check if new posts were loaded
                            current_post_count = len(driver.find_elements(By.CSS_SELECTOR, ".post-block.insight"))
                            if current_post_count == last_post_count:
                                print(f"  No new posts loaded. Stopping.")
                                break
                            
                            last_post_count = current_post_count
                            print(f"  Total posts loaded: {current_post_count}")
                            
                            # Check again after loading new content
                            current_html = driver.page_source
                            if self._check_if_reached_stop_date(current_html):
                                print(f"  Reached stop date ({self.stop_date.strftime('%Y-%m-%d')}). Stopping.")
                                break
                        else:
                            print("  'More posts' button not visible. Stopping.")
                            break
                            
                    except NoSuchElementException:
                        print("  'More posts' button not found. All posts may be loaded.")
                        break
                    except Exception as e:
                        print(f"  Error clicking 'More posts' button: {e}")
                        break
                
                print(f"Finished loading posts. Total clicks: {clicks}")
            
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
        Extract blog articles from HTML.
        Targets post-block elements within the posts-container.
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with title, date, link, description, author, type
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Find the posts container
        posts_container = soup.find('div', id='all-posts')
        if not posts_container:
            # Fallback: find all post-block elements directly
            post_blocks = soup.find_all('div', class_=lambda x: x and 'post-block' in str(x) and 'insight' in str(x))
        else:
            # Find all post-block elements with insight class
            post_blocks = posts_container.find_all('div', class_=lambda x: x and 'post-block' in str(x) and 'insight' in str(x))
        
        print(f"[DEBUG] Found {len(post_blocks)} post block(s)")
        
        # Process each post block
        for idx, block in enumerate(post_blocks):
            try:
                # Skip promo blocks (they have data-type="promo")
                data_type = block.get('data-type', '')
                if data_type == 'promo':
                    continue
                
                # Extract title and link from post-block__title > a
                title = "N/A"
                link = "N/A"
                
                title_elem = block.find('h2', class_='post-block__title')
                if title_elem:
                    link_tag = title_elem.find('a')
                    if link_tag:
                        link = link_tag.get('href', '')
                        if link:
                            # Make URL absolute if needed
                            if link.startswith('/'):
                                link = f"https://www.forrester.com{link}"
                            elif not link.startswith('http'):
                                link = f"https://www.forrester.com/{link.lstrip('/')}"
                        
                        title = link_tag.get_text(strip=True)
                
                # Skip if no valid link or title
                if link == "N/A" or title == "N/A" or len(title) < 5:
                    continue
                
                # Avoid duplicates
                if link in seen_links:
                    continue
                seen_links.add(link)
                
                # Extract type/subheading (Blog, Podcast, etc.)
                type_text = "N/A"
                subheading = block.find('div', class_='post-block__subheading')
                if subheading:
                    type_text = subheading.get_text(strip=True)
                
                # Extract author
                author = "N/A"
                meta = block.find('div', class_='post-block__meta')
                if meta:
                    author_span = meta.find('span', class_='post-block__author')
                    if author_span:
                        author_link = author_span.find('a')
                        if author_link:
                            author = author_link.get_text(strip=True)
                        else:
                            author = author_span.get_text(strip=True)
                
                # Extract date
                date_text = "N/A"
                if meta:
                    date_span = meta.find('span', class_='post-block__date')
                    if date_span:
                        date_text = date_span.get_text(strip=True)
                
                # Extract excerpt/description
                description = "N/A"
                excerpt = block.find('div', class_='post-block__excerpt')
                if excerpt:
                    description = excerpt.get_text(strip=True)
                
                articles.append({
                    'title': title,
                    'date': date_text,
                    'link': link,
                    'description': description,
                    'author': author,
                    'type': type_text
                })
                
                print(f"[DEBUG] Extracted article {idx+1}: {title[:50]}...")
                
            except Exception as e:
                print(f"[WARNING] Error processing post block {idx+1}: {e}")
                continue
        
        return articles
    
    def scrape(self, debug: bool = False, load_all_pages: bool = True, max_clicks: int = 50) -> List[Dict]:
        """
        Main method to scrape the blog page.
        
        Args:
            debug: If True, save extracted HTML to file for debugging
            load_all_pages: If True, click "More posts" button to load all content
            max_clicks: Maximum number of "More posts" button clicks
        
        Returns:
            List of structured article data
        """
        print("Fetching HTML from Forrester blog page...")
        html = self.fetch_html(load_all_pages=load_all_pages, max_clicks=max_clicks)
        
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
            debug_filepath = debug_dir / "debug_forrester_blog_full_html.html"
            with open(debug_filepath, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[DEBUG] Full HTML saved to {debug_filepath} ({len(html)} chars)")
        
        print("Extracting blog articles from HTML...")
        articles = self.extract_articles(html)
        print(f"Found {len(articles)} article(s)")
        
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
            print(f"  Title:       {article['title']}")
            print(f"  Type:        {article.get('type', 'N/A')}")
            print(f"  Author:      {article.get('author', 'N/A')}")
            print(f"  Date:        {article.get('date', 'N/A')}")
            print(f"  Link:        {article['link']}")
            print(f"  Description: {article['description'][:100]}..." if len(article.get('description', '')) > 100 else f"  Description: {article.get('description', 'N/A')}")
            print("-" * 80)
    
    def save_to_json(self, articles: List[Dict], filename: str = "forrester_blog_articles.json"):
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
    
    # Check for flags
    debug = "--debug" in sys.argv or "-d" in sys.argv
    load_all = "--no-load-all" not in sys.argv  # Default to True, use --no-load-all to disable
    
    # Parse max_clicks if provided
    max_clicks = 50
    for arg in sys.argv:
        if arg.startswith("--max-clicks="):
            try:
                max_clicks = int(arg.split("=")[1])
            except ValueError:
                print(f"Invalid max-clicks value, using default: 50")
    
    try:
        scraper = ForresterBlogScraper()
        articles = scraper.scrape(debug=debug, load_all_pages=load_all, max_clicks=max_clicks)
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

