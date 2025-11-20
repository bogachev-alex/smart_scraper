"""
LLM-based scraper for extracting structured data from Oracle news page.
Extracts: title, date, link
Renamed from oracle_scraper.py to oracle_news_scraper.py
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

class OracleNewsScraper:
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
        self.url = "https://www.oracle.com/news/"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def fetch_html(self, use_selenium: bool = True) -> str:
        """
        Fetch HTML content from the Oracle news page.
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
            options.add_argument("--start-maximized")
            options.add_argument("--disable-blink-features=AutomationControlled")
            # Non-headless mode (headless is disabled by default in uc.Chrome)
            # Note: excludeSwitches and useAutomationExtension are handled internally by undetected_chromedriver
            
            driver = uc.Chrome(options=options, version_main=None)
            
            print("Loading page...")
            driver.get(self.url)
            
            # Wait for content to load - try multiple selectors
            print("Waiting for page content to load...")
            max_wait = 30
            waited = 0
            while waited < max_wait:
                page_source = driver.page_source
                
                # Try multiple selectors to find news items
                news_items = driver.find_elements(By.CSS_SELECTOR, "li.rc92w3")
                if len(news_items) == 0:
                    news_items = driver.find_elements(By.CSS_SELECTOR, "li[class*='rc92w3']")
                if len(news_items) == 0:
                    # Try finding by structure
                    news_list = driver.find_elements(By.CSS_SELECTOR, "ul.rc92w2")
                    if news_list:
                        news_items = news_list[0].find_elements(By.CSS_SELECTOR, "li")
                
                news_list = driver.find_elements(By.CSS_SELECTOR, "ul.rc92w2, ul[class*='rc92w2']")
                links = driver.find_elements(By.CSS_SELECTOR, "a[href*='news'], a[href*='announcement']")
                
                if len(news_items) > 0:
                    print(f"[OK] Content loaded successfully! Found {len(news_items)} news items")
                    break
                elif len(news_list) > 0:
                    print(f"[OK] News list found, waiting for items...")
                    time.sleep(3)  # Give it more time to populate
                    news_items = driver.find_elements(By.CSS_SELECTOR, "li.rc92w3, li[class*='rc92w3']")
                    if len(news_items) > 0:
                        print(f"[OK] Found {len(news_items)} news items after additional wait")
                        break
                elif len(links) > 5 or len(page_source) > 20000:
                    print(f"[OK] Content loaded (found {len(links)} links)")
                    break
                
                time.sleep(2)
                waited += 2
                if waited % 4 == 0:
                    print(f"  Still waiting... ({waited}s)")
            
            # Additional wait for JavaScript to fully render
            time.sleep(5)
            
            # Scroll to ensure all visible content is loaded
            print("Scrolling to ensure all content is visible...")
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)
            
            # Final check with multiple methods
            final_check = driver.find_elements(By.CSS_SELECTOR, "li.rc92w3")
            if len(final_check) == 0:
                final_check = driver.find_elements(By.CSS_SELECTOR, "li[class*='rc92w3']")
            if len(final_check) == 0:
                # Try finding any li in ul.rc92w2
                news_list = driver.find_elements(By.CSS_SELECTOR, "ul.rc92w2, ul[class*='rc92w2']")
                if news_list:
                    final_check = news_list[0].find_elements(By.TAG_NAME, "li")
            
            print(f"[DEBUG] Final check: Found {len(final_check)} news items in DOM")
            
            # Debug: Print what we actually found
            if len(final_check) == 0:
                print("[DEBUG] No news items found. Checking page structure...")
                # Check for ul.rc92w2
                ul_check = driver.find_elements(By.CSS_SELECTOR, "ul.rc92w2, ul[class*='rc92w2']")
                print(f"[DEBUG] Found {len(ul_check)} ul.rc92w2 elements")
                # Check for section.rc92
                section_check = driver.find_elements(By.CSS_SELECTOR, "section[class*='rc92']")
                print(f"[DEBUG] Found {len(section_check)} section.rc92 elements")
                # Check for any li elements
                all_lis = driver.find_elements(By.TAG_NAME, "li")
                print(f"[DEBUG] Found {len(all_lis)} total <li> elements")
                # Check for news/announcement links
                news_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='news'], a[href*='announcement']")
                print(f"[DEBUG] Found {len(news_links)} news/announcement links")
            
            html = driver.page_source
            print(f"Retrieved HTML: {len(html)} characters")
            
            if len(html) < 10000:
                print(f"[WARNING] Retrieved HTML seems too short ({len(html)} chars). The page might still be loading.")
                print("Trying to wait a bit longer...")
                time.sleep(5)
                html = driver.page_source
                print(f"Retrieved HTML after additional wait: {len(html)} characters")
            
            # Try to find article links to verify we have content
            temp_soup = BeautifulSoup(html, 'html.parser')
            test_links = temp_soup.find_all('a', href=lambda x: x and any(kw in x.lower() for kw in ['news', 'announcement']))
            print(f"[DEBUG] Found {len(test_links)} news/announcement links in full HTML")
            
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
        Targets rc92w3 (news item) elements.
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with basic article info (link, title, date)
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Find all news items (rc92w3 class) - try multiple methods
        # Method 1: Direct search for li.rc92w3
        news_items = soup.find_all('li', class_='rc92w3')
        
        # Method 2: If not found, try with lambda (more flexible)
        if len(news_items) == 0:
            news_items = soup.find_all('li', class_=lambda x: x and 'rc92w3' in str(x))
        
        # Method 3: Find by structure - find ul.rc92w2 first, then get ALL li children
        if len(news_items) == 0:
            news_list = soup.find('ul', class_='rc92w2')
            if news_list:
                # Get all li children and filter to those with rc92w5
                all_lis = news_list.find_all('li')
                for li in all_lis:
                    rc92w5 = li.find('div', class_=lambda x: x and 'rc92w5' in str(x))
                    if rc92w5:
                        news_items.append(li)
            else:
                news_list = soup.find('ul', class_=lambda x: x and 'rc92w2' in str(x))
                if news_list:
                    all_lis = news_list.find_all('li')
                    for li in all_lis:
                        rc92w5 = li.find('div', class_=lambda x: x and 'rc92w5' in str(x))
                        if rc92w5:
                            news_items.append(li)
        
        # Method 4: Find by section.rc92, then ul.rc92w2, then all li with rc92w5
        if len(news_items) == 0:
            rc92_section = soup.find('section', class_=lambda x: x and 'rc92' in str(x))
            if rc92_section:
                news_list = rc92_section.find('ul', class_='rc92w2')
                if news_list:
                    all_lis = news_list.find_all('li')
                    for li in all_lis:
                        rc92w5 = li.find('div', class_=lambda x: x and 'rc92w5' in str(x))
                        if rc92w5:
                            news_items.append(li)
                else:
                    news_list = rc92_section.find('ul', class_=lambda x: x and 'rc92w2' in str(x))
                    if news_list:
                        all_lis = news_list.find_all('li')
                        for li in all_lis:
                            rc92w5 = li.find('div', class_=lambda x: x and 'rc92w5' in str(x))
                            if rc92w5:
                                news_items.append(li)
        
        # Method 5: Find any li with div.rc92w5 (the content div) that has a news/announcement link
        if len(news_items) == 0:
            all_lis = soup.find_all('li')
            for li in all_lis:
                rc92w5 = li.find('div', class_=lambda x: x and 'rc92w5' in str(x))
                if rc92w5:
                    # Check if it has a link to news/announcement
                    link = rc92w5.find('a', href=lambda x: x and any(kw in str(x).lower() for kw in ['news', 'announcement']))
                    if link:
                        news_items.append(li)
        
        print(f"[DEBUG] Found {len(news_items)} news items (rc92w3)")
        
        # Process news items
        for idx, item in enumerate(news_items):
            try:
                # Find date in rc92w4 > rc92-dt
                date_text = "N/A"
                date_elem = item.find('div', class_=lambda x: x and 'rc92-dt' in str(x))
                if date_elem:
                    date_text = date_elem.get_text(strip=True)
                
                # Find title and link in rc92w5 > h3 > a (or h5 > a as fallback)
                title = "N/A"
                link = "N/A"
                description = "N/A"
                
                rc92w5 = item.find('div', class_=lambda x: x and 'rc92w5' in str(x))
                if rc92w5:
                    # Try h3 first (as shown in user's HTML)
                    h3 = rc92w5.find('h3')
                    if h3:
                        a = h3.find('a', href=True)
                        if a:
                            href = a.get('href', '')
                            title = a.get_text(strip=True)
                            
                            # Make URL absolute
                            if href.startswith('/'):
                                link = f"https://www.oracle.com{href}"
                            elif href.startswith('http'):
                                link = href
                            else:
                                link = f"https://www.oracle.com/{href.lstrip('/')}"
                    else:
                        # Fallback to h5
                        h5 = rc92w5.find('h5')
                        if h5:
                            a = h5.find('a', href=True)
                            if a:
                                href = a.get('href', '')
                                title = a.get_text(strip=True)
                                
                                # Make URL absolute
                                if href.startswith('/'):
                                    link = f"https://www.oracle.com{href}"
                                elif href.startswith('http'):
                                    link = href
                                else:
                                    link = f"https://www.oracle.com/{href.lstrip('/')}"
                    
                    # Extract description from p tag in rc92w5
                    desc_p = rc92w5.find('p')
                    if desc_p:
                        description = desc_p.get_text(strip=True)
                
                # Skip if no valid link or title
                if link == "N/A" or title == "N/A" or len(title) < 10:
                    continue
                
                # Avoid duplicates
                if link in seen_links:
                    continue
                seen_links.add(link)
                
                articles.append({
                    'link': link,
                    'title': title,
                    'date': date_text,
                    'description': description
                })
                
                print(f"[DEBUG] Extracted article {idx+1}: {title[:50]}...")
            except Exception as e:
                print(f"[WARNING] Error processing article {idx+1}: {e}")
                continue
        
        return articles
    
    def extract_html_structure(self, html: str) -> str:
        """
        Extract relevant HTML structure for LLM analysis.
        Uses BeautifulSoup to clean and extract meaningful content.
        Specifically extracts all li.rc92w3 elements (news items).
        
        Args:
            html: Raw HTML content
            
        Returns:
            Cleaned HTML structure as string
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style", "noscript"]):
            script.decompose()
        
        # PRIMARY METHOD: Find all li.rc92w3 elements (news items)
        news_items = soup.find_all('li', class_='rc92w3')
        
        # If not found with exact class, try flexible matching
        if len(news_items) == 0:
            news_items = soup.find_all('li', class_=lambda x: x and 'rc92w3' in str(x))
        
        # If still not found, try finding via ul.rc92w2 - get ALL li children
        if len(news_items) == 0:
            news_list = soup.find('ul', class_='rc92w2')
            if news_list:
                # Get all li children, not just those with rc92w3 class
                all_lis = news_list.find_all('li')
                # Filter to those that have rc92w5 (content div) or look like articles
                for li in all_lis:
                    rc92w5 = li.find('div', class_=lambda x: x and 'rc92w5' in str(x))
                    if rc92w5:
                        news_items.append(li)
            else:
                news_list = soup.find('ul', class_=lambda x: x and 'rc92w2' in str(x))
                if news_list:
                    all_lis = news_list.find_all('li')
                    for li in all_lis:
                        rc92w5 = li.find('div', class_=lambda x: x and 'rc92w5' in str(x))
                        if rc92w5:
                            news_items.append(li)
        
        # If still not found, try finding via section.rc92
        if len(news_items) == 0:
            news_section = soup.find('section', class_=lambda x: x and 'rc92' in str(x))
            if news_section:
                news_list = news_section.find('ul', class_='rc92w2')
                if news_list:
                    all_lis = news_list.find_all('li')
                    for li in all_lis:
                        rc92w5 = li.find('div', class_=lambda x: x and 'rc92w5' in str(x))
                        if rc92w5:
                            news_items.append(li)
                else:
                    news_list = news_section.find('ul', class_=lambda x: x and 'rc92w2' in str(x))
                    if news_list:
                        all_lis = news_list.find_all('li')
                        for li in all_lis:
                            rc92w5 = li.find('div', class_=lambda x: x and 'rc92w5' in str(x))
                            if rc92w5:
                                news_items.append(li)
        
        # If still not found, try finding any li with div.rc92w5 anywhere
        if len(news_items) == 0:
            all_lis = soup.find_all('li')
            for li in all_lis:
                rc92w5 = li.find('div', class_=lambda x: x and 'rc92w5' in str(x))
                if rc92w5:
                    # Also check if it has a link to news/announcement
                    link = rc92w5.find('a', href=lambda x: x and any(kw in str(x).lower() for kw in ['news', 'announcement']))
                    if link:
                        news_items.append(li)
        
        # If we found news items, extract their HTML
        if news_items:
            articles_html = [str(item) for item in news_items]
            content_str = '\n'.join(articles_html)
            print(f"[DEBUG] Extracted {len(news_items)} news items for LLM analysis")
        else:
            # Fallback: extract the entire news section
            news_section = soup.find('section', class_=lambda x: x and 'rc92' in str(x))
            if news_section:
                content_str = str(news_section)
                print(f"[DEBUG] Extracted news section (no individual items found)")
            else:
                # Last fallback: look for ul.rc92w2 and extract all its content
                news_list = soup.find('ul', class_=lambda x: x and 'rc92w2' in str(x))
                if news_list:
                    content_str = str(news_list)
                    print(f"[DEBUG] Extracted news list (ul.rc92w2)")
                else:
                    # Last resort: extract all links with news/announcement in href and their full parent context
                    body = soup.find('body')
                    if body:
                        links_html = []
                        seen_links = set()
                        for link in body.find_all('a', href=lambda x: x and any(kw in x.lower() for kw in ['news', 'announcement'])):
                            href = link.get('href', '')
                            if href in seen_links:
                                continue
                            seen_links.add(href)
                            # Get parent with more context
                            parent = link.find_parent(['li', 'div', 'article', 'section'])
                            if parent:
                                links_html.append(str(parent))
                        content_str = '\n'.join(links_html) if links_html else str(body)
                        print(f"[DEBUG] Extracted {len(links_html)} link contexts as fallback")
                    else:
                        content_str = html
        
        # Limit content size to avoid token limits (but keep it large enough for many articles)
        if len(content_str) > 200000:
            content_str = content_str[:200000] + "..."
        
        return content_str
    
    def analyze_with_llm(self, html_content: str) -> List[Dict]:
        """
        Use OpenAI LLM to extract structured data from HTML.
        
        Args:
            html_content: HTML content to analyze
            
        Returns:
            List of dictionaries with title, date, link
        """
        prompt = f"""You are analyzing HTML from Oracle news page (https://www.oracle.com/news/). Your task is to extract ALL news articles from the page.

CRITICAL INSTRUCTIONS - READ CAREFULLY:
1. Extract ALL news articles you can find - be extremely thorough and systematic
2. Each news article should become a separate entry in the JSON array
3. Do NOT extract filter links, navigation links, category links, or footer links
4. Extract ALL news articles you can find - there should be MANY (10-50+ articles), NOT just 4
5. Look for ALL article structures - be flexible about the HTML structure
6. If you see multiple links to /news/announcement/, each one is likely a separate article
7. Count the articles as you extract them - if you only find 4, you're missing many more
8. Be systematic: go through the HTML and extract every article link you see

HTML STRUCTURE TO LOOK FOR (be flexible - structure may vary):
- Articles may be in: <li class="rc92w3"> or any <li> element
- Articles may be in: <div> or <article> elements
- Date: Look for dates in various formats (Nov 12, 2025, 2025-11-12, etc.)
- Title/Link: Look for <a href="/news/announcement/...">Title</a> or similar
- Description: Look for <p> tags near article links

EXTRACTION RULES:
- Extract EVERY link that contains "/news/announcement/" in the path as a separate article
- If you see 10 links to /news/announcement/, extract 10 articles
- If you see 20 links, extract 20 articles
- Links should contain "/news/announcement/" in the path
- Skip links that are just filters, navigation, categories, or the main /news/ page
- Skip duplicate links (same href)
- Each article must have at least a title (from link text) or link
- Look for dates near the links - they might be in various formats

For EACH news article you find, extract:
- title: The headline or title (required - use link text if no explicit title)
- date: Publication date (format as YYYY-MM-DD if possible, otherwise keep original format like "Nov 12, 2025", use "N/A" if not found)
- link: Full URL (if relative, prepend https://www.oracle.com. Use "N/A" only if absolutely no link exists)

EXAMPLES of what to extract:
- News articles with dates, titles, and links from the Latest News section
- Articles from the rc92w2 list container

EXAMPLES of what to SKIP:
- Navigation links
- Filter/search links
- "See more" buttons
- Links to /news/ without a specific article path

Return a JSON array with ALL news articles found.

JSON structure:
[
  {{
    "title": "First Article Title",
    "date": "2025-11-12",
    "link": "https://www.oracle.com/news/announcement/article-1"
  }},
  {{
    "title": "Second Article Title",
    "date": "2025-10-28",
    "link": "https://www.oracle.com/news/announcement/article-2"
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
                        "link": article.get("link", "N/A")
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
        print("Fetching HTML from Oracle news page...")
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
            debug_filepath = debug_dir / "debug_oracle_full_html.html"
            with open(debug_filepath, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[DEBUG] Full HTML saved to {debug_filepath} ({len(html)} chars)")

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
            debug_filepath = debug_dir / "debug_oracle_extracted_html.html"
            with open(debug_filepath, "w", encoding="utf-8") as f:
                f.write(html_structure)
            print(f"[DEBUG] Extracted HTML saved to {debug_filepath} ({len(html_structure)} chars)")

        # Count potential articles in HTML
        soup = BeautifulSoup(html_structure, 'html.parser')
        news_links = soup.find_all('a', href=lambda x: x and any(kw in x.lower() for kw in ['news', 'announcement']))
        print(f"[DEBUG] Found {len(news_links)} potential news/announcement links in extracted HTML")
        
        # If extracted HTML is too small or has no links, extract from full HTML
        if len(html_structure) < 5000 or len(news_links) == 0:
            print("[WARNING] Extracted HTML seems incomplete, extracting from full HTML")
            # Extract just the body or main content from full HTML
            full_soup = BeautifulSoup(html, 'html.parser')
            for script in full_soup(["script", "style", "noscript"]):
                script.decompose()
            body = full_soup.find('body')
            if body:
                # First try to find ul.rc92w2 directly (this contains the actual articles)
                news_list = body.find('ul', class_=lambda x: x and 'rc92w2' in str(x))
                if news_list:
                    html_structure = str(news_list)
                    print(f"[DEBUG] Using full news list from body ({len(html_structure)} chars)")
                else:
                    # Fallback: try to find section.rc92 and get ul.rc92w2 inside it
                    news_section = body.find('section', class_=lambda x: x and 'rc92' in str(x))
                    if news_section:
                        news_list = news_section.find('ul', class_=lambda x: x and 'rc92w2' in str(x))
                        if news_list:
                            html_structure = str(news_list)
                            print(f"[DEBUG] Using news list from section ({len(html_structure)} chars)")
                        else:
                            # Get the entire section as fallback
                            html_structure = str(news_section)
                            print(f"[DEBUG] Using full news section from body ({len(html_structure)} chars)")
                    else:
                        # Get all news/announcement links with their full parent context
                        links_html = []
                        seen_hrefs = set()
                        for link in body.find_all('a', href=lambda x: x and any(kw in x.lower() for kw in ['news', 'announcement'])):
                            href = link.get('href', '')
                            # Skip duplicates and filter links
                            if href in seen_hrefs or not href or href == '#' or '?' in href:
                                continue
                            # Skip if it's just the main news page
                            if href.endswith('/news/') or href.endswith('/news'):
                                continue
                            seen_hrefs.add(href)
                            
                            # Get parent with more context - try to get the full article container
                            parent = link.find_parent(['li', 'div', 'article', 'section'])
                            if parent:
                                # Try to get even more context - the parent's parent if it's a list item
                                if parent.name == 'li':
                                    grandparent = parent.find_parent(['ul', 'ol', 'section', 'div'])
                                    if grandparent:
                                        links_html.append(str(grandparent))
                                    else:
                                        links_html.append(str(parent))
                                else:
                                    links_html.append(str(parent))
                        
                        if links_html:
                            html_structure = '\n'.join(links_html)
                            print(f"[DEBUG] Using {len(links_html)} link contexts from body ({len(html_structure)} chars)")
                        else:
                            # Last resort: use main content area or body
                            main = body.find('main')
                            if main:
                                html_structure = str(main)
                                print(f"[DEBUG] Using main content area ({len(html_structure)} chars)")
                            else:
                                html_structure = str(body)
                                print(f"[DEBUG] Using full body as fallback ({len(html_structure)} chars)")
        
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
                'link': art['link']
            })
        
        # Add any LLM results that weren't found by direct extraction
        filtered_count = 0
        for llm_art in llm_articles:
            llm_link = llm_art.get('link', '')
            llm_title = llm_art.get('title', '')
            
            # Only add if not already found and is a valid article link
            if llm_link not in direct_links and llm_link != 'N/A':
                # Check if it's a valid article link
                is_valid = False
                
                # Accept links that contain news/announcement keywords
                if '/news/' in llm_link or '/announcement/' in llm_link:
                    # Make sure it's not just the main page
                    if not llm_link.endswith('/news/') and not llm_link.endswith('/news'):
                        is_valid = True
                # Also accept oracle.com links with meaningful paths (not just homepage)
                elif 'oracle.com' in llm_link and llm_link != 'https://www.oracle.com' and llm_link != 'https://www.oracle.com/':
                    # Check if it has a meaningful path (more than just domain)
                    path = llm_link.split('oracle.com', 1)[-1] if 'oracle.com' in llm_link else ''
                    if path and len(path) > 5 and path != '/' and not path.startswith('/#'):
                        # Check if title is meaningful (not empty, not too short)
                        if llm_title and len(llm_title) > 10:
                            is_valid = True
                
                if is_valid:
                    articles.append(llm_art)
                else:
                    filtered_count += 1
                    if filtered_count <= 5:  # Log first 5 filtered articles for debugging
                        print(f"[DEBUG] Filtered out LLM article: {llm_title[:50]}... ({llm_link[:80]})")
        
        if filtered_count > 0:
            print(f"[DEBUG] Filtered out {filtered_count} LLM articles that didn't match validation criteria")
        
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
            print(f"  Title: {article['title']}")
            print(f"  Date:  {article['date']}")
            print(f"  Link:  {article['link']}")
            print("-" * 80)
    
    def save_to_json(self, articles: List[Dict], filename: str = "oracle_news.json"):
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
        print("  3. Provide it as a command line argument: python oracle_news_scraper.py your_api_key")
        return 1
    
    try:
        scraper = OracleNewsScraper(api_key=api_key)
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

