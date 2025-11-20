"""
Scraper for extracting structured data from Cisco blog page.
Extracts: title, date, link, description
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
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class CiscoBlogScraper:
    def __init__(self):
        """
        Initialize the scraper.
        """
        self.url = "https://blogs.cisco.com/"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def fetch_html(self, use_selenium: bool = False) -> str:
        """
        Fetch HTML content from the Cisco blog page.
        Uses Selenium if needed to handle JavaScript-rendered content.
        
        Args:
            use_selenium: If True, use Selenium. If False, try requests first.
        
        Returns:
            HTML content as string
        """
        if use_selenium:
            return self._fetch_html_selenium()
        else:
            # Try requests first
            try:
                return self._fetch_html_requests()
            except Exception as e:
                print(f"Requests failed: {e}")
                print("Trying with Selenium...")
                return self._fetch_html_selenium()
    
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
            
            # Wait for content to load
            print("Waiting for page content to load...")
            time.sleep(5)
            
            # Wait for blog cards to appear
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".blog-card"))
                )
                print("[OK] Blog cards loaded!")
            except:
                print("[WARNING] Blog cards not found, but continuing...")
            
            # Additional wait for JavaScript to fully render
            time.sleep(3)
            
            html = driver.page_source
            print(f"Retrieved HTML: {len(html)} characters")
            
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
        Extract blog articles from HTML using BeautifulSoup.
        Targets blog-card elements within the cui section.
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with title, link, description
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Find the main section with class "cui section"
        main_section = soup.find('div', class_=lambda x: x and 'cui' in str(x) and 'section' in str(x))
        
        if not main_section:
            # Fallback: find all blog-card elements directly
            blog_cards = soup.find_all('div', class_=lambda x: x and 'blog-card' in str(x))
        else:
            # Find all blog-card elements within the section
            blog_cards = main_section.find_all('div', class_=lambda x: x and 'blog-card' in str(x))
        
        print(f"[DEBUG] Found {len(blog_cards)} blog card(s)")
        
        # Process each blog card
        for idx, card in enumerate(blog_cards):
            # Extract title and link from card-link > h4
            title = "N/A"
            link = "N/A"
            
            card_link = card.find('a', class_='card-link')
            if card_link:
                href = card_link.get('href', '')
                if href:
                    # Make URL absolute if needed
                    if href.startswith('/'):
                        link = f"https://blogs.cisco.com{href}"
                    elif href.startswith('http'):
                        link = href
                    else:
                        link = f"https://blogs.cisco.com/{href.lstrip('/')}"
                
                # Find h4 with title
                h4 = card_link.find('h4', class_=lambda x: x and 'base-margin-bottom' in str(x))
                if h4:
                    title = h4.get_text(strip=True)
                elif card_link:
                    # Fallback: use link text
                    title = card_link.get_text(strip=True)
            
            # If no title found, try alternative methods
            if title == "N/A" or len(title) < 5:
                # Try to find any h4 in the card
                h4_alt = card.find('h4')
                if h4_alt:
                    title = h4_alt.get_text(strip=True)
            
            # Extract description from card-paragraph
            description = "N/A"
            desc_elem = card.find('p', class_='card-paragraph')
            if desc_elem:
                description = desc_elem.get_text(strip=True)
            
            # Extract date - look for date patterns in card text
            date_text = "N/A"
            card_text = card.get_text()
            date_patterns = [
                r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',
                r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b',
                r'\b\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b',
                r'\b\d{4}-\d{2}-\d{2}\b',
                r'\b\d{1,2}/\d{1,2}/\d{4}\b',
            ]
            for pattern in date_patterns:
                match = re.search(pattern, card_text, re.IGNORECASE)
                if match:
                    date_text = match.group(0)
                    break
            
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
                'description': description
            })
            
            print(f"[DEBUG] Extracted article {idx+1}: {title[:50]}...")
        
        return articles
    
    def scrape(self, debug: bool = False, use_selenium: bool = False) -> List[Dict]:
        """
        Main method to scrape the blog page.
        
        Args:
            debug: If True, save extracted HTML to file for debugging
            use_selenium: If True, force use of Selenium. If False, try requests first.
        
        Returns:
            List of structured article data
        """
        print("Fetching HTML from Cisco blog page...")
        html = self.fetch_html(use_selenium=use_selenium)
        
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
            debug_filepath = debug_dir / "debug_cisco_blog_full_html.html"
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
            print(f"  Date:        {article.get('date', 'N/A')}")
            print(f"  Link:        {article['link']}")
            print(f"  Description: {article['description']}")
            print("-" * 80)
    
    def save_to_json(self, articles: List[Dict], filename: str = "cisco_blog_articles.json"):
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
    
    # Check for flags
    debug = "--debug" in sys.argv or "-d" in sys.argv
    use_selenium = "--selenium" in sys.argv or "-s" in sys.argv
    
    try:
        scraper = CiscoBlogScraper()
        articles = scraper.scrape(debug=debug, use_selenium=use_selenium)
        scraper.display_results(articles)
        scraper.save_to_json(articles)
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        import gc
        with redirect_stderr(StringIO()):
            time.sleep(0.3)
            gc.collect()
            time.sleep(0.3)
    
    return 0

if __name__ == "__main__":
    exit(main())

