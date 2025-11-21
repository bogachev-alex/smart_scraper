"""
Scraper for extracting structured data from TM Forum Inform articles.
Extracts: title, date, link, author, reading_time, topics, page_type, image_url
Scrapes from: https://inform.tmforum.org/
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

class TMForumScraper:
    def __init__(self, stop_date: Optional[datetime] = None):
        """
        Initialize the scraper.
        
        Args:
            stop_date: Stop loading more posts when reaching this date or earlier.
                      If None, defaults to June 1, 2025.
        """
        self.url = "https://inform.tmforum.org/"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        # Default stop date: May 31, 2025 (end of May 2025)
        self.stop_date = stop_date or datetime(2025, 5, 31)
    
    def _parse_date(self, date_str: str, assume_year: Optional[int] = None) -> Optional[datetime]:
        """
        Parse date string to datetime object.
        On TM Forum, dates like "May 25" mean "May 2025" (month and year, no specific day).
        We'll use the first day of the month for comparison purposes.
        
        Args:
            date_str: Date string to parse (e.g., "May 25" means May 2025)
            assume_year: Year to assume if not specified. If None, tries both current and previous year.
            
        Returns:
            datetime object (first day of the month) or None if parsing fails
        """
        if not date_str or date_str == "N/A":
            return None
        
        date_str = date_str.strip()
        
        # Try formats with explicit year first
        date_formats_with_year = [
            "%b %d %Y",                   # "Nov 25 2025"
            "%B %d %Y",                    # "November 25 2025"
            "%m/%d/%Y",                    # "11/25/2025"
            "%Y-%m-%d",                    # "2025-11-25"
            "%d %B %Y",                    # "25 November 2025"
            "%d %b %Y",                    # "25 Nov 2025"
        ]
        
        for fmt in date_formats_with_year:
            try:
                parsed = datetime.strptime(date_str, fmt)
                # Use first day of month for comparison
                return parsed.replace(day=1)
            except ValueError:
                continue
        
        # Try formats without year - "May 25" means "May 2025" (month and year)
        date_formats_no_year = [
            "%b %d",                       # "May 25" -> May 2025
            "%B %d",                       # "May 25" -> May 2025
        ]
        
        for fmt in date_formats_no_year:
            try:
                parsed = datetime.strptime(date_str, fmt)
                
                # Extract year from the date string (the number after month)
                # "May 25" -> year is 25, but we interpret as 2025
                parts = date_str.split()
                if len(parts) >= 2:
                    year_part = parts[1]
                    try:
                        # Try to parse as year (e.g., "25" -> 2025, "24" -> 2024)
                        year_num = int(year_part)
                        if year_num < 100:
                            # Two-digit year, assume 2000s
                            year = 2000 + year_num
                        else:
                            year = year_num
                        
                        # Use first day of month
                        parsed = parsed.replace(year=year, day=1)
                        return parsed
                    except ValueError:
                        pass
                
                # Fallback: use assume_year if provided
                if assume_year is not None:
                    parsed = parsed.replace(year=assume_year, day=1)
                    return parsed
                
                # Otherwise, try both current year and previous year
                current_year = datetime.now().year
                previous_year = current_year - 1
                
                # Try current year first
                parsed_current = parsed.replace(year=current_year, day=1)
                # If the month hasn't passed yet this year, use current year
                if parsed_current <= datetime.now().replace(day=1):
                    return parsed_current
                
                # Otherwise, try previous year
                parsed_previous = parsed.replace(year=previous_year, day=1)
                return parsed_previous
                
            except ValueError:
                continue
        
        # If dateutil is available, try it as a fallback
        if HAS_DATEUTIL:
            try:
                default_year = assume_year if assume_year else datetime.now().year
                parsed_date = date_parser.parse(date_str, default=datetime(default_year, 1, 1))
                # Use first day of month
                return parsed_date.replace(day=1)
            except (ValueError, TypeError):
                pass
        
        return None
    
    def _check_if_reached_stop_date(self, html: str) -> bool:
        """
        Check if we've reached the stop date by parsing dates from the HTML.
        Stop date is May 31, 2025 (end of May 2025).
        On TM Forum, "May 25" means May 2025 (month and year).
        We stop when the OLDEST articles are from May 2025 or earlier.
        
        Args:
            html: HTML content to check
            
        Returns:
            True if we've reached or passed the stop date
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles_container = soup.find('div', class_=lambda x: x and 'HomepageArticles_containerArticles' in str(x))
        if not articles_container:
            return False
        
        article_items = articles_container.find_all('div', class_=lambda x: x and 'HomepageArticles_item' in str(x))
        
        if len(article_items) < 5:
            # Not enough articles to make a decision, continue loading
            return False
        
        # Check the LAST 20 (oldest) articles to see if we've reached the stop date
        # We want to continue loading until the oldest articles are from May 2025 or earlier
        articles_to_check = article_items[-20:] if len(article_items) >= 20 else article_items[-10:]
        
        # Count how many of the oldest articles are from May 2025 or earlier
        articles_at_or_before_stop = 0
        articles_after_stop = 0
        
        for item in reversed(articles_to_check):  # Check from oldest to newest
            # Find date element
            date_span = item.find('span', class_=lambda x: x and 'Date_date' in str(x) and 'Date_articleDate' in str(x))
            if date_span:
                date_str = date_span.get_text(strip=True)
                
                # Parse the date (handles "May 25" as May 2025)
                parsed_date = self._parse_date(date_str)
                
                if parsed_date:
                    if parsed_date <= self.stop_date:
                        articles_at_or_before_stop += 1
                    else:
                        articles_after_stop += 1
        
        # Only stop if we have at least 5 articles from May 2025 or earlier in the oldest articles
        # This ensures we've actually reached May 2025, not just found a few mixed in
        if articles_at_or_before_stop >= 5 and articles_after_stop == 0:
            print(f"  Found {articles_at_or_before_stop} articles from May 2025 or earlier in the oldest articles. Stopping.")
            return True
        
        # If we have some articles after stop date, continue loading
        if articles_after_stop > 0:
            return False
        
        # If we don't have enough data, continue loading
        return False
    
    def fetch_html(self, load_all_pages: bool = True, max_clicks: int = 100) -> str:
        """
        Fetch HTML content from the TM Forum Inform page.
        Uses Selenium to handle JavaScript-rendered content and "Load More" button.
        
        Args:
            load_all_pages: If True, click "Load More" button to load all content
            max_clicks: Maximum number of "Load More" button clicks
        
        Returns:
            HTML content as string
        """
        return self._fetch_html_selenium(load_all_pages=load_all_pages, max_clicks=max_clicks)
    
    def _fetch_html_selenium(self, load_all_pages: bool = True, max_clicks: int = 100) -> str:
        """
        Fetch HTML using undetected-chromedriver to handle JavaScript rendering
        and "Load More" button clicking.
        
        Args:
            load_all_pages: If True, click "Load More" button to load all content
            max_clicks: Maximum number of "Load More" button clicks
        
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
            
            # Handle cookie consent alert if present
            try:
                time.sleep(2)  # Wait a bit for alert to appear
                alert = driver.switch_to.alert
                alert_text = alert.text
                print(f"Cookie consent alert detected: {alert_text[:50]}...")
                alert.accept()  # Accept the alert
                print("Cookie consent accepted.")
                time.sleep(1)
            except Exception:
                # No alert present, continue
                pass
            
            # Wait for page content to load
            print("Waiting for page content to load...")
            max_wait = 30
            waited = 0
            while waited < max_wait:
                # Handle any alerts that might appear
                try:
                    alert = driver.switch_to.alert
                    alert.accept()
                    time.sleep(1)
                except Exception:
                    pass
                
                page_source = driver.page_source
                
                # Check if we have actual content - look for articles container
                try:
                    articles_container = driver.find_elements(By.CSS_SELECTOR, "[class*='HomepageArticles_containerArticles']")
                    article_items = driver.find_elements(By.CSS_SELECTOR, "[class*='HomepageArticles_item']")
                    
                    if len(articles_container) > 0 or len(article_items) > 0 or len(page_source) > 50000:
                        print(f"[OK] Content loaded successfully! ({len(article_items)} articles found)")
                        break
                except Exception as e:
                    # If we get an alert exception, try to handle it
                    try:
                        alert = driver.switch_to.alert
                        alert.accept()
                        time.sleep(1)
                    except Exception:
                        pass
                
                time.sleep(2)
                waited += 2
                if waited % 4 == 0:
                    print(f"  Still waiting... ({waited}s)")
            
            # Additional wait for JavaScript to fully render
            time.sleep(3)
            
            # Handle "Load More" button clicking
            if load_all_pages:
                print(f"Loading articles until reaching {self.stop_date.strftime('%B %Y')} or earlier...")
                clicks = 0
                try:
                    last_article_count = len(driver.find_elements(By.CSS_SELECTOR, "[class*='HomepageArticles_item']"))
                except Exception:
                    # Handle alert if present
                    try:
                        alert = driver.switch_to.alert
                        alert.accept()
                        time.sleep(1)
                        last_article_count = len(driver.find_elements(By.CSS_SELECTOR, "[class*='HomepageArticles_item']"))
                    except Exception:
                        last_article_count = 0
                
                while clicks < max_clicks:
                    try:
                        # Look for "Load More" button
                        load_more_button = None
                        try:
                            # Try to find button by text content
                            load_more_button = driver.find_element(By.XPATH, "//button[contains(text(), 'Load More')]")
                        except NoSuchElementException:
                            # Fallback: try finding by class
                            try:
                                button_container = driver.find_element(By.CSS_SELECTOR, "[class*='HomepageArticles_articlesButton']")
                                load_more_button = button_container.find_element(By.TAG_NAME, "button")
                            except NoSuchElementException:
                                pass
                        
                        if load_more_button and load_more_button.is_displayed():
                            # Scroll to button
                            driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", load_more_button)
                            time.sleep(2)
                            
                            # Click using JavaScript to avoid interception
                            driver.execute_script("arguments[0].click();", load_more_button)
                            clicks += 1
                            
                            print(f"  Clicked 'Load More' button (click {clicks}/{max_clicks})...")
                            
                            # Handle any alerts that might appear
                            try:
                                time.sleep(1)
                                alert = driver.switch_to.alert
                                alert.accept()
                            except Exception:
                                pass
                            
                            # Wait for new content to load - wait until article count increases or timeout
                            print(f"  Waiting for new articles to load...")
                            wait_start = time.time()
                            max_wait_time = 10  # Wait up to 10 seconds for new content
                            new_articles_loaded = False
                            
                            while time.time() - wait_start < max_wait_time:
                                try:
                                    current_article_count = len(driver.find_elements(By.CSS_SELECTOR, "[class*='HomepageArticles_item']"))
                                    if current_article_count > last_article_count:
                                        new_articles_loaded = True
                                        break
                                    time.sleep(1)
                                except Exception:
                                    # Handle alert if present
                                    try:
                                        alert = driver.switch_to.alert
                                        alert.accept()
                                        time.sleep(1)
                                    except Exception:
                                        pass
                            
                            # Final check for article count
                            try:
                                current_article_count = len(driver.find_elements(By.CSS_SELECTOR, "[class*='HomepageArticles_item']"))
                            except Exception:
                                # Handle alert if present
                                try:
                                    alert = driver.switch_to.alert
                                    alert.accept()
                                    time.sleep(1)
                                    current_article_count = len(driver.find_elements(By.CSS_SELECTOR, "[class*='HomepageArticles_item']"))
                                except Exception:
                                    current_article_count = last_article_count
                            
                            if current_article_count == last_article_count:
                                if new_articles_loaded:
                                    print(f"  Articles loaded but count didn't change. Continuing...")
                                else:
                                    print(f"  No new articles loaded after {max_wait_time}s. Stopping.")
                                    break
                            
                            articles_added = current_article_count - last_article_count
                            last_article_count = current_article_count
                            print(f"  Total articles loaded: {current_article_count} (added {articles_added} new)")
                            
                            # Check again after loading new content
                            current_html = driver.page_source
                            if self._check_if_reached_stop_date(current_html):
                                print(f"  Reached stop date ({self.stop_date.strftime('%B %Y')}). Stopping.")
                                break
                        else:
                            print("  'Load More' button not visible. Stopping.")
                            break
                            
                    except NoSuchElementException:
                        print("  'Load More' button not found. All articles may be loaded.")
                        break
                    except Exception as e:
                        print(f"  Error clicking 'Load More' button: {e}")
                        break
                
                print(f"Finished loading articles. Total clicks: {clicks}")
            
            # Final scroll to bottom to ensure all content is loaded
            print("Performing final scroll to ensure all articles are loaded...")
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)
            
            # Scroll back up a bit and wait
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
            time.sleep(2)
            
            # Scroll to bottom again
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            # Verify article count using Selenium before getting page source
            try:
                final_article_count = len(driver.find_elements(By.CSS_SELECTOR, "[class*='HomepageArticles_item']"))
                print(f"[VERIFY] Selenium found {final_article_count} article elements in DOM")
            except Exception as e:
                print(f"[WARNING] Could not verify article count: {e}")
            
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
        Targets HomepageArticles_item elements.
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with title, date, link, author, reading_time, topics, page_type, image_url
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Find all article items - use multiple strategies to ensure we get all articles
        article_items = []
        
        # Strategy 1: Find by container first
        articles_container = soup.find('div', class_=lambda x: x and 'HomepageArticles_containerArticles' in str(x))
        if articles_container:
            article_items = articles_container.find_all('div', class_=lambda x: x and 'HomepageArticles_item' in str(x))
        
        # Strategy 2: If container method didn't find many, try finding all items directly
        if len(article_items) < 10:
            all_items = soup.find_all('div', class_=lambda x: x and 'HomepageArticles_item' in str(x))
            if len(all_items) > len(article_items):
                article_items = all_items
        
        # Strategy 3: Find by h4 with text-xl class (article titles)
        if len(article_items) < 10:
            title_elements = soup.find_all('h4', class_='text-xl')
            # Get parent divs that contain these titles
            for title_elem in title_elements:
                parent_item = title_elem.find_parent('div', class_=lambda x: x and 'HomepageArticles_item' in str(x))
                if parent_item and parent_item not in article_items:
                    article_items.append(parent_item)
        
        print(f"[DEBUG] Found {len(article_items)} article item(s)")
        
        # Also count articles by looking for links to article pages
        article_links = soup.find_all('a', href=lambda x: x and ('/features-and-opinion/' in str(x) or '/research-and-analysis/' in str(x) or '/videos/' in str(x) or '/webinars-and-podcasts/' in str(x)))
        unique_article_links = set()
        for link in article_links:
            href = link.get('href', '')
            if href and href.startswith('/'):
                unique_article_links.add(href)
        print(f"[DEBUG] Found {len(unique_article_links)} unique article links in HTML")
        
        # Process each article item
        for idx, item in enumerate(article_items):
            try:
                # Extract title and link
                title = "N/A"
                link = "N/A"
                
                title_elem = item.find('h4', class_='text-xl')
                if title_elem:
                    # Find the link (could be in title_elem or parent)
                    link_tag = title_elem.find('a')
                    if not link_tag:
                        # Try finding link in parent
                        parent_link = title_elem.find_parent('a')
                        if parent_link:
                            link_tag = parent_link
                    
                    if link_tag:
                        link = link_tag.get('href', '')
                        if link:
                            # Make URL absolute if needed
                            if link.startswith('/'):
                                link = f"https://inform.tmforum.org{link}"
                            elif not link.startswith('http'):
                                link = f"https://inform.tmforum.org/{link.lstrip('/')}"
                        
                        title = title_elem.get_text(strip=True)
                
                # Skip if no valid link or title
                if link == "N/A" or title == "N/A" or len(title) < 5:
                    continue
                
                # Avoid duplicates
                if link in seen_links:
                    continue
                seen_links.add(link)
                
                # Extract date
                date_text = "N/A"
                date_span = item.find('span', class_=lambda x: x and 'Date_date' in str(x) and 'Date_articleDate' in str(x))
                if date_span:
                    date_text = date_span.get_text(strip=True)
                
                # Extract author
                author = "N/A"
                author_span = item.find('span', class_=lambda x: x and 'Author_author' in str(x))
                if author_span:
                    author_text = author_span.get_text(strip=True)
                    # Remove " | BY " prefix if present
                    if " | BY " in author_text:
                        author = author_text.split(" | BY ")[-1].strip()
                    elif "BY " in author_text:
                        author = author_text.split("BY ")[-1].strip()
                    else:
                        author = author_text.strip()
                
                # Extract reading time
                reading_time = "N/A"
                reading_time_span = item.find('span', class_=lambda x: x and 'ReadingTime_readingTimeContant' in str(x))
                if reading_time_span:
                    reading_time = reading_time_span.get_text(strip=True)
                    # Remove "Reading time: " prefix if present
                    if "Reading time: " in reading_time:
                        reading_time = reading_time.replace("Reading time: ", "").strip()
                
                # Extract topics/categories
                topics = []
                topics_div = item.find('div', class_=lambda x: x and 'Topics_topics' in str(x))
                if topics_div:
                    topic_links = topics_div.find_all('a', href=True)
                    for topic_link in topic_links:
                        topic_text = topic_link.get_text(strip=True)
                        if topic_text and topic_text not in topics:
                            topics.append(topic_text)
                
                # Extract page type (Article, eBook, Case Study, etc.)
                page_type = "N/A"
                page_type_span = item.find('span', class_=lambda x: x and 'Topics_pageType' in str(x))
                if page_type_span:
                    page_type_text = page_type_span.get_text(strip=True)
                    # Remove " | " suffix if present
                    if page_type_text.endswith(" |"):
                        page_type = page_type_text[:-2].strip()
                    elif page_type_text.endswith(" | "):
                        page_type = page_type_text[:-3].strip()
                    elif " | " in page_type_text:
                        page_type = page_type_text.split(" | ")[0].strip()
                    elif " |" in page_type_text:
                        page_type = page_type_text.split(" |")[0].strip()
                    else:
                        page_type = page_type_text.strip()
                
                # Extract image URL
                image_url = "N/A"
                img_tag = item.find('img')
                if img_tag:
                    # Try src attribute first
                    if img_tag.get('src'):
                        image_url = img_tag.get('src')
                        # Make URL absolute if needed
                        if image_url.startswith('/'):
                            image_url = f"https://inform.tmforum.org{image_url}"
                        elif not image_url.startswith('http'):
                            image_url = f"https://inform.tmforum.org/{image_url.lstrip('/')}"
                    # Fallback to alt attribute which might contain the URL
                    elif img_tag.get('alt') and img_tag.get('alt').startswith('http'):
                        image_url = img_tag.get('alt')
                
                articles.append({
                    'title': title,
                    'date': date_text,
                    'link': link,
                    'author': author,
                    'reading_time': reading_time,
                    'topics': topics,
                    'page_type': page_type,
                    'image_url': image_url
                })
                
                print(f"[DEBUG] Extracted article {idx+1}: {title[:50]}...")
                
            except Exception as e:
                print(f"[WARNING] Error processing article item {idx+1}: {e}")
                continue
        
        return articles
    
    def scrape(self, debug: bool = False, load_all_pages: bool = True, max_clicks: int = 100) -> List[Dict]:
        """
        Main method to scrape the TM Forum Inform page.
        
        Args:
            debug: If True, save extracted HTML to file for debugging
            load_all_pages: If True, click "Load More" button to load all content
            max_clicks: Maximum number of "Load More" button clicks
        
        Returns:
            List of structured article data
        """
        print("Fetching HTML from TM Forum Inform page...")
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
            debug_filepath = debug_dir / "debug_tmforum_full_html.html"
            with open(debug_filepath, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[DEBUG] Full HTML saved to {debug_filepath} ({len(html)} chars)")
        
        print("Extracting articles from HTML...")
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
        
        # Set UTF-8 encoding for stdout to handle special characters
        import sys
        import io
        if sys.stdout.encoding != 'utf-8':
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        
        for idx, article in enumerate(articles, 1):
            try:
                print(f"Article {idx}:")
                print(f"  Title:        {article['title']}")
                print(f"  Page Type:    {article.get('page_type', 'N/A')}")
                print(f"  Author:       {article.get('author', 'N/A')}")
                print(f"  Date:         {article.get('date', 'N/A')}")
                print(f"  Reading Time: {article.get('reading_time', 'N/A')}")
                print(f"  Topics:       {', '.join(article.get('topics', [])) if article.get('topics') else 'N/A'}")
                print(f"  Link:         {article['link']}")
                if article.get('image_url') != "N/A":
                    print(f"  Image URL:    {article['image_url']}")
                print("-" * 80)
            except UnicodeEncodeError:
                # Skip articles with encoding issues
                print(f"Article {idx}: [Encoding error - article saved to JSON]")
                print("-" * 80)
    
    def save_to_json(self, articles: List[Dict], filename: str = "tmforum_articles.json"):
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
    max_clicks = 100
    for arg in sys.argv:
        if arg.startswith("--max-clicks="):
            try:
                max_clicks = int(arg.split("=")[1])
            except ValueError:
                print(f"Invalid max-clicks value, using default: 100")
    
    # Parse stop date if provided
    stop_date = None
    for arg in sys.argv:
        if arg.startswith("--stop-date="):
            try:
                date_str = arg.split("=")[1]
                stop_date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                print(f"Invalid stop-date format, using default: June 1, 2025")
                print("Expected format: --stop-date=2025-06-01")
    
    try:
        scraper = TMForumScraper(stop_date=stop_date)
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

