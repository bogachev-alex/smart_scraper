"""
Scraper for extracting structured data from Arthur D. Little insights page.
Extracts: title, date, link, description, read_time, type
Filters by: Telecommunications, Information technology, Media & Electronics (TIME)
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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Load environment variables
load_dotenv()

class ADLInsightsScraper:
    def __init__(self):
        """Initialize the scraper."""
        self.url = "https://www.adlittle.com/en/insights"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        self.time_industry_value = "48"  # Value for TIME industry filter
    
    def fetch_html(self, use_selenium: bool = True) -> str:
        """
        Fetch HTML content from the ADL insights page with TIME filter applied.
        Uses Selenium to handle JavaScript-rendered content and apply filter.
        
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
        """Fetch HTML using requests library (may not work due to JS filtering)."""
        try:
            response = requests.get(self.url, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            raise Exception(f"Failed to fetch HTML: {str(e)}")
    
    def _fetch_html_selenium(self) -> str:
        """Fetch HTML using undetected-chromedriver and apply TIME filter."""
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
            print("Waiting for page to load...")
            time.sleep(5)
            
            # Find and select the TIME industry filter
            print("Applying TIME industry filter...")
            try:
                # Wait for the select element to be present
                wait = WebDriverWait(driver, 20)
                industry_select = wait.until(
                    EC.presence_of_element_located((By.ID, "edit-field-industries-target-id"))
                )
                
                # Scroll to the select element to ensure it's visible
                driver.execute_script("arguments[0].scrollIntoView(true);", industry_select)
                time.sleep(1)
                
                # Select the TIME industry option (value="48")
                from selenium.webdriver.support.ui import Select
                select = Select(industry_select)
                select.select_by_value(self.time_industry_value)
                
                print("Filter applied. Waiting for results to load...")
                time.sleep(5)  # Wait for filtered results to load
                
            except (TimeoutException, NoSuchElementException) as e:
                print(f"[WARNING] Could not find or interact with filter dropdown: {e}")
                print("Continuing without filter...")
            
            # Wait for insights content to load
            print("Waiting for insights content to load...")
            max_wait = 30
            waited = 0
            while waited < max_wait:
                page_source = driver.page_source
                
                # Check if we have insights content
                insights_container = driver.find_elements(By.CSS_SELECTOR, ".insights-container")
                insight_cards = driver.find_elements(By.CSS_SELECTOR, ".insights-container .col-xl-3, .insights-container .col-xl-4")
                
                if len(insights_container) > 0 and len(insight_cards) > 0:
                    print(f"[OK] Content loaded successfully! Found {len(insight_cards)} insight cards")
                    break
                
                time.sleep(2)
                waited += 2
                if waited % 4 == 0:
                    print(f"  Still waiting... ({waited}s)")
            
            # Try to click "Load More" button to get all results
            print("Checking for 'Load More' button...")
            try:
                load_more_button = driver.find_element(By.CSS_SELECTOR, ".load-more-btn")
                if load_more_button.is_displayed() and load_more_button.is_enabled():
                    print("Clicking 'Load More' button to load additional results...")
                    # Scroll to button and use JavaScript click to avoid interception
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", load_more_button)
                    time.sleep(2)
                    # Use JavaScript click instead of regular click to avoid interception
                    driver.execute_script("arguments[0].click();", load_more_button)
                    time.sleep(5)  # Wait for additional content to load
                    
                    # Keep clicking until no more content loads
                    max_clicks = 10
                    clicks = 0
                    while clicks < max_clicks:
                        try:
                            load_more_button = driver.find_element(By.CSS_SELECTOR, ".load-more-btn")
                            if load_more_button.is_displayed() and load_more_button.is_enabled():
                                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", load_more_button)
                                time.sleep(2)
                                driver.execute_script("arguments[0].click();", load_more_button)
                                time.sleep(5)
                                clicks += 1
                                print(f"  Loaded more content (click {clicks}/{max_clicks})...")
                            else:
                                break
                        except (NoSuchElementException, Exception):
                            break
            except (NoSuchElementException, Exception) as e:
                print(f"[INFO] No 'Load More' button found or already loaded all content: {e}")
            
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
            test_cards = temp_soup.find_all('div', class_='insights-container')
            print(f"[DEBUG] Found insights-container in HTML")
            
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
        Targets the structure: div.insights-container > div.row > div.col-xl-3/col-xl-4
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with title, date, link, description, read_time, type
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Find the main insights container
        insights_container = soup.find('div', class_='insights-container')
        if not insights_container:
            print("[WARNING] Could not find div.insights-container")
            return articles
        
        # Find all insight cards (they can be in col-xl-3, col-xl-4, or col-xl-12 with special layout)
        cards = insights_container.find_all('div', class_=lambda x: x and ('col-xl-3' in x or 'col-xl-4' in x or 'col-xl-12' in x))
        
        print(f"[DEBUG] Found {len(cards)} insight card elements")
        
        # Process each card
        for idx, card in enumerate(cards):
            try:
                # Extract title from h5 or h3 tag
                title = "N/A"
                title_elem = card.find('h5')
                if not title_elem:
                    title_elem = card.find('h3')
                
                href = ""
                if title_elem:
                    title_link = title_elem.find('a')
                    if title_link:
                        title = title_link.get_text(strip=True)
                        href = title_link.get('href', '')
                    else:
                        title = title_elem.get_text(strip=True)
                
                # If no title link found, try to find the main article link
                # Look for "Find out more" link or any link to /en/insights/
                if not href or '/en/insights/' not in href:
                    find_more_link = card.find('a', class_='find-more-button')
                    if find_more_link:
                        href = find_more_link.get('href', '')
                    
                    # If still no link, find any link to insights
                    if not href or '/en/insights/' not in href:
                        all_links = card.find_all('a', href=True)
                        for link in all_links:
                            link_href = link.get('href', '')
                            if '/en/insights/' in link_href and '/en/industries/' not in link_href:
                                href = link_href
                                if title == "N/A":
                                    title = link.get_text(strip=True)
                                break
                
                # Skip if no valid link found or if it's an industry link
                if not href or '/en/industries/' in href:
                    continue
                
                # Make URL absolute
                if href.startswith('/'):
                    full_url = f"https://www.adlittle.com{href}"
                elif href.startswith('http'):
                    full_url = href
                else:
                    continue
                
                # Avoid duplicates
                if full_url in seen_links:
                    continue
                seen_links.add(full_url)
                
                # Extract description from p tag (not in topics or bottom div)
                description = "N/A"
                p_tags = card.find_all('p')
                for p in p_tags:
                    # Skip if it's in topics or bottom div
                    if p.find_parent('div', class_='topics') or p.find_parent('div', class_='bottom'):
                        continue
                    text = p.get_text(strip=True)
                    if text and len(text) > 20:  # Likely the description
                        description = text
                        break
                
                # Extract read time and type/date
                read_time = "N/A"
                article_type = "N/A"
                date_text = "N/A"
                
                # Look for the row with read time and type/date
                row_g0 = card.find('div', class_='row g-0')
                if not row_g0:
                    # Try alternative structure - look for row without g-0 class
                    row_g0 = card.find('div', class_='row')
                
                if row_g0:
                    cols = row_g0.find_all('div', class_='col')
                    if len(cols) >= 2:
                        # First col usually has read time
                        read_time_text = cols[0].get_text(strip=True)
                        if 'min read' in read_time_text.lower():
                            read_time = read_time_text
                        
                        # Second col has type and date
                        type_date_text = cols[1].get_text(strip=True)
                        if '•' in type_date_text:
                            parts = type_date_text.split('•')
                            if len(parts) == 2:
                                article_type = parts[0].strip()
                                date_raw = parts[1].strip()
                                
                                # Parse date like "September 2025" or "Sep 2025"
                                date_patterns = [
                                    r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})',
                                    r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})',
                                ]
                                for pattern in date_patterns:
                                    match = re.search(pattern, date_raw, re.IGNORECASE)
                                    if match:
                                        month = match.group(1)
                                        year = match.group(2)
                                        month_map = {
                                            'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
                                            'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
                                            'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12',
                                            'January': '01', 'February': '02', 'March': '03', 'April': '04',
                                            'May': '05', 'June': '06', 'July': '07', 'August': '08',
                                            'September': '09', 'October': '10', 'November': '11', 'December': '12'
                                        }
                                        month_num = month_map.get(month[:3], '01')
                                        # Use first day of month since we don't have day
                                        date_text = f"{year}-{month_num}-01"
                                        break
                                if date_text == "N/A":
                                    date_text = date_raw
                
                # Extract image URL if available
                image_url = "N/A"
                img_elem = card.find('img')
                if img_elem:
                    image_url = img_elem.get('src', '')
                    if image_url and not image_url.startswith('http'):
                        image_url = f"https://www.adlittle.com{image_url}"
                
                articles.append({
                    'title': title,
                    'date': date_text,
                    'link': full_url,
                    'description': description,
                    'read_time': read_time,
                    'type': article_type,
                    'image_url': image_url
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
        print("Fetching HTML from ADL insights page...")
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
            debug_filepath = debug_dir / "debug_adl_insights_full_html.html"
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
            print(f"  Title:       {article['title']}")
            print(f"  Date:        {article['date']}")
            print(f"  Type:        {article['type']}")
            print(f"  Read Time:   {article['read_time']}")
            print(f"  Link:        {article['link']}")
            print(f"  Description: {article['description'][:100]}..." if len(article['description']) > 100 else f"  Description: {article['description']}")
            print("-" * 80)
    
    def save_to_json(self, articles: List[Dict], filename: str = "adl_insights_articles.json"):
        """
        Save results to JSON file in the project root.
        
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
    
    try:
        scraper = ADLInsightsScraper()
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

