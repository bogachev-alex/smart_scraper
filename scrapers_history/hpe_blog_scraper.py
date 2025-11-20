"""
Scraper for extracting structured data from HPE Community blog page.
Extracts: title, date, link, author
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
from datetime import datetime, timedelta
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

class HPEBlogScraper:
    def __init__(self, urls: List[str] = None):
        """
        Initialize the scraper.
        
        Args:
            urls: List of URLs to scrape. If None, uses default 3 HPE blog pages.
        """
        if urls is None:
            self.urls = [
                "https://community.hpe.com/t5/the-cloud-experience-everywhere/bg-p/TransformingIT",
                "https://community.hpe.com/t5/networking/bg-p/HPE_Networking",
                "https://community.hpe.com/t5/ai-unlocked/bg-p/AI-Unlocked"
            ]
        else:
            self.urls = urls if isinstance(urls, list) else [urls]
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def fetch_html(self, url: str = None, use_selenium: bool = True) -> str:
        """
        Fetch HTML content from the HPE Community blog page.
        Uses Selenium to handle JavaScript-rendered content.
        
        Args:
            url: URL to fetch. If None, uses the first URL in self.urls.
            use_selenium: If True, use Selenium (default). If False, use requests.
        
        Returns:
            HTML content as string
        """
        if url is None:
            url = self.urls[0] if self.urls else None
        if url is None:
            raise ValueError("No URL provided")
        
        # Temporarily set self.url for the fetch methods
        original_url = getattr(self, 'url', None)
        self.url = url
        
        try:
            if use_selenium:
                return self._fetch_html_selenium()
            else:
                return self._fetch_html_requests()
        finally:
            # Restore original URL if it existed
            if original_url:
                self.url = original_url
    
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
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            
            driver = uc.Chrome(options=options, version_main=None)
            
            print("Loading page...")
            driver.get(self.url)
            
            # Wait for page content to load
            print("Waiting for page content to load...")
            max_wait = 30
            waited = 0
            while waited < max_wait:
                page_source = driver.page_source
                
                # Check if we have actual content - look for blog-articles-wrapper or blog-article-teaser
                blog_wrapper = driver.find_elements(By.CSS_SELECTOR, ".blog-articles-wrapper, .blog-article-teaser")
                articles = driver.find_elements(By.CSS_SELECTOR, ".lia-panel-message")
                
                if len(blog_wrapper) > 0 or len(articles) > 0 or len(page_source) > 20000:
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
            test_articles = temp_soup.find_all('div', class_='blog-article-teaser')
            print(f"[DEBUG] Found {len(test_articles)} blog-article-teaser elements in full HTML")
            
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
    
    def parse_relative_date(self, date_text: str) -> str:
        """
        Parse relative dates like "yesterday", "Monday", "10 hours ago", "a week ago", "3 weeks ago" into absolute dates.
        Also handles absolute dates like "10-17-2025", "09-24-2025".
        
        Args:
            date_text: Relative or absolute date string
            
        Returns:
            Date string in YYYY-MM-DD format, or original if parsing fails
        """
        date_text = date_text.strip()
        now = datetime.now()
        
        # Handle "yesterday"
        if 'yesterday' in date_text.lower():
            date_obj = now - timedelta(days=1)
            return date_obj.strftime('%Y-%m-%d')
        
        # Handle day names (Monday, Tuesday, etc.) - find the most recent occurrence
        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        for day_name in day_names:
            if day_name.lower() in date_text.lower():
                # Get the day of week for today (0=Monday, 6=Sunday)
                target_day = day_names.index(day_name)
                current_day = now.weekday()  # 0=Monday, 6=Sunday
                
                # Calculate days to subtract
                days_ago = (current_day - target_day) % 7
                if days_ago == 0:
                    # If it's the same day, assume it's from last week
                    days_ago = 7
                
                date_obj = now - timedelta(days=days_ago)
                return date_obj.strftime('%Y-%m-%d')
        
        # Handle relative dates
        if 'hour' in date_text.lower() or 'hours' in date_text.lower():
            match = re.search(r'(\d+)\s*hour', date_text, re.IGNORECASE)
            if match:
                hours = int(match.group(1))
                date_obj = now - timedelta(hours=hours)
                return date_obj.strftime('%Y-%m-%d')
        
        if 'day' in date_text.lower() or 'days' in date_text.lower():
            match = re.search(r'(\d+)\s*day', date_text, re.IGNORECASE)
            if match:
                days = int(match.group(1))
                date_obj = now - timedelta(days=days)
                return date_obj.strftime('%Y-%m-%d')
        
        if 'week' in date_text.lower() or 'weeks' in date_text.lower():
            match = re.search(r'(\d+)\s*week', date_text, re.IGNORECASE)
            if match:
                weeks = int(match.group(1))
                date_obj = now - timedelta(weeks=weeks)
                return date_obj.strftime('%Y-%m-%d')
            elif 'a week ago' in date_text.lower() or '1 week ago' in date_text.lower():
                date_obj = now - timedelta(weeks=1)
                return date_obj.strftime('%Y-%m-%d')
        
        if 'month' in date_text.lower() or 'months' in date_text.lower():
            match = re.search(r'(\d+)\s*month', date_text, re.IGNORECASE)
            if match:
                months = int(match.group(1))
                date_obj = now - timedelta(days=months * 30)
                return date_obj.strftime('%Y-%m-%d')
            elif 'a month ago' in date_text.lower() or '1 month ago' in date_text.lower():
                date_obj = now - timedelta(days=30)
                return date_obj.strftime('%Y-%m-%d')
        
        # Handle absolute dates in MM-DD-YYYY format
        date_patterns = [
            (r'(\d{1,2})-(\d{1,2})-(\d{4})', '%m-%d-%Y'),  # 10-17-2025
            (r'(\d{4})-(\d{1,2})-(\d{1,2})', '%Y-%m-%d'),  # 2025-10-17
            (r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})', None),  # Nov 10, 2025
            (r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})', None),  # 10 Nov 2025
        ]
        
        for pattern, date_format in date_patterns:
            match = re.search(pattern, date_text, re.IGNORECASE)
            if match:
                if date_format:
                    try:
                        date_obj = datetime.strptime(match.group(0), date_format)
                        return date_obj.strftime('%Y-%m-%d')
                    except ValueError:
                        continue
                else:
                    # Handle month name formats
                    month_map = {
                        'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
                        'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
                        'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12',
                        'January': '01', 'February': '02', 'March': '03', 'April': '04',
                        'May': '05', 'June': '06', 'July': '07', 'August': '08',
                        'September': '09', 'October': '10', 'November': '11', 'December': '12'
                    }
                    
                    groups = match.groups()
                    if len(groups) == 3:
                        if groups[0].isdigit():
                            # Format: 10 Nov 2025
                            day, month, year = groups
                            month_num = month_map.get(month[:3], '01')
                            return f"{year}-{month_num}-{day.zfill(2)}"
                        else:
                            # Format: Nov 10, 2025
                            month, day, year = groups
                            month_num = month_map.get(month[:3], '01')
                            return f"{year}-{month_num}-{day.zfill(2)}"
        
        # If no pattern matches, return original
        return date_text
    
    def extract_articles(self, html: str) -> List[Dict]:
        """
        Extract blog articles from HTML.
        Targets the structure: div.blog-articles-wrapper > div.blog-articles > div.lia-panel-message > div.blog-wrapper > div.blog-article-teaser
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with title, date, link, author
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Find the main blog articles container
        blog_articles_wrapper = soup.find('div', class_='blog-articles-wrapper')
        if blog_articles_wrapper:
            blog_articles = blog_articles_wrapper.find('div', class_='blog-articles')
            if blog_articles:
                # Find all message panels
                message_panels = blog_articles.find_all('div', class_='lia-panel-message')
            else:
                # Fallback: find message panels directly in wrapper
                message_panels = blog_articles_wrapper.find_all('div', class_='lia-panel-message')
        else:
            # Fallback: find all blog-article-teaser elements directly
            message_panels = []
            blog_teasers = soup.find_all('div', class_='blog-article-teaser')
            for teaser in blog_teasers:
                # Find parent message panel
                parent = teaser.find_parent('div', class_='lia-panel-message')
                if parent and parent not in message_panels:
                    message_panels.append(parent)
        
        print(f"[DEBUG] Found {len(message_panels)} message panel(s)")
        
        # Process each message panel
        for idx, panel in enumerate(message_panels):
            try:
                # Find the blog-article-teaser within this panel
                teaser = panel.find('div', class_='blog-article-teaser')
                if not teaser:
                    continue
                
                # Extract title and link from div.detail > div.headline > div.subject > a.message-link
                title = "N/A"
                link = "N/A"
                
                detail = teaser.find('div', class_='detail')
                if detail:
                    headline = detail.find('div', class_='headline')
                    if headline:
                        subject = headline.find('div', class_='subject')
                        if subject:
                            title_link = subject.find('a', class_='message-link')
                            if title_link:
                                title = title_link.get_text(strip=True)
                                href = title_link.get('href', '')
                                if href:
                                    # Make URL absolute
                                    if href.startswith('/'):
                                        link = f"https://community.hpe.com{href}"
                                    elif href.startswith('http'):
                                        link = href
                                    else:
                                        link = f"https://community.hpe.com/{href.lstrip('/')}"
                
                # If no title/link found, try alternative methods
                if title == "N/A" or link == "N/A":
                    # Try to find any link in the teaser
                    link_elem = teaser.find('a', href=True)
                    if link_elem:
                        href = link_elem.get('href', '')
                        if href:
                            if href.startswith('/'):
                                link = f"https://community.hpe.com{href}"
                            elif href.startswith('http'):
                                link = href
                            else:
                                link = f"https://community.hpe.com/{href.lstrip('/')}"
                        
                        if title == "N/A":
                            title = link_elem.get_text(strip=True)
                
                # Extract author from div.author-wrapper > div.author > a.profile-link
                author = "N/A"
                if detail:
                    author_wrapper = detail.find('div', class_='author-wrapper')
                    if author_wrapper:
                        author_div = author_wrapper.find('div', class_='author')
                        if author_div:
                            author_link = author_div.find('a', class_='profile-link')
                            if author_link:
                                author = author_link.get_text(strip=True)
                
                # Extract date from div.post-date
                date_text = "N/A"
                if detail:
                    post_date = detail.find('div', class_='post-date')
                    if post_date:
                        date_raw = post_date.get_text(strip=True)
                        # Parse relative dates to absolute
                        date_text = self.parse_relative_date(date_raw)
                
                # Skip if no valid link or title
                if link == "N/A" or title == "N/A" or len(title) < 5:
                    continue
                
                # Avoid duplicates
                if link in seen_links:
                    continue
                seen_links.add(link)
                
                articles.append({
                    'title': title,
                    'date': date_text,
                    'link': link,
                    'author': author
                })
                
                print(f"[DEBUG] Extracted article {idx+1}: {title[:50]}...")
                
            except Exception as e:
                print(f"[WARNING] Error processing panel {idx+1}: {e}")
                continue
        
        return articles
    
    def scrape(self, debug: bool = False) -> List[Dict]:
        """
        Main method to scrape all blog pages.
        
        Args:
            debug: If True, save extracted HTML to file for debugging
        
        Returns:
            List of structured article data from all pages
        """
        all_articles = []
        seen_links = set()
        
        for idx, url in enumerate(self.urls, 1):
            print(f"\n{'='*80}")
            print(f"Scraping page {idx}/{len(self.urls)}: {url}")
            print(f"{'='*80}")
            
            try:
                html = self.fetch_html(url=url)
                
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
                    
                    # Save to debug folder with page number
                    debug_filepath = debug_dir / f"debug_hpe_blog_page_{idx}_full_html.html"
                    with open(debug_filepath, "w", encoding="utf-8") as f:
                        f.write(html)
                    print(f"[DEBUG] Full HTML saved to {debug_filepath} ({len(html)} chars)")

                print("Extracting blog articles from HTML...")
                articles = self.extract_articles(html)
                
                # Filter out duplicates across pages
                new_articles = []
                for article in articles:
                    if article['link'] not in seen_links:
                        seen_links.add(article['link'])
                        new_articles.append(article)
                
                print(f"Found {len(new_articles)} new article(s) from this page")
                all_articles.extend(new_articles)
                
                # Small delay between pages to be respectful
                if idx < len(self.urls):
                    time.sleep(2)
                    
            except Exception as e:
                print(f"[ERROR] Failed to scrape {url}: {str(e)}")
                import traceback
                traceback.print_exc()
                continue
        
        print(f"\n{'='*80}")
        print(f"Total articles found across all pages: {len(all_articles)}")
        print(f"{'='*80}")
        
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
            print(f"  Title:  {article['title']}")
            print(f"  Date:   {article['date']}")
            print(f"  Author: {article.get('author', 'N/A')}")
            print(f"  Link:   {article['link']}")
            print("-" * 80)
    
    def save_to_json(self, articles: List[Dict], filename: str = "hpe_blog_articles.json"):
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
        scraper = HPEBlogScraper()
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

