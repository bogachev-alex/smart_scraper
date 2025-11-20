"""
LLM-based scraper for extracting structured data from Ericsson newsroom page.
Extracts: title, date, link, description
Renamed from ericsson_scraper.py to ericsson_news_scraper.py
"""

import requests
from bs4 import BeautifulSoup
from openai import OpenAI
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

# Load environment variables
load_dotenv()


class EricssonNewsScraper:
    def __init__(self, api_key: str = None):
        """
        Initialize the scraper with OpenAI API key.
        
        Args:
            api_key: OpenAI API key. If not provided, will try to get from environment.
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key is required. Provide it as argument or set OPENAI_API_KEY environment variable.")
        
        self.client = OpenAI(api_key=self.api_key)
        self.url = "https://www.ericsson.com/en/newsroom/latest-news?typeFilters=1,2,3,4&locs=68304"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def fetch_html(self, use_selenium: bool = True) -> str:
        """
        Fetch HTML content from the Ericsson newsroom page.
        Uses Selenium to handle JavaScript-rendered content and bot protection.
        
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
        """Fetch HTML using undetected-chromedriver to bypass bot protection."""
        driver = None
        try:
            # Use undetected-chromedriver which is designed to bypass bot detection
            print("Initializing browser (this may take a moment)...")
            options = uc.ChromeOptions()
            # Try without headless first - some sites block headless browsers
            # options.add_argument('--headless')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--start-maximized')
            
            driver = uc.Chrome(options=options, version_main=None)
            
            print("Loading page...")
            driver.get(self.url)
            
            # Initial wait for page to start loading
            time.sleep(3)
            
            # Wait for content to load with better detection
            print("Waiting for page content to load...")
            max_wait = 20
            waited = 0
            while waited < max_wait:
                page_source = driver.page_source
                page_length = len(page_source)
                
                # Check for specific Ericsson newsroom elements
                news_list = driver.find_elements(By.CSS_SELECTOR, ".news-list, div.news-list")
                cards = driver.find_elements(By.CSS_SELECTOR, ".card, div.card")
                articles = driver.find_elements(By.TAG_NAME, "article")
                links = driver.find_elements(By.CSS_SELECTOR, "a[href*='newsroom'], a[href*='/en/news/']")
                main_content = driver.find_elements(By.TAG_NAME, "main")
                
                # Check if we have substantial content
                has_content = (
                    len(news_list) > 0 or 
                    len(cards) > 0 or 
                    len(articles) > 0 or 
                    len(links) > 5 or 
                    len(main_content) > 0 or 
                    page_length > 50000  # Increased threshold
                )
                
                if has_content:
                    print(f"[OK] Content loaded successfully! ({page_length} chars, {len(cards)} cards, {len(links)} links)")
                    break
                
                # If page is very small, it might be an error page
                if page_length < 5000 and waited > 6:
                    print(f"[WARNING] Page seems too small ({page_length} chars). May be an error page.")
                    break
                
                time.sleep(2)
                waited += 2
                if waited % 4 == 0:
                    print(f"  Still waiting... ({waited}s, {page_length} chars)")
            
            # Additional wait for JavaScript to fully render
            time.sleep(3)
            
            html = driver.page_source
            current_url = driver.current_url
            print(f"Retrieved HTML: {len(html)} characters")
            print(f"Current URL: {current_url}")
            
            # Verify we're on the correct page
            if 'ericsson.com' not in current_url.lower():
                print(f"[WARNING] May have been redirected. Expected Ericsson URL, got: {current_url}")
            
            # Try to find article links to verify we have content
            temp_soup = BeautifulSoup(html, 'html.parser')
            test_links = temp_soup.find_all('a', href=lambda x: x and any(kw in x.lower() for kw in ['newsroom', 'news', 'article']))
            news_list_elem = temp_soup.find('div', class_='news-list')
            cards_elem = temp_soup.find_all('div', class_='card')
            print(f"[DEBUG] Found {len(test_links)} newsroom/news links, {len(cards_elem)} cards, news-list: {news_list_elem is not None}")
            
            if len(html) < 10000:
                print(f"[WARNING] Retrieved HTML seems too short ({len(html)} chars). The page might not have loaded correctly.")
                print(f"[DEBUG] Page title: {driver.title}")
                # Check if it's an error page
                if 'error' in html.lower() or '404' in html.lower() or 'not found' in html.lower():
                    print("[ERROR] Page appears to be an error page!")
            
            return html
        except Exception as e:
            raise Exception(f"Failed to fetch HTML with Selenium: {str(e)}")
        finally:
            if driver:
                print("Closing browser...")
                driver.quit()
    
    def extract_article_links(self, html: str) -> List[Dict]:
        """
        Extract article links using BeautifulSoup.
        Specifically targets the press releases structure with class 'td_headlines' (similar to Nokia).
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with basic article info (link, title, date, description)
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # PRIMARY METHOD: Look for Ericsson news list structure
        # Find the news-list container
        news_list = soup.find('div', class_='news-list')
        
        if news_list:
            # Find all cards directly within news-list (more reliable than finding rows)
            cards = news_list.find_all('div', class_='card', recursive=True)
            print(f"[DEBUG] Found {len(cards)} cards in news-list")
            
            # Process each card
            for idx, card in enumerate(cards):
                # Verify this card has a title link (to ensure it's an article card)
                title_elem = card.find('h4', class_='card-title')
                if not title_elem:
                    continue
                title_link = title_elem.find('a', href=True)
                if not title_link:
                    continue
                
                # Extract URL from title link (we already verified it exists)
                href = title_link.get('href', '')
                
                # If no href from title, try to find image link in parent row
                if not href:
                    # Find parent row to look for image link
                    parent_row = card.find_parent('div', class_='row')
                    if parent_row:
                        img_link = parent_row.find('a', href=True)
                        if img_link:
                            href = img_link.get('href', '')
                
                if not href:
                    continue
                
                # Make URL absolute
                if href.startswith('/'):
                    full_url = f"https://www.ericsson.com{href}"
                elif href.startswith('http'):
                    full_url = href
                else:
                    continue
                
                # Avoid duplicates
                if full_url in seen_links:
                    continue
                seen_links.add(full_url)
                
                # Extract title from h4.card-title > a (we already have title_link)
                title = title_link.get_text(strip=True)
                if not title or len(title) < 5:
                    title = "N/A"
                
                # Extract date from p.card-description > span.date
                date_text = "N/A"
                date_author = card.find('p', class_='card-description')
                if date_author:
                    date_span = date_author.find('span', class_='date')
                    if date_span:
                        date_raw = date_span.get_text(strip=True)
                        # Parse date like "Nov 10, 2025" or "Nov 10 2025"
                        date_patterns = [
                            r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})',
                            r'(\d{4})-(\d{2})-(\d{2})',
                        ]
                        for pattern in date_patterns:
                            match = re.search(pattern, date_raw, re.IGNORECASE)
                            if match:
                                if len(match.groups()) == 3:
                                    if match.group(1).isdigit():
                                        # YYYY-MM-DD format
                                        date_text = date_raw
                                    else:
                                        # Month Day, Year format
                                        month = match.group(1)
                                        day = match.group(2)
                                        year = match.group(3)
                                        month_map = {
                                            'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
                                            'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
                                            'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12',
                                            'January': '01', 'February': '02', 'March': '03', 'April': '04',
                                            'May': '05', 'June': '06', 'July': '07', 'August': '08',
                                            'September': '09', 'October': '10', 'November': '11', 'December': '12'
                                        }
                                        month_num = month_map.get(month[:3], month)
                                        if month_num.isdigit():
                                            day_padded = day.zfill(2)
                                            date_text = f"{year}-{month_num}-{day_padded}"
                                        else:
                                            date_text = date_raw
                                break
                        if date_text == "N/A":
                            date_text = date_raw
                
                # Extract description from div.preamble-content
                description = "N/A"
                preamble = card.find('div', class_='preamble-content')
                if preamble:
                    desc_text = preamble.get_text(strip=True)
                    if desc_text and len(desc_text) > 20:
                        description = desc_text[:500]
                
                articles.append({
                    'link': full_url,
                    'title': title,
                    'date': date_text,
                    'description': description
                })
                
                print(f"[DEBUG] Extracted article {idx+1}: {title[:50]}...")
            
            # If we found articles using the primary method, return them
            if len(articles) > 0:
                return articles
        
        # FALLBACK: Try Nokia-style structure (ppmodule_headlines) if Ericsson structure not found
        container = soup.find('div', class_=lambda x: x and ('ppmodule_headlines' in str(x) or 'archive_item_container' in str(x) or 'div_headlines' in str(x)))
        
        if container:
            # Find all article links within the container
            article_links = container.find_all('a', class_='td_headlines')
            print(f"[DEBUG] Found {len(article_links)} article links with class 'td_headlines' in container")
            
            # Process each article link (Nokia structure)
            for idx, link in enumerate(article_links):
                # Extract URL
                href = link.get('href', '')
                if not href:
                    continue
                
                # Skip filter/search links
                if '?h=' in href or '?t=' in href or '?match=' in href:
                    continue
                
                # Make URL absolute
                if href.startswith('/'):
                    full_url = f"https://www.ericsson.com{href}"
                elif href.startswith('http'):
                    full_url = href
                else:
                    continue
                
                # Avoid duplicates
                if full_url in seen_links:
                    continue
                seen_links.add(full_url)
                
                # Extract title - try multiple sources
                title = "N/A"
                
                # 1. Try title attribute
                title_attr = link.get('title', '')
                if title_attr and len(title_attr) > 10:
                    title = title_attr
                
                # 2. Try h3 inside pp_headline div
                if title == "N/A" or len(title) < 10:
                    headline_div = link.find('div', class_='pp_headline')
                    if headline_div:
                        h3 = headline_div.find('h3')
                        if h3:
                            title = h3.get_text(strip=True)
                
                # 3. Fallback to link text
                if title == "N/A" or len(title) < 10:
                    link_text = link.get_text(strip=True)
                    if link_text and len(link_text) > 10:
                        title = link_text
                
                # Extract date from pp_publishdate div
                date_text = "N/A"
                publishdate_div = link.find('div', class_='pp_publishdate')
                
                if publishdate_div:
                    # Extract month, day, year
                    month_elem = publishdate_div.find('div', class_='pp_date_month')
                    day_elem = publishdate_div.find('div', class_='pp_date_day')
                    year_elem = publishdate_div.find('div', class_='pp_date_year')
                    
                    month = month_elem.get_text(strip=True) if month_elem else ""
                    day = day_elem.get_text(strip=True) if day_elem else ""
                    year = year_elem.get_text(strip=True) if year_elem else ""
                    
                    # Clean day (remove comma if present)
                    day = day.replace(',', '').strip()
                    
                    # Format date
                    if month and day and year:
                        # Try to format as YYYY-MM-DD
                        month_map = {
                            'January': '01', 'February': '02', 'March': '03', 'April': '04',
                            'May': '05', 'June': '06', 'July': '07', 'August': '08',
                            'September': '09', 'October': '10', 'November': '11', 'December': '12',
                            'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
                            'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
                            'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
                        }
                        
                        month_num = month_map.get(month, month)
                        if month_num.isdigit():
                            day_padded = day.zfill(2)
                            date_text = f"{year}-{month_num}-{day_padded}"
                        else:
                            # Fallback to readable format
                            date_text = f"{month} {day}, {year}"
                    elif year:
                        # At least we have the year
                        date_text = year
                
                # Extract description
                description = "N/A"
                # Look for description in paragraph, summary, or excerpt elements
                desc_elem = link.find_parent(['div', 'article', 'li', 'section'])
                if desc_elem:
                    desc_paragraphs = desc_elem.find_all(['p', 'div', 'span'], class_=lambda x: x and any(keyword in str(x).lower() for keyword in ['description', 'summary', 'excerpt', 'intro', 'lead']))
                    if desc_paragraphs:
                        desc_text = desc_paragraphs[0].get_text(strip=True)
                        if desc_text and len(desc_text) > 20:
                            description = desc_text[:500]
                
                articles.append({
                    'link': full_url,
                    'title': title,
                    'date': date_text,
                    'description': description
                })
                
                print(f"[DEBUG] Extracted article {idx+1}: {title[:50]}...")
            
            # If we found articles using the fallback method, return them
            if len(articles) > 0:
                return articles
        
        # FALLBACK METHOD: Original extraction logic
        # Find all article elements or news containers
        article_elements = soup.find_all(['article', 'div'], class_=lambda x: x and any(keyword in str(x).lower() for keyword in ['article', 'news', 'item', 'card', 'post']))
        
        # Also look for links that might be article links
        news_links = soup.find_all('a', href=lambda x: x and ('newsroom' in x.lower() or '/news/' in x.lower() or '/article' in x.lower() or '/en/news/' in x.lower()))
        
        print(f"[DEBUG] Found {len(article_elements)} potential article containers")
        print(f"[DEBUG] Found {len(news_links)} potential news links")
        
        # Also try to find articles by looking for date patterns in links
        date_pattern_links = soup.find_all('a', href=re.compile(r'/\d{4}/'))
        print(f"[DEBUG] Found {len(date_pattern_links)} links with date patterns (YYYY format)")
        
        # Process article elements
        for idx, article in enumerate(article_elements[:200]):  # Increased limit to 200 to capture more articles
            # Find the main article link
            article_links = article.find_all('a', href=True)
            
            # Find the link that points to the actual article
            main_link = None
            for link in article_links:
                href = link.get('href', '')
                # Look for links to newsroom articles
                if '/newsroom/' in href or '/news/' in href.lower() or '/article' in href.lower() or '/en/news/' in href.lower():
                    # Skip filter/search links
                    if '?typeFilters=' in href or '?locs=' in href or href.endswith('/newsroom') or href.endswith('/news'):
                        continue
                    # Make sure it's an actual article link (has a date or descriptive path)
                    if '/2025/' in href or '/2024/' in href or len(href.split('/')) > 5:
                        main_link = link
                        break
            
            # If no main link found in article container, try to find any valid news link
            if not main_link and article_links:
                for link in article_links:
                    href = link.get('href', '')
                    if '/en/news/' in href or (href.startswith('/en/newsroom/') and '/202' in href):
                        if '?typeFilters=' not in href and '?locs=' not in href:
                            main_link = link
                            break
            
            if not main_link:
                continue
            
            href = main_link.get('href', '')
            if href in ['/newsroom', '/newsroom/', '/news', '/news/']:
                continue
            
            # Make URL absolute
            if href.startswith('/'):
                full_url = f"https://www.ericsson.com{href}"
            elif href.startswith('http'):
                full_url = href
            elif href.startswith('en/'):
                full_url = f"https://www.ericsson.com/{href}"
            else:
                continue
            
            # Avoid duplicates
            if full_url in seen_links:
                continue
            seen_links.add(full_url)
            
            # Extract title
            title = "N/A"
            # Try to find title in h1, h2, h3, h4, h5 within the article
            for heading in article.find_all(['h1', 'h2', 'h3', 'h4', 'h5']):
                heading_text = heading.get_text(strip=True)
                if heading_text and len(heading_text) > 10:
                    title = heading_text
                    break
            
            # If no heading found, use link text
            if title == "N/A" or len(title) < 10:
                link_text = main_link.get_text(strip=True)
                if link_text and len(link_text) > 10:
                    title = link_text
                else:
                    # Try title attribute
                    title_attr = main_link.get('title', '')
                    if title_attr and len(title_attr) > 10:
                        title = title_attr
            
            # Extract date
            date_text = "N/A"
            article_text = article.get_text()
            date_patterns = [
                r'\b(\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b',
                r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b',
                r'\b\d{4}-\d{2}-\d{2}\b',
                r'\b\d{1,2}/\d{1,2}/\d{4}\b',
            ]
            for pattern in date_patterns:
                match = re.search(pattern, article_text, re.IGNORECASE)
                if match:
                    date_text = match.group(1) if match.lastindex >= 1 else match.group(0)
                    break
            
            # Also look for date in time elements or date-related classes
            time_elem = article.find(['time', 'span', 'div'], class_=lambda x: x and any(keyword in str(x).lower() for keyword in ['date', 'time', 'published']))
            if time_elem and date_text == "N/A":
                time_text = time_elem.get_text(strip=True)
                for pattern in date_patterns:
                    match = re.search(pattern, time_text, re.IGNORECASE)
                    if match:
                        date_text = match.group(1) if match.lastindex >= 1 else match.group(0)
                        break
            
            # Extract description
            description = "N/A"
            # Look for description in paragraph, summary, or excerpt elements
            desc_elem = article.find(['p', 'div', 'span'], class_=lambda x: x and any(keyword in str(x).lower() for keyword in ['description', 'summary', 'excerpt', 'intro', 'lead']))
            if desc_elem:
                desc_text = desc_elem.get_text(strip=True)
                if desc_text and len(desc_text) > 20:
                    description = desc_text[:500]  # Limit description length
            else:
                # Try to find first paragraph that's not too short
                paragraphs = article.find_all('p')
                for p in paragraphs:
                    p_text = p.get_text(strip=True)
                    if p_text and len(p_text) > 20 and len(p_text) < 500:
                        description = p_text
                        break
            
            articles.append({
                'link': full_url,
                'title': title,
                'date': date_text,
                'description': description
            })
            
            print(f"[DEBUG] Extracted article {idx+1}: {title[:50]}...")
        
        # Fallback: If we didn't find many articles, try extracting directly from links
        if len(articles) < 10:
            print(f"[DEBUG] Only found {len(articles)} articles from containers, trying direct link extraction...")
            for link in date_pattern_links[:100]:  # Check first 100 date-pattern links
                href = link.get('href', '')
                if not href:
                    continue
                
                # Make URL absolute
                if href.startswith('/'):
                    full_url = f"https://www.ericsson.com{href}"
                elif href.startswith('http'):
                    full_url = href
                elif href.startswith('en/'):
                    full_url = f"https://www.ericsson.com/{href}"
                else:
                    continue
                
                # Skip if already found
                if full_url in seen_links:
                    continue
                
                # Skip filter links
                if '?typeFilters=' in href or '?locs=' in href:
                    continue
                
                # Make sure it's a news article link
                if '/en/news/' not in href and '/newsroom/' not in href and '/news/' not in href.lower():
                    continue
                
                # Skip category pages
                if href.endswith('/newsroom') or href.endswith('/news') or href.endswith('/latest-news'):
                    continue
                
                seen_links.add(full_url)
                
                # Extract title
                title = link.get_text(strip=True)
                if not title or len(title) < 10:
                    title_attr = link.get('title', '')
                    if title_attr and len(title_attr) > 10:
                        title = title_attr
                    else:
                        title = "N/A"
                
                # Try to find date in parent elements
                date_text = "N/A"
                parent = link.find_parent(['div', 'article', 'li', 'section'])
                if parent:
                    parent_text = parent.get_text()
                    date_patterns = [
                        r'\b(\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b',
                        r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b',
                        r'\b\d{4}-\d{2}-\d{2}\b',
                    ]
                    for pattern in date_patterns:
                        match = re.search(pattern, parent_text, re.IGNORECASE)
                        if match:
                            date_text = match.group(1) if match.lastindex >= 1 else match.group(0)
                            break
                
                # Extract description from parent
                description = "N/A"
                if parent:
                    desc_elem = parent.find(['p', 'div', 'span'], class_=lambda x: x and any(keyword in str(x).lower() for keyword in ['description', 'summary', 'excerpt']))
                    if desc_elem:
                        desc_text = desc_elem.get_text(strip=True)
                        if desc_text and len(desc_text) > 20:
                            description = desc_text[:500]
                    else:
                        paragraphs = parent.find_all('p')
                        for p in paragraphs:
                            p_text = p.get_text(strip=True)
                            if p_text and len(p_text) > 20 and len(p_text) < 500:
                                description = p_text
                                break
                
                articles.append({
                    'link': full_url,
                    'title': title,
                    'date': date_text,
                    'description': description
                })
            
            print(f"[DEBUG] After fallback extraction, found {len(articles)} total articles")
        
        return articles
    
    def extract_html_structure(self, html: str) -> str:
        """
        Extract relevant HTML structure for LLM analysis.
        Uses BeautifulSoup to clean and extract meaningful content.
        Prioritizes the ppmodule_headlines structure (like Nokia).
        
        Args:
            html: Raw HTML content
            
        Returns:
            Cleaned HTML structure as string
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style", "noscript"]):
            script.decompose()
        
        # Strategy 1: Look for Ericsson news-list structure (primary method)
        main_content = soup.find('div', class_='news-list')
        
        if main_content:
            # Extract the container with all article links
            content_str = str(main_content)
        else:
            # Strategy 1b: Try Nokia-style structure (ppmodule_headlines) as fallback
            main_content = soup.find('div', class_=lambda x: x and ('ppmodule_headlines' in str(x) or 'archive_item_container' in str(x) or 'div_headlines' in str(x)))
            
            if main_content:
                # Extract the container with all article links
                content_str = str(main_content)
            else:
                # Strategy 2: Look for common news/press content selectors
                content_selectors = [
                    ('main', {}),
                    ('article', {}),
                    ('div', {'class': lambda x: x and any(keyword in str(x).lower() for keyword in ['news', 'article', 'content', 'listing', 'newsroom'])}),
                    ('section', {'class': lambda x: x and any(keyword in str(x).lower() for keyword in ['news', 'article', 'newsroom'])}),
                    ('ul', {'class': lambda x: x and any(keyword in str(x).lower() for keyword in ['news', 'article', 'list'])}),
                ]
                
                main_content = None
                for tag, attrs in content_selectors:
                    main_content = soup.find(tag, attrs)
                    if main_content:
                        break
                
                # Strategy 3: Look for links that might be article links
                if not main_content:
                    # Find all links and their parent containers
                    links = soup.find_all('a', href=True)
                    if links:
                        # Find common parent containers of links
                        for link in links[:20]:  # Check first 20 links
                            href = link.get('href', '')
                            text = link.get_text(strip=True)
                            # If link looks like an article link and has text
                            if text and len(text) > 10 and ('newsroom' in href.lower() or 'news' in href.lower() or 'article' in href.lower() or '/20' in href):
                                parent = link.find_parent(['div', 'article', 'li', 'section'])
                                if parent:
                                    main_content = parent.find_parent(['div', 'section', 'main'])
                                    if main_content:
                                        break
                
                if main_content:
                    # Extract text and links from main content
                    content_str = str(main_content)
                else:
                    # Fallback: extract all links and their context
                    body = soup.find('body')
                    if body:
                        # Get all links with their surrounding context
                        links_html = []
                        for link in body.find_all('a', href=True)[:50]:  # Limit to 50 links
                            parent = link.find_parent(['div', 'li', 'article', 'section'])
                            if parent:
                                links_html.append(str(parent))
                        content_str = '\n'.join(links_html) if links_html else str(body)
                    else:
                        content_str = html
        
        # If we still don't have good content, try to get the entire body with all links
        if len(content_str) < 5000 or "incapsula" in content_str.lower() or "imperva" in content_str.lower() or "cloudflare" in content_str.lower():
            body = soup.find('body')
            if body:
                # Get ALL links and their full context - be more aggressive
                all_links_context = []
                seen_contexts = set()  # Avoid duplicates
                
                for link in body.find_all('a', href=True):
                    href = link.get('href', '').lower()
                    link_text = link.get_text(strip=True)
                    
                    # Look for newsroom/news/article links
                    if any(keyword in href for keyword in ['newsroom', 'news', 'article', '/20']) or \
                       (link_text and len(link_text) > 15):  # Long link text might be article titles
                        # Get parent with more context
                        parent = link.find_parent(['div', 'li', 'article', 'section', 'tr', 'td', 'p'])
                        if parent:
                            # Get even more context - the parent's parent
                            grandparent = parent.find_parent(['div', 'section', 'ul', 'ol', 'table', 'main', 'article'])
                            if grandparent:
                                context_str = str(grandparent)
                                if context_str not in seen_contexts and len(context_str) > 50:
                                    all_links_context.append(context_str)
                                    seen_contexts.add(context_str)
                            else:
                                context_str = str(parent)
                                if context_str not in seen_contexts and len(context_str) > 50:
                                    all_links_context.append(context_str)
                                    seen_contexts.add(context_str)
                
                if all_links_context:
                    content_str = '\n'.join(all_links_context)
                    print(f"[DEBUG] Extracted {len(all_links_context)} link contexts")
                else:
                    # Last resort: get entire body
                    content_str = str(body)
        
        # Limit content size to avoid token limits (keep first 150000 chars for better context)
        if len(content_str) > 150000:
            content_str = content_str[:150000] + "..."
        
        return content_str
    
    def analyze_with_llm(self, html_content: str) -> List[Dict]:
        """
        Use OpenAI LLM to extract structured data from HTML.
        
        Args:
            html_content: HTML content to analyze
            
        Returns:
            List of dictionaries with title, date, link, description
        """
        prompt = f"""You are analyzing HTML from Ericsson newsroom page (https://www.ericsson.com/en/newsroom/latest-news?typeFilters=1,2,3,4&locs=68304). Your task is to extract ALL news articles from the page.

CRITICAL INSTRUCTIONS:
1. Extract ALL news articles you can find on the page - be extremely thorough
2. Each news article should become a separate entry
3. Do NOT extract filter links, navigation links, or category links
4. Do NOT extract links with query parameters like ?typeFilters=, ?locs= (these are filter/search links)
5. Extract ALL news articles you can find - there should be MANY articles (typically 20-100+ on a listing page)
6. Look for ALL article cards, containers, and links - don't miss any
7. If articles are in a list or grid, extract EVERY single one

What to look for:
- Article cards/containers that contain news content
- Links within those containers that point to actual article pages (href containing "/newsroom/" or "/news/" with descriptive path)
- Titles/headlines in headings (<h1>, <h2>, <h3>, <h4>) within article containers
- Dates in formats like "11 Nov 2025", "Nov 11, 2025", "2025-11-11", "11/11/2025", etc.
- Descriptions/summaries in paragraph elements or elements with description/summary/excerpt classes
- Skip any links with query parameters like ?typeFilters=, ?locs= (these are filter links, not articles)

For EACH news article you find, extract:
- title: The headline or title (required - use link text if no explicit title)
- date: Publication date (format as YYYY-MM-DD if possible, otherwise keep original format, use "N/A" if not found)
- link: Full URL (if relative, prepend https://www.ericsson.com. Use "N/A" only if absolutely no link exists)
- description: A brief description or summary of the article (extract from paragraph, summary, or excerpt elements. Use "N/A" if not found)

EXAMPLES of what to extract:
- News articles with dates, titles, and descriptions
- Articles from the newsroom with full URLs and summaries

EXAMPLES of what to SKIP:
- Filter links (URLs with ?typeFilters=, ?locs=)
- Navigation links
- Category/tag links
- Links that just say "Latest News" (those are filters, not articles)
- Links to /newsroom without a specific article path

Return a JSON array with ALL news articles found.

JSON structure:
[
  {{
    "title": "First Article Title",
    "date": "2025-11-11",
    "link": "https://www.ericsson.com/en/newsroom/article-1",
    "description": "Brief description of the article content..."
  }},
  {{
    "title": "Second Article Title",
    "date": "2025-10-15",
    "link": "https://www.ericsson.com/en/newsroom/article-2",
    "description": "Another article description..."
  }}
  // ... continue for ALL articles found
]

HTML Content:
{html_content}

Return ONLY valid JSON array. Extract EVERY article you can find. No explanations, no markdown, just the JSON array."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",  # Using gpt-4o-mini for cost efficiency, can be changed to gpt-4 if needed
                messages=[
                    {"role": "system", "content": "You are a web scraping expert that extracts ALL articles from HTML. You MUST find every single news article on the page. Return only valid JSON arrays with all articles found. Be extremely thorough - typical news listing pages have 10-50+ articles."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=8000  # Increased to allow for many articles
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Remove markdown code blocks if present
            if result_text.startswith("```json"):
                result_text = result_text[7:]
            if result_text.startswith("```"):
                result_text = result_text[3:]
            if result_text.endswith("```"):
                result_text = result_text[:-3]
            result_text = result_text.strip()
            
            # Parse JSON
            articles = json.loads(result_text)
            
            # Ensure all articles have required fields
            structured_articles = []
            for article in articles:
                if isinstance(article, dict):
                    structured_article = {
                        "title": article.get("title", "N/A"),
                        "date": article.get("date", "N/A"),
                        "link": article.get("link", "N/A"),
                        "description": article.get("description", "N/A")
                    }
                    structured_articles.append(structured_article)
            
            return structured_articles
            
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON response: {e}")
            print(f"Response was: {result_text}")
            return []
        except Exception as e:
            raise Exception(f"LLM analysis failed: {str(e)}")
    
    def scrape(self, debug: bool = False) -> List[Dict]:
        """
        Main method to scrape and analyze the page.
        
        Args:
            debug: If True, save extracted HTML to file for debugging
        
        Returns:
            List of structured article data
        """
        print("Fetching HTML from Ericsson newsroom page...")
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
            debug_filepath = debug_dir / "debug_ericsson_news_full_html.html"
            with open(debug_filepath, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[DEBUG] Full HTML saved to debug_ericsson_news_full_html.html ({len(html)} chars)")
        
        # First, try to extract article links directly
        print("Extracting article links directly from HTML...")
        direct_articles = self.extract_article_links(html)
        print(f"[DEBUG] Found {len(direct_articles)} article links using BeautifulSoup")
        
        print("Extracting HTML structure for LLM analysis...")
        html_structure = self.extract_html_structure(html)
        
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
            debug_filepath = debug_dir / "debug_ericsson_news_extracted_html.html"
            with open(debug_filepath, "w", encoding="utf-8") as f:
                f.write(html_structure)
            print(f"[DEBUG] Extracted HTML saved to debug_ericsson_news_extracted_html.html ({len(html_structure)} chars)")
        
        # Count potential articles in HTML
        soup = BeautifulSoup(html_structure, 'html.parser')
        news_links = soup.find_all('a', href=lambda x: x and any(kw in x.lower() for kw in ['newsroom', 'news', 'article']))
        print(f"[DEBUG] Found {len(news_links)} potential newsroom/news links in extracted HTML")
        
        print("Analyzing content with LLM to extract detailed information...")
        llm_articles = self.analyze_with_llm(html_structure)
        print(f"[DEBUG] LLM found {len(llm_articles)} articles")
        
        # Combine results - prefer direct extraction, use LLM as supplement
        articles = []
        direct_links = {art['link'] for art in direct_articles}
        
        # Start with direct extraction results
        for art in direct_articles:
            articles.append({
                'title': art['title'],
                'date': art['date'],
                'link': art['link'],
                'description': art['description']
            })
        
        # Add any LLM results that weren't found by direct extraction
        for llm_art in llm_articles:
            llm_link = llm_art.get('link', '')
            # Only add if not already found and is a valid article link
            if llm_link not in direct_links:
                # Check if it's a valid article link
                is_valid = False
                if '/en/news/' in llm_link or '/newsroom/' in llm_link or '/news/' in llm_link:
                    if '?typeFilters=' not in llm_link and '?locs=' not in llm_link:
                        # Make sure it's not just a category page
                        if not llm_link.endswith('/newsroom') and not llm_link.endswith('/news') and not llm_link.endswith('/latest-news'):
                            is_valid = True
                
                if is_valid:
                    articles.append(llm_art)
        
        print(f"Final result: {len(articles)} news articles found")
        if len(direct_articles) > 0:
            print(f"  - {len(direct_articles)} from direct extraction")
        if len(articles) > len(direct_articles):
            print(f"  - {len(articles) - len(direct_articles)} additional from LLM")
        
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
            print(f"  Link:        {article['link']}")
            print(f"  Description: {article['description'][:100]}..." if len(article.get('description', '')) > 100 else f"  Description: {article.get('description', 'N/A')}")
            print("-" * 80)
    
    def save_to_json(self, articles: List[Dict], filename: str = "ericsson_news.json"):
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
    # Check for debug flag first (before parsing API key)
    debug = "--debug" in sys.argv or "-d" in sys.argv
    
    # Filter out debug flags from arguments when looking for API key
    args_without_flags = [arg for arg in sys.argv[1:] if arg not in ["--debug", "-d"]]
    
    # API key from environment variable first, then numbered keys, then command line
    api_key = os.getenv("OPENAI_API_KEY")
    
    # If not found, try numbered keys (OPENAI_API_KEY_1, OPENAI_API_KEY_2, etc.)
    if not api_key:
        i = 1
        while i <= 10:  # Check up to 10 numbered keys
            api_key = os.getenv(f"OPENAI_API_KEY_{i}")
            if api_key:
                print(f"Using OPENAI_API_KEY_{i} from environment")
                break
            i += 1
    
    # If still not found, try command line argument
    if not api_key and args_without_flags:
        api_key = args_without_flags[0]
    
    if not api_key:
        print("Error: OPENAI_API_KEY not found!")
        print("Please either:")
        print("  1. Set OPENAI_API_KEY or OPENAI_API_KEY_1 environment variable")
        print("  2. Create a .env file with OPENAI_API_KEY=your_key_here")
        print("  3. Provide it as a command line argument: python ericsson_news_scraper.py your_api_key")
        return 1
    
    try:
        scraper = EricssonNewsScraper(api_key=api_key)
        articles = scraper.scrape(debug=debug)
        scraper.display_results(articles)
        scraper.save_to_json(articles)
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())

