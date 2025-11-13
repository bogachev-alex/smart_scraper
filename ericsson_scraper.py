"""
LLM-based scraper for extracting structured data from Ericsson newsroom page.
Extracts: title, date, link, description
"""

import requests
from bs4 import BeautifulSoup
from openai import OpenAI
import json
import os
import time
import re
from typing import List, Dict
from dotenv import load_dotenv
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Load environment variables
load_dotenv()


class EricssonScraper:
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
            options.add_argument('--start-maximized')
            options.add_argument('--disable-blink-features=AutomationControlled')
            
            driver = uc.Chrome(options=options, version_main=None)
            
            print("Loading page (bypassing security checks)...")
            driver.get(self.url)
            
            # Wait for security check to complete
            print("Waiting for security verification...")
            time.sleep(8)  # Give time for any security checks to complete
            
            # Check if we're on a security check page
            page_source_lower = driver.page_source.lower()
            security_keywords = ['imperva', 'incapsula', 'security check', 'additional security', 'verify you are human', 'cloudflare']
            
            if any(keyword in page_source_lower for keyword in security_keywords):
                print("\n[WARNING] Security check detected!")
                print("The page requires manual verification.")
                print("A browser window should be open - please complete the security check manually.")
                print("Waiting for you to complete the check (press Enter when done)...")
                
                # Keep browser open for manual interaction
                input("Press Enter after completing the security check in the browser window...")
                time.sleep(2)
            
            # Wait for actual content to load
            print("Waiting for page content to load...")
            max_wait = 30
            waited = 0
            while waited < max_wait:
                page_source = driver.page_source
                page_source_lower = page_source.lower()
                
                # Check if we're past security checks
                if not any(keyword in page_source_lower for keyword in security_keywords):
                    # Check if we have actual content
                    articles = driver.find_elements(By.TAG_NAME, "article")
                    links = driver.find_elements(By.CSS_SELECTOR, "a[href*='newsroom'], a[href*='news'], a[href*='article']")
                    main_content = driver.find_elements(By.TAG_NAME, "main")
                    
                    if len(articles) > 0 or len(links) > 5 or len(main_content) > 0 or len(page_source) > 20000:
                        print(f"[OK] Content loaded successfully!")
                        break
                
                time.sleep(2)
                waited += 2
                if waited % 4 == 0:
                    print(f"  Still waiting... ({waited}s)")
            
            # Scroll to load lazy-loaded content
            print("Scrolling page to load all content...")
            try:
                # First, look for "Load More" or "Show More" buttons and click them
                load_more_attempts = 0
                max_load_more_attempts = 10
                while load_more_attempts < max_load_more_attempts:
                    try:
                        # Look for various "Load More" button patterns
                        load_more_selectors = [
                            "button:contains('Load More')",
                            "button:contains('Show More')",
                            "button:contains('More')",
                            "a:contains('Load More')",
                            "a:contains('Show More')",
                            "[class*='load-more']",
                            "[class*='show-more']",
                            "[id*='load-more']",
                            "[id*='show-more']"
                        ]
                        
                        load_more_found = False
                        for selector in load_more_selectors:
                            try:
                                # Try to find by text content
                                if ':contains(' in selector:
                                    # Use XPath for text matching
                                    text = selector.split("'")[1]
                                    xpath = f"//button[contains(text(), '{text}')] | //a[contains(text(), '{text}')]"
                                    elements = driver.find_elements(By.XPATH, xpath)
                                else:
                                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                                
                                for element in elements:
                                    if element.is_displayed() and element.is_enabled():
                                        print(f"  Found 'Load More' button, clicking...")
                                        driver.execute_script("arguments[0].scrollIntoView(true);", element)
                                        time.sleep(1)
                                        element.click()
                                        time.sleep(3)  # Wait for new content to load
                                        load_more_found = True
                                        break
                            except:
                                continue
                        
                        if not load_more_found:
                            break
                        
                        load_more_attempts += 1
                    except Exception as e:
                        break
                
                # Scroll to bottom to trigger lazy loading
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                
                # Scroll back up
                driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(1)
                
                # Scroll down gradually to trigger any lazy loading
                scroll_pause_time = 1.5
                last_height = driver.execute_script("return document.body.scrollHeight")
                scroll_count = 0
                max_scrolls = 10  # Increased from 5
                
                while scroll_count < max_scrolls:
                    # Scroll down gradually
                    current_scroll = 0
                    scroll_increment = 500
                    max_scroll = driver.execute_script("return document.body.scrollHeight")
                    
                    while current_scroll < max_scroll:
                        driver.execute_script(f"window.scrollTo(0, {current_scroll});")
                        time.sleep(0.5)
                        current_scroll += scroll_increment
                    
                    # Scroll to bottom
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(scroll_pause_time)
                    
                    # Calculate new scroll height
                    new_height = driver.execute_script("return document.body.scrollHeight")
                    if new_height == last_height:
                        # No new content, try one more time
                        time.sleep(2)
                        new_height = driver.execute_script("return document.body.scrollHeight")
                        if new_height == last_height:
                            break
                    last_height = new_height
                    scroll_count += 1
                    print(f"  Scrolled {scroll_count}/{max_scrolls}, page height: {new_height}")
                
                # Scroll back to top
                driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(2)
            except Exception as e:
                print(f"  Note: Could not scroll (this is okay): {e}")
            
            # Additional wait for JavaScript to fully render
            time.sleep(4)
            
            html = driver.page_source
            print(f"Retrieved HTML: {len(html)} characters")
            
            # Check if we're still on security page
            if any(keyword in html.lower() for keyword in security_keywords):
                print("[ERROR] Still on security check page. Please complete the security check manually.")
                print("The browser window should still be open. Complete the check and press Enter...")
                input("Press Enter after completing security check...")
                time.sleep(5)  # Wait longer after manual check
                html = driver.page_source
                print(f"Retrieved HTML after manual check: {len(html)} characters")
            
            if len(html) < 10000:
                print(f"[WARNING] Retrieved HTML seems too short ({len(html)} chars). The page might still be loading.")
                print("Trying to wait a bit longer...")
                time.sleep(5)
                html = driver.page_source
                print(f"Retrieved HTML after additional wait: {len(html)} characters")
            
            # Try to find article links to verify we have content
            temp_soup = BeautifulSoup(html, 'html.parser')
            test_links = temp_soup.find_all('a', href=lambda x: x and any(kw in x.lower() for kw in ['newsroom', 'news', 'article']))
            print(f"[DEBUG] Found {len(test_links)} newsroom/news links in full HTML")
            
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
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with basic article info (link, title, date, description)
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
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
        
        Args:
            html: Raw HTML content
            
        Returns:
            Cleaned HTML structure as string
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style", "noscript"]):
            script.decompose()
        
        # Try multiple strategies to find content
        # Strategy 1: Look for common news/press content selectors
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
        
        # Strategy 2: Look for links that might be article links
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
            with open("debug_ericsson_full_html.html", "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[DEBUG] Full HTML saved to debug_ericsson_full_html.html ({len(html)} chars)")
        
        # First, try to extract article links directly
        print("Extracting article links directly from HTML...")
        direct_articles = self.extract_article_links(html)
        print(f"[DEBUG] Found {len(direct_articles)} article links using BeautifulSoup")
        
        print("Extracting HTML structure for LLM analysis...")
        html_structure = self.extract_html_structure(html)
        
        if debug:
            with open("debug_ericsson_extracted_html.html", "w", encoding="utf-8") as f:
                f.write(html_structure)
            print(f"[DEBUG] Extracted HTML saved to debug_ericsson_extracted_html.html ({len(html_structure)} chars)")
        
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
    
    def save_to_json(self, articles: List[Dict], filename: str = "ericsson_articles.json"):
        """
        Save results to JSON file.
        
        Args:
            articles: List of article dictionaries
            filename: Output filename
        """
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(articles, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to {filename}")


def main():
    """Main entry point."""
    import sys
    # API key from command line or environment
    api_key = os.getenv("OPENAI_API_KEY") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable must be set or provided as command line argument")
    
    # Check for debug flag
    debug = "--debug" in sys.argv or "-d" in sys.argv
    
    try:
        scraper = EricssonScraper(api_key=api_key)
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

