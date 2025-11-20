"""
IBM Newsroom Scraper
Scrapes news articles from https://newsroom.ibm.com/campaign
Renamed from ibm_scraper.py to ibm_news_scraper.py
"""

import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
from typing import List, Dict
import time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


class IBMNewsScraper:
    """Scraper for IBM Newsroom campaign page"""
    
    def __init__(self, base_url: str = "https://newsroom.ibm.com/campaign"):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
    
    def _fetch_html_selenium(self) -> str:
        """Fetch HTML using Selenium to get fully rendered page with correct links"""
        driver = None
        try:
            print("Initializing browser...")
            options = uc.ChromeOptions()
            options.add_argument('--start-maximized')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument('--headless')  # Run in background
            
            driver = uc.Chrome(options=options, version_main=None)
            
            print(f"Loading page: {self.base_url}")
            driver.get(self.base_url)
            
            # Wait for the article list to load
            print("Waiting for content to load...")
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "ul.wd_layout-simple.wd_item_list"))
                )
                time.sleep(3)  # Give extra time for JavaScript to update links
            except:
                print("Warning: Timeout waiting for content, proceeding anyway...")
                time.sleep(5)
            
            html = driver.page_source
            try:
                driver.quit()
            except:
                pass
            return html
            
        except Exception as e:
            print(f"Error with Selenium: {e}")
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            return None
    
    def fetch_page(self, url: str = None, use_selenium: bool = True) -> BeautifulSoup:
        """Fetch and parse the HTML page"""
        if url is None:
            url = self.base_url
        
        # Use Selenium to get fully rendered page with correct links
        if use_selenium:
            html = self._fetch_html_selenium()
            if html:
                return BeautifulSoup(html, 'html.parser')
            else:
                print("Selenium failed, falling back to requests...")
        
        # Fallback to requests
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except requests.RequestException as e:
            print(f"Error fetching page: {e}")
            return None
    
    def extract_articles(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract article data from the parsed HTML"""
        articles = []
        
        if not soup:
            return articles
        
        # Find the main list container
        item_list = soup.find('ul', class_='wd_layout-simple wd_item_list')
        
        if not item_list:
            print("Could not find article list container")
            return articles
        
        # Find all article items
        items = item_list.find_all('li', class_='wd_item')
        
        for item in items:
            try:
                # Extract title and link
                title_div = item.find('div', class_='wd_title')
                if title_div:
                    title_link = title_div.find('a')
                    if title_link:
                        title = title_link.get_text(strip=True)
                        link = title_link.get('href', '')
                        
                        # Make link absolute if it's relative
                        if link and not link.startswith('http'):
                            if link.startswith('/'):
                                link = f"https://newsroom.ibm.com{link}"
                            else:
                                link = f"{self.base_url}/{link}"
                    else:
                        title = title_div.get_text(strip=True)
                        link = ''
                else:
                    title = ''
                    link = ''
                
                # Extract description
                summary_div = item.find('div', class_='wd_summary')
                description = ''
                if summary_div:
                    p_tag = summary_div.find('p')
                    if p_tag:
                        description = p_tag.get_text(strip=True)
                    else:
                        description = summary_div.get_text(strip=True)
                
                # Extract date
                date_div = item.find('div', class_='wd_date')
                date = ''
                if date_div:
                    date = date_div.get_text(strip=True)
                
                # Only add article if we have at least a title
                if title:
                    articles.append({
                        'title': title,
                        'date': date,
                        'link': link,
                        'description': description
                    })
            
            except Exception as e:
                print(f"Error extracting article: {e}")
                continue
        
        return articles
    
    def scrape(self) -> List[Dict]:
        """Main scraping method"""
        print(f"Fetching page: {self.base_url}")
        soup = self.fetch_page()
        
        if not soup:
            return []
        
        articles = self.extract_articles(soup)
        print(f"Found {len(articles)} articles")
        
        return articles
    
    def save_to_json(self, articles: List[Dict], filename: str = 'ibm_news.json'):
        """Save articles to JSON file in the data/ folder"""
        from pathlib import Path
        
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
        print(f"Saved {len(articles)} articles to {filepath}")
    
    def save_to_csv(self, articles: List[Dict], filename: str = 'ibm_news.csv'):
        """Save articles to CSV file"""
        import csv
        
        if not articles:
            return
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['title', 'date', 'link', 'description'])
            writer.writeheader()
            writer.writerows(articles)
        print(f"Saved {len(articles)} articles to {filename}")


def main():
    """Main function to run the scraper"""
    scraper = IBMNewsScraper()
    articles = scraper.scrape()
    
    if articles:
        # Print first few articles as preview
        print("\n--- Preview of scraped articles ---")
        for i, article in enumerate(articles[:3], 1):
            print(f"\n{i}. {article['title']}")
            print(f"   Date: {article['date']}")
            print(f"   Link: {article['link']}")
            print(f"   Description: {article['description'][:100]}...")
        
        # Save to files
        scraper.save_to_json(articles)
        scraper.save_to_csv(articles)
    else:
        print("No articles found")


if __name__ == "__main__":
    main()


