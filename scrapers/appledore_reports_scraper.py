"""
Scraper for extracting structured data from Appledore Research reports page.
Extracts: title, date, link, description, authors, pages, status
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import time
import re
from typing import List, Dict
from pathlib import Path
from dotenv import load_dotenv
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Load environment variables
load_dotenv()


class AppledoreReportsScraper:
    def __init__(self):
        """Initialize the scraper."""
        self.url = "https://appledoreresearch.com/all-reports/?form_submitted=1&term_module=&term_type=&term_topic=&term_status=1672&text_search=&term_tag=&term_vendor=&term_author="
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def fetch_html(self, use_selenium: bool = True, load_all_pages: bool = True) -> str:
        """
        Fetch HTML content from the Appledore Research reports page.
        Uses Selenium to handle JavaScript-rendered content and infinite scroll.
        
        Args:
            use_selenium: If True, use Selenium (default). If False, use requests.
            load_all_pages: If True, click "Load more" to get all reports.
        
        Returns:
            HTML content as string
        """
        if use_selenium:
            return self._fetch_html_selenium(load_all_pages)
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
    
    def _fetch_html_selenium(self, load_all_pages: bool = True) -> str:
        """Fetch HTML using undetected-chromedriver and handle infinite scroll."""
        driver = None
        try:
            print("Initializing browser (this may take a moment)...")
            options = uc.ChromeOptions()
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--start-maximized')
            
            driver = uc.Chrome(options=options, version_main=None)
            
            print("Loading page...")
            driver.get(self.url)
            
            # Initial wait for page to load
            time.sleep(3)
            
            # Wait for the table to load
            print("Waiting for page content to load...")
            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".k-post-table__item--report"))
                )
                print("[OK] Table content loaded successfully!")
            except TimeoutException:
                print("[WARNING] Table not found, but continuing...")
            
            # Additional wait for JavaScript to fully render
            time.sleep(2)
            
            # Handle infinite scroll / "Load more" button
            if load_all_pages:
                print("Loading all pages...")
                max_clicks = 50  # Safety limit
                clicks = 0
                
                while clicks < max_clicks:
                    try:
                        # Look for "Load more" button or link
                        load_more_selectors = [
                            "a[href='#']:has(i.k-icon--plus-circled)",
                            "a:contains('Load more')",
                            ".k-post-table__footer a",
                            "a[href='#']",
                        ]
                        
                        load_more_button = None
                        for selector in load_more_selectors:
                            try:
                                if ":contains" in selector:
                                    # Find all links and check text
                                    links = driver.find_elements(By.CSS_SELECTOR, "a[href='#']")
                                    for link in links:
                                        if "load more" in link.text.lower():
                                            load_more_button = link
                                            break
                                else:
                                    load_more_button = driver.find_element(By.CSS_SELECTOR, selector)
                                    if load_more_button and "load more" in load_more_button.text.lower():
                                        break
                                    else:
                                        load_more_button = None
                            except NoSuchElementException:
                                continue
                        
                        if not load_more_button:
                            # Try finding by text content
                            try:
                                load_more_button = driver.find_element(By.XPATH, "//a[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'load more')]")
                            except NoSuchElementException:
                                pass
                        
                        if load_more_button:
                            # Scroll to button
                            driver.execute_script("arguments[0].scrollIntoView(true);", load_more_button)
                            time.sleep(1)
                            
                            # Check if button is visible and clickable
                            if load_more_button.is_displayed():
                                # Get current number of items
                                current_items = len(driver.find_elements(By.CSS_SELECTOR, ".k-post-table__item--report"))
                                
                                # Click the button
                                driver.execute_script("arguments[0].click();", load_more_button)
                                print(f"  Clicked 'Load more' (click {clicks + 1})...")
                                
                                # Wait for new content to load
                                time.sleep(3)
                                
                                # Check if new items were loaded
                                new_items = len(driver.find_elements(By.CSS_SELECTOR, ".k-post-table__item--report"))
                                if new_items == current_items:
                                    print("  No new items loaded. Reached end of list.")
                                    break
                                else:
                                    print(f"  Loaded {new_items - current_items} new items (total: {new_items})")
                                
                                clicks += 1
                            else:
                                print("  'Load more' button not visible. Reached end of list.")
                                break
                        else:
                            print("  No 'Load more' button found. All content loaded.")
                            break
                            
                    except Exception as e:
                        print(f"  Error while loading more: {str(e)}")
                        break
                
                print(f"Finished loading pages. Total clicks: {clicks}")
            
            # Final wait for any remaining content to load
            time.sleep(2)
            
            html = driver.page_source
            print(f"Retrieved HTML: {len(html)} characters")
            
            return html
        except Exception as e:
            raise Exception(f"Failed to fetch HTML with Selenium: {str(e)}")
        finally:
            if driver:
                print("Closing browser...")
                driver.quit()
    
    def parse_date(self, date_str: str) -> str:
        """
        Parse date string to YYYY-MM-DD format.
        
        Args:
            date_str: Date string in various formats (e.g., "28/10/2025", "Oct 28, 2025")
        
        Returns:
            Date in YYYY-MM-DD format, or original string if parsing fails
        """
        if not date_str or date_str.strip() == "":
            return "N/A"
        
        date_str = date_str.strip()
        
        # Try DD/MM/YYYY format (common in UK/Europe)
        match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', date_str)
        if match:
            day, month, year = match.groups()
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        
        # Try YYYY-MM-DD format
        match = re.search(r'(\d{4})-(\d{2})-(\d{2})', date_str)
        if match:
            return date_str
        
        # Try Month Day, Year format
        month_map = {
            'january': '01', 'february': '02', 'march': '03', 'april': '04',
            'may': '05', 'june': '06', 'july': '07', 'august': '08',
            'september': '09', 'october': '10', 'november': '11', 'december': '12',
            'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
            'may': '05', 'jun': '06', 'jul': '07', 'aug': '08',
            'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'
        }
        
        pattern = r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})'
        match = re.search(pattern, date_str, re.IGNORECASE)
        if match:
            month, day, year = match.groups()
            month_num = month_map.get(month.lower()[:3], '01')
            return f"{year}-{month_num}-{day.zfill(2)}"
        
        # Return original if no pattern matches
        return date_str
    
    def extract_reports(self, html: str) -> List[Dict]:
        """
        Extract report data from HTML.
        
        Args:
            html: Raw HTML content
        
        Returns:
            List of dictionaries with report info
        """
        soup = BeautifulSoup(html, 'html.parser')
        reports = []
        seen_links = set()
        
        # Find all report items
        report_items = soup.find_all('div', class_='k-post-table__item--report')
        print(f"[DEBUG] Found {len(report_items)} report items")
        
        for idx, item in enumerate(report_items):
            try:
                # Extract title and link
                title_col = item.find('div', class_='k-post-table__column--title')
                title = "N/A"
                link = "N/A"
                
                if title_col:
                    title_link = title_col.find('a', href=True)
                    if title_link:
                        title = title_link.get_text(strip=True)
                        link = title_link.get('href', '')
                        # Make URL absolute if needed
                        if link and not link.startswith('http'):
                            if link.startswith('/'):
                                link = f"https://appledoreresearch.com{link}"
                            else:
                                link = f"https://appledoreresearch.com/{link}"
                
                # Extract description
                desc_col = item.find('div', class_='k-post-table__column--excerpt')
                description = "N/A"
                if desc_col:
                    desc_inner = desc_col.find('div', class_='k-post-table__column-inner')
                    if desc_inner:
                        description = desc_inner.get_text(strip=True)
                
                # Extract details (Authors, Pages, Date)
                details_col = item.find('div', class_='k-post-table__column--details')
                authors = "N/A"
                pages = "N/A"
                date = "N/A"
                
                if details_col:
                    details_inner = details_col.find('div', class_='k-post-table__column-inner')
                    if details_inner:
                        details_text = details_inner.get_text()
                        
                        # Extract authors
                        authors_match = re.search(r'Authors?:\s*(.+?)(?:\n|Pages|Date|$)', details_text, re.IGNORECASE | re.DOTALL)
                        if authors_match:
                            authors = authors_match.group(1).strip()
                            # Clean up authors (remove extra whitespace, newlines)
                            authors = re.sub(r'\s+', ' ', authors).strip()
                        
                        # Extract pages
                        pages_match = re.search(r'Pages?:\s*(\d+)', details_text, re.IGNORECASE)
                        if pages_match:
                            pages = pages_match.group(1).strip()
                        
                        # Extract date
                        date_match = re.search(r'Date:\s*(.+?)(?:\n|$)', details_text, re.IGNORECASE)
                        if date_match:
                            date_raw = date_match.group(1).strip()
                            date = self.parse_date(date_raw)
                
                # Extract status
                status_col = item.find('div', class_='k-post-table__column--status')
                status = "N/A"
                if status_col:
                    status_inner = status_col.find('div', class_='k-post-table__column-inner')
                    if status_inner:
                        status = status_inner.get_text(strip=True)
                
                # Skip duplicates
                if link in seen_links:
                    continue
                seen_links.add(link)
                
                # Only add if we have at least a title or link
                if title != "N/A" or link != "N/A":
                    reports.append({
                        'title': title,
                        'date': date,
                        'link': link,
                        'description': description,
                        'authors': authors,
                        'pages': pages,
                        'status': status
                    })
                    
                    print(f"[DEBUG] Extracted report {idx+1}: {title[:50]}...")
            
            except Exception as e:
                print(f"[WARNING] Error extracting report {idx+1}: {str(e)}")
                continue
        
        return reports
    
    def scrape(self, debug: bool = False, load_all_pages: bool = True) -> List[Dict]:
        """
        Main method to scrape and analyze the page.
        
        Args:
            debug: If True, save extracted HTML to file for debugging
            load_all_pages: If True, load all pages via "Load more" button
        
        Returns:
            List of structured report data
        """
        print("Fetching HTML from Appledore Research reports page...")
        html = self.fetch_html(load_all_pages=load_all_pages)
        
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
            debug_filepath = debug_dir / "debug_appledore_reports_full_html.html"
            with open(debug_filepath, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[DEBUG] Full HTML saved to debug_appledore_reports_full_html.html ({len(html)} chars)")
        
        print("Extracting reports from HTML...")
        reports = self.extract_reports(html)
        print(f"Found {len(reports)} reports")
        
        return reports
    
    def display_results(self, reports: List[Dict]):
        """
        Display results in a structured format.
        
        Args:
            reports: List of report dictionaries
        """
        if not reports:
            print("\nNo reports found.")
            return
        
        print(f"\n{'='*80}")
        print(f"Found {len(reports)} report(s)")
        print(f"{'='*80}\n")
        
        for idx, report in enumerate(reports, 1):
            print(f"Report {idx}:")
            print(f"  Title:       {report['title']}")
            print(f"  Date:        {report['date']}")
            print(f"  Authors:     {report.get('authors', 'N/A')}")
            print(f"  Pages:       {report.get('pages', 'N/A')}")
            print(f"  Status:      {report.get('status', 'N/A')}")
            print(f"  Link:        {report['link']}")
            print(f"  Description: {report['description'][:100]}..." if len(report.get('description', '')) > 100 else f"  Description: {report.get('description', 'N/A')}")
            print("-" * 80)
    
    def save_to_json(self, reports: List[Dict], filename: str = "appledore_reports.json"):
        """
        Save results to JSON file in the project root.
        
        Args:
            reports: List of report dictionaries
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
            json.dump(reports, f, indent=2, ensure_ascii=False)
        print(f"Results saved to {filepath}")


def main():
    """Main entry point."""
    import sys
    
    # Check for debug flag
    debug = "--debug" in sys.argv or "-d" in sys.argv
    
    # Check for no-load-more flag
    load_all_pages = "--no-load-more" not in sys.argv
    
    try:
        scraper = AppledoreReportsScraper()
        reports = scraper.scrape(debug=debug, load_all_pages=load_all_pages)
        scraper.display_results(reports)
        scraper.save_to_json(reports)
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())

