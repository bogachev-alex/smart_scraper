"""
Article Enhancer Scraper
Reads unified JSON file, visits article links, and extracts main ideas and tags
"""

import json
import os
import sys
import re
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from typing import List, Dict, Optional
from collections import defaultdict
import time
import sqlite3
import random
from urllib.parse import urlparse
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import warnings
import logging

# Suppress harmless warnings from undetected_chromedriver
warnings.filterwarnings('ignore', message='.*could not detect version_main.*')
logging.getLogger('undetected_chromedriver').setLevel(logging.ERROR)

# Selenium imports for sites that block regular requests
try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("Warning: Selenium not available. Some sites may fail to load.")

# Load environment variables from .env file
load_dotenv()


class ArticleEnhancer:
    """Enhances articles with main ideas and tags by visiting their links"""
    
    def __init__(self, api_key: str = None, api_keys: List[str] = None):
        """
        Initialize the enhancer with OpenAI API key(s).
        
        Args:
            api_key: Single OpenAI API key (for backward compatibility). If not provided, will try to get from environment.
            api_keys: List of OpenAI API keys for parallel processing. If provided, will use these instead of api_key.
        """
        # Support multiple API keys for parallel processing
        if api_keys:
            self.api_keys = api_keys
            if not all(api_keys):
                raise ValueError("All API keys in api_keys list must be non-empty")
        else:
            # Single API key mode (backward compatible)
            single_key = api_key or os.getenv("OPENAI_API_KEY")
            if not single_key:
                raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY in .env file or provide it as argument.")
            self.api_keys = [single_key]
        
        # Create a client for each API key
        self.clients = [OpenAI(api_key=key) for key in self.api_keys]
        self.num_keys = len(self.api_keys)
        
        # Thread-safe round-robin counter for key selection
        self._key_counter = 0
        self._key_lock = threading.Lock()
        
        # For backward compatibility, keep self.client pointing to first client
        self.client = self.clients[0]
        
        # Store database path for checking existing articles
        self.db_path = None
        
        self.session = requests.Session()
        # More realistic browser headers to avoid blocking
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0'
        })
        # Domains that typically require Selenium (known to block requests)
        self.selenium_domains = ['hpe.com', 'servicenow.com']
    
    def _get_next_client(self) -> OpenAI:
        """
        Get the next OpenAI client in round-robin fashion (thread-safe).
        
        Returns:
            OpenAI client instance
        """
        with self._key_lock:
            client = self.clients[self._key_counter]
            self._key_counter = (self._key_counter + 1) % self.num_keys
            return client
    
    def load_articles(self, filename: str = 'all_scraped_articles.json') -> List[Dict]:
        """Load articles from unified JSON file in data/ folder"""
        from pathlib import Path
        
        # Check data/ folder first, then root for backward compatibility
        current_dir = Path(__file__).parent
        data_dir = current_dir / "data"
        
        filepath = data_dir / filename
        if not filepath.exists():
            filepath = current_dir / filename
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                articles = json.load(f)
            print(f"Loaded {len(articles)} articles from {filepath}")
            return articles
        except FileNotFoundError:
            print(f"Error: File {filepath} not found")
            return []
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {e}")
            return []
    
    def group_by_source(self, articles: List[Dict]) -> Dict[str, List[Dict]]:
        """Group articles by source (vendor)"""
        grouped = defaultdict(list)
        for article in articles:
            source = article.get('source', 'Unknown')
            grouped[source].append(article)
        return dict(grouped)
    
    def select_test_articles(self, grouped_articles: Dict[str, List[Dict]], per_vendor: int = 3) -> List[Dict]:
        """Select N articles from each vendor for testing"""
        test_articles = []
        for source, articles in grouped_articles.items():
            selected = articles[:per_vendor]
            test_articles.extend(selected)
            print(f"Selected {len(selected)} articles from {source}")
        return test_articles
    
    def _should_use_selenium(self, url: str) -> bool:
        """Check if URL domain requires Selenium"""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        return any(selenium_domain in domain for selenium_domain in self.selenium_domains)
    
    def _safe_quit_driver(self, driver):
        """Safely quit Chrome driver, handling any errors"""
        if driver is None:
            return
        try:
            driver.quit()
        except Exception:
            # Ignore all quit errors - driver may already be closed or handle invalid
            pass
        finally:
            # Try to force cleanup
            try:
                if hasattr(driver, 'service') and driver.service:
                    try:
                        driver.service.process.terminate()
                    except:
                        pass
            except:
                pass
    
    def _extract_formatted_text(self, content) -> str:
        """
        Extract text from HTML content while preserving original formatting.
        Keeps paragraphs, line breaks, and spacing for readability.
        
        Args:
            content: BeautifulSoup element containing the article content
            
        Returns:
            Formatted text string with preserved structure
        """
        if not content:
            return ""
        
        # Get text with newlines preserved for block elements
        # Use separator='\n' for block elements to preserve paragraph structure
        text = content.get_text(separator='\n', strip=True)
        
        # Clean up excessive blank lines (more than 2 consecutive newlines)
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Clean up spaces around newlines but keep the newlines
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            # Strip each line but keep empty lines for paragraph breaks
            cleaned_line = line.strip()
            if cleaned_line:  # Non-empty line
                # Normalize multiple spaces to single space within the line
                cleaned_line = re.sub(r' +', ' ', cleaned_line)
                cleaned_lines.append(cleaned_line)
            elif cleaned_lines and cleaned_lines[-1]:  # Empty line after non-empty line (paragraph break)
                cleaned_lines.append('')
        
        # Join with newlines to preserve paragraph structure
        formatted_text = '\n'.join(cleaned_lines)
        
        # Remove leading/trailing whitespace
        return formatted_text.strip()
    
    def _extract_cleaned_text(self, content) -> str:
        """
        Extract text from HTML content for LLM analysis (cleaned, single line).
        
        Args:
            content: BeautifulSoup element containing the article content
            
        Returns:
            Cleaned text string suitable for LLM processing
        """
        if not content:
            return ""
        
        text = content.get_text(separator=' ', strip=True)
        # Clean up excessive whitespace
        text = ' '.join(text.split())
        return text
    
    def _fetch_with_selenium(self, url: str, max_retries: int = 2, use_headless: bool = True) -> Optional[str]:
        """Fetch article content using Selenium (for sites that block regular requests)
        
        Args:
            url: URL to fetch
            max_retries: Maximum number of retry attempts
            use_headless: Whether to use headless mode (will fallback to non-headless if access denied)
        """
        if not SELENIUM_AVAILABLE:
            print("  Selenium not available, cannot fetch this URL")
            return None
        
        def detect_access_denied(html: str) -> bool:
            """Detect if HTML indicates access denied or blocking."""
            if not html:
                return False
            html_lower = html.lower()
            error_indicators = [
                'access denied', 'access forbidden', 'you don\'t have permission',
                'you do not have permission', '403 forbidden', 'forbidden', 'blocked',
                'errors.edgesuite.net', 'reference #', 'cloudflare', 'checking your browser',
                'ddos protection', 'captcha', 'bot detection', 'automated access',
                'please verify you are human', 'err_http2_protocol_error',
                'this site can\'t be reached', 'connection refused', 'temporarily down'
            ]
            return any(indicator in html_lower for indicator in error_indicators)
        
        driver = None
        last_exception = None
        
        # For ServiceNow and other strict sites, try non-headless first (more realistic)
        parsed_url = urlparse(url)
        initial_headless = use_headless and ('servicenow.com' not in parsed_url.netloc.lower())
        
        # Try headless first, then non-headless
        headless_modes = [initial_headless, False] if initial_headless else [False]
        
        for selenium_attempt in range(max_retries):
            for current_headless in headless_modes:
                try:
                    if selenium_attempt > 0 or (current_headless != initial_headless):
                        print(f"  Selenium retry attempt {selenium_attempt + 1}/{max_retries} (headless={current_headless})...")
                        time.sleep(3 * (selenium_attempt + 1))  # Exponential backoff
                    
                    print(f"  Using Selenium to bypass bot protection (headless={current_headless})...")
                    options = uc.ChromeOptions()
                    
                    if current_headless:
                        options.add_argument('--headless=new')  # Use new headless mode
                    else:
                        # Use non-headless mode for better stealth
                        options.add_argument('--start-maximized')
                        options.add_argument('--window-size=1920,1080')
                    
                    options.add_argument('--disable-blink-features=AutomationControlled')
                    options.add_argument('--disable-dev-shm-usage')
                    options.add_argument('--no-sandbox')
                    options.add_argument('--disable-gpu')
                    # Force HTTP/1.1 to avoid HTTP/2 protocol errors
                    options.add_argument('--disable-http2')
                    options.add_argument('--disable-quic')
                    # Additional options for better compatibility
                    options.add_argument('--disable-web-security')
                    options.add_argument('--ignore-certificate-errors')
                    options.add_argument('--ignore-ssl-errors')
                    options.add_argument('--allow-running-insecure-content')
                    
                    # Make browser look more realistic (if not already set)
                    if not current_headless:
                        options.add_argument('--window-size=1920,1080')
                        options.add_argument('--start-maximized')
                    
                    # Set user agent
                    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
                    
                    # Add preferences to make browser less detectable
                    prefs = {
                        "profile.default_content_setting_values": {
                            "notifications": 2
                        },
                        "profile.managed_default_content_settings": {
                            "images": 1
                        }
                    }
                    options.add_experimental_option("prefs", prefs)
                    
                    driver = uc.Chrome(options=options, version_main=None)
                    
                    # Execute script to hide webdriver property
                    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                        'source': '''
                            Object.defineProperty(navigator, 'webdriver', {
                                get: () => undefined
                            });
                            window.chrome = {
                                runtime: {}
                            };
                        '''
                    })
                    
                    # Set page load timeout
                    driver.set_page_load_timeout(60)
                    
                    print(f"  Loading page: {url}")
                    driver.get(url)
                    
                    # Wait for page to load and check for errors
                    time.sleep(10)  # Give more time for JavaScript to render and security checks
                    
                    # Check if we got an error page or access denied
                    page_source = driver.page_source
                    if detect_access_denied(page_source):
                        print(f"  Access denied or error page detected")
                        self._safe_quit_driver(driver)
                        driver = None
                        
                        # If we're in headless mode, try non-headless next
                        if current_headless:
                            print("  [RETRY] Retrying with non-headless browser (better stealth)...")
                            continue  # Continue to next iteration (non-headless)
                        else:
                            # Already tried non-headless, try next retry attempt
                            if selenium_attempt < max_retries - 1:
                                time.sleep(5)  # Wait longer before retry
                                continue
                            else:
                                print(f"  Failed to load page after {max_retries} attempts (blocked by server)")
                                return None
                    
                    # Check current URL to see if we were redirected to an error page
                    current_url = driver.current_url
                    if 'error' in current_url.lower() or 'blocked' in current_url.lower():
                        print(f"  Redirected to error page: {current_url}")
                        if selenium_attempt < max_retries - 1:
                            self._safe_quit_driver(driver)
                            continue
                    
                    # Get page source
                    html = driver.page_source
                    
                    # Final check for access denied
                    if detect_access_denied(html):
                        print(f"  Access denied detected in final HTML")
                        self._safe_quit_driver(driver)
                        driver = None
                        
                        # If we're in headless mode, try non-headless
                        if current_headless:
                            print("  [RETRY] Retrying with non-headless browser (better stealth)...")
                            continue  # Continue to next iteration (non-headless)
                        else:
                            # Already tried non-headless, try next retry attempt
                            if selenium_attempt < max_retries - 1:
                                continue
                            else:
                                print(f"  Failed to load page after {max_retries} attempts (blocked by server)")
                                return None
                    
                    # Check if we got meaningful content
                    if len(html) < 1000:
                        print(f"  Page content too short ({len(html)} chars), might be an error page")
                        if selenium_attempt < max_retries - 1:
                            self._safe_quit_driver(driver)
                            driver = None
                            continue
                    
                    # Properly close driver before parsing (to free resources)
                    self._safe_quit_driver(driver)
                    driver = None
                
                    # Parse with BeautifulSoup
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Remove script and style elements
                    for script in soup(["script", "style", "nav", "header", "footer", "aside"]):
                        script.decompose()
                    
                    # Try to find main content area
                    content_selectors = [
                        'article',
                        'main',
                        '[role="main"]',
                        '.article-content',
                        '.post-content',
                        '.entry-content',
                        '.content',
                        'div[class*="article"]',
                        'div[class*="content"]',
                        'div[class*="post"]'
                    ]
                    
                    content = None
                    for selector in content_selectors:
                        content = soup.select_one(selector)
                        if content:
                            break
                    
                    # If no specific content area found, use body
                    if not content:
                        content = soup.find('body')
                    
                    if content:
                        # Extract cleaned text for length checking
                        text = self._extract_cleaned_text(content)
                        if len(text) >= 100:
                            # Return formatted text with preserved structure
                            formatted_text = self._extract_formatted_text(content)
                            print(f"  Successfully extracted {len(formatted_text)} characters of content (formatted)")
                            return formatted_text[:50000]
                        else:
                            print(f"  Content too short ({len(text)} chars)")
                            if selenium_attempt < max_retries - 1:
                                continue
                    
                    # If we got here and it's the last attempt, return what we have
                    if selenium_attempt == max_retries - 1:
                        if content:
                            text = self._extract_cleaned_text(content)
                            if len(text) > 0:
                                formatted_text = self._extract_formatted_text(content)
                                print(f"  Returning content despite being short ({len(formatted_text)} chars, formatted)")
                                return formatted_text[:50000]
                    
                    return None
                    
                except Exception as e:
                    print(f"  Selenium error (attempt {selenium_attempt + 1}/{max_retries}): {e}")
                    self._safe_quit_driver(driver)
                    driver = None
                    
                    # If this was the last attempt, return None
                    if selenium_attempt == max_retries - 1:
                        return None
        
        return None
    
    def fetch_article_content(self, url: str, max_retries: int = 3) -> Optional[str]:
        """Fetch and extract main content from article URL with retry logic"""
        # Check if this domain requires Selenium
        if self._should_use_selenium(url):
            print("  Domain requires Selenium, using browser automation...")
            return self._fetch_with_selenium(url)
        
        # Try regular requests first
        for attempt in range(max_retries):
            try:
                # Increase timeout and add retry delay with randomization
                timeout = (30, 60)  # Connection and read timeout tuple
                if attempt > 0:
                    # Exponential backoff with randomization: 3-5s, 6-10s, 12-20s
                    base_wait = 3 * (2 ** attempt)
                    wait_time = base_wait + random.uniform(0, base_wait * 0.5)
                    print(f"  Retry attempt {attempt + 1}/{max_retries} after {wait_time:.1f}s...")
                    time.sleep(wait_time)
                
                # Add small random delay before request to appear more human-like
                if attempt == 0:
                    time.sleep(random.uniform(0.5, 1.5))
                
                # Update referer header for subsequent requests
                if attempt > 0:
                    # Extract domain for referer
                    parsed = urlparse(url)
                    domain = f"{parsed.scheme}://{parsed.netloc}"
                    self.session.headers['Referer'] = domain
                
                response = self.session.get(url, timeout=timeout, allow_redirects=True)
                response.raise_for_status()
                
                # Handle encoding properly - use apparent_encoding which detects from content
                if not response.encoding or response.encoding.lower() in ['iso-8859-1', 'latin1']:
                    # If encoding is not set or is a fallback, use apparent_encoding
                    response.encoding = response.apparent_encoding or 'utf-8'
                
                # Use response.text which handles encoding automatically
                # If there are still encoding issues, decode with error handling
                try:
                    html_content = response.text
                except (UnicodeDecodeError, UnicodeError):
                    # Fallback: decode with error handling
                    encoding = response.encoding or response.apparent_encoding or 'utf-8'
                    html_content = response.content.decode(encoding, errors='replace')
                
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # Remove script and style elements
                for script in soup(["script", "style", "nav", "header", "footer", "aside"]):
                    script.decompose()
                
                # Try to find main content area
                # Common selectors for article content
                content_selectors = [
                    'article',
                    'main',
                    '[role="main"]',
                    '.article-content',
                    '.post-content',
                    '.entry-content',
                    '.content',
                    'div[class*="article"]',
                    'div[class*="content"]',
                    'div[class*="post"]'
                ]
                
                content = None
                for selector in content_selectors:
                    content = soup.select_one(selector)
                    if content:
                        break
                
                # If no specific content area found, use body
                if not content:
                    content = soup.find('body')
                
                if content:
                    # Get cleaned text for length checking
                    text = self._extract_cleaned_text(content)
                    
                    # Check if content is meaningful (at least 100 characters)
                    if len(text) < 100:
                        # For IBM campaign pages, try to find content in different selectors
                        if 'newsroom.ibm.com' in url:
                            # Try IBM-specific selectors
                            ibm_selectors = [
                                '.wd_item',
                                '.wd_content',
                                '.wd_summary',
                                '.wd_description',
                                'div[class*="wd_"]',
                                '.campaign-content'
                            ]
                            for selector in ibm_selectors:
                                ibm_content = soup.select_one(selector)
                                if ibm_content:
                                    ibm_text = self._extract_cleaned_text(ibm_content)
                                    if len(ibm_text) >= 100:
                                        text = ibm_text
                                        content = ibm_content  # Update content for formatted extraction
                                        break
                        
                        # If still too short after trying specific selectors, retry
                        if len(text) < 100:
                            if attempt < max_retries - 1:
                                print(f"  Content too short ({len(text)} chars), retrying...")
                                continue  # Retry
                            else:
                                print(f"  Warning: Content is very short ({len(text)} chars), but proceeding...")
                    
                    if len(text) > 0:
                        # Return formatted text with preserved structure for original_text
                        formatted_text = self._extract_formatted_text(content)
                        return formatted_text[:50000]  # Limit to avoid token limits
                
                # If we got here but no content, retry
                if attempt < max_retries - 1:
                    print(f"  No content found, retrying...")
                    continue
                return None
                
            except requests.exceptions.Timeout as e:
                print(f"  Timeout error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    # Try Selenium as last resort
                    print(f"  All requests failed, trying Selenium as fallback...")
                    return self._fetch_with_selenium(url) if SELENIUM_AVAILABLE else None
            except requests.exceptions.ConnectionError as e:
                print(f"  Connection error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    # Try Selenium as last resort
                    print(f"  All requests failed, trying Selenium as fallback...")
                    return self._fetch_with_selenium(url) if SELENIUM_AVAILABLE else None
            except requests.RequestException as e:
                print(f"  Request error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    # Try Selenium as last resort
                    print(f"  All requests failed, trying Selenium as fallback...")
                    return self._fetch_with_selenium(url) if SELENIUM_AVAILABLE else None
            except Exception as e:
                print(f"  Unexpected error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    # Try Selenium as last resort
                    print(f"  All requests failed, trying Selenium as fallback...")
                    return self._fetch_with_selenium(url) if SELENIUM_AVAILABLE else None
        
        return None
    
    def check_article_exists(self, url: str, db_path: str = None) -> Optional[Dict]:
        """
        Check if an article with the given URL already exists in the database.
        
        Args:
            url: Article URL to check
            db_path: Database path. If not provided, uses self.db_path.
            
        Returns:
            Dictionary with article data if exists, None otherwise
        """
        db = db_path or self.db_path
        if not db:
            return None
        
        try:
            conn = sqlite3.connect(db)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT title, date, link, description, source, main_ideas, tags, original_text
                FROM articles 
                WHERE link = ?
            ''', (url,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                # Convert database row to dictionary
                return {
                    'title': row[0],
                    'date': row[1],
                    'link': row[2],
                    'description': row[3],
                    'source': row[4],
                    'main_ideas': json.loads(row[5]) if row[5] else [],
                    'tags': json.loads(row[6]) if row[6] else [],
                    'original_text': row[7] if row[7] else ''
                }
            return None
        except Exception as e:
            print(f"  Warning: Error checking database for {url}: {e}")
            return None
    
    def extract_main_ideas_and_tags(self, article_content: str, title: str = "", description: str = "", client: OpenAI = None) -> Dict[str, any]:
        """
        Use OpenAI LLM to extract main ideas and tags from article content.
        
        Args:
            article_content: Main text content of the article
            title: Article title (for context)
            description: Article description (for context)
            client: OpenAI client to use. If not provided, uses round-robin selection.
            
        Returns:
            Dictionary with 'main_ideas' (list) and 'tags' (list)
        """
        # Use provided client or get next one in round-robin
        if client is None:
            client = self._get_next_client()
        
        # Limit content size to avoid token limits
        content_limit = 40000
        limited_content = article_content[:content_limit] if len(article_content) > content_limit else article_content
        
        prompt = f"""You are analyzing a news article to extract its main ideas and relevant tags.

Article Title: {title}
Article Description: {description if description else 'N/A'}

Article Content:
{limited_content}

Your task:
1. Extract 3-5 main ideas from the article. Each main idea should be a concise sentence (10-20 words) that captures a key point or theme.
2. Extract 5-10 relevant tags. Tags should be:
   - Single words or short phrases (1-3 words)
   - Relevant to the article's topics, technologies, industries, or themes
   - Use lowercase and separate multi-word tags with hyphens (e.g., "artificial-intelligence", "cloud-computing")
   - Include technology names, company names, industry terms, and topic keywords

Return a JSON object with this structure:
{{
  "main_ideas": [
    "First main idea in a concise sentence",
    "Second main idea in a concise sentence",
    "Third main idea in a concise sentence"
  ],
  "tags": [
    "tag1",
    "tag2",
    "tag3"
  ]
}}

Return ONLY valid JSON. No explanations, no markdown, just the JSON object."""

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are an expert at analyzing news articles and extracting key information. Return only valid JSON with main_ideas and tags arrays."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=2000
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
            result = json.loads(result_text)
            
            # Ensure we have the right structure
            return {
                "main_ideas": result.get("main_ideas", []),
                "tags": result.get("tags", [])
            }
            
        except json.JSONDecodeError as e:
            print(f"Error parsing LLM response: {e}")
            print(f"Response was: {result_text[:200]}")
            return {"main_ideas": [], "tags": []}
        except Exception as e:
            print(f"Error calling OpenAI API: {e}")
            return {"main_ideas": [], "tags": []}
    
    def enhance_article(self, article: Dict, client: OpenAI = None, db_path: str = None) -> Dict:
        """
        Enhance a single article with main ideas and tags.
        
        Args:
            article: Article dictionary to enhance
            client: OpenAI client to use. If not provided, uses round-robin selection.
            db_path: Database path to check for existing articles. If not provided, uses self.db_path.
            
        Returns:
            Enhanced article dictionary
        """
        url = article.get('link', '')
        title = article.get('title', '')
        description = article.get('description', '')
        
        if not url:
            print(f"Skipping article '{title}' - no URL")
            return {**article, "main_ideas": [], "tags": [], "original_text": ""}
        
        print(f"\nProcessing: {title}")
        print(f"URL: {url}")
        
        # Check if article already exists in database
        existing_article = self.check_article_exists(url, db_path=db_path)
        content = None
        
        if existing_article:
            # Check if existing article has content and enhancements
            if existing_article.get('original_text') and existing_article.get('main_ideas'):
                print(f"  Article already exists in database with content and enhancements. Skipping fetch and enhancement.")
                # Merge existing data with article data (prefer article data for metadata, keep existing for enhancements)
                enhanced = {**article}
                enhanced["main_ideas"] = existing_article.get("main_ideas", [])
                enhanced["tags"] = existing_article.get("tags", [])
                enhanced["original_text"] = existing_article.get("original_text", "")
                return enhanced
            elif existing_article.get('original_text'):
                # Has content but no enhancements - skip fetch, use existing content for enhancement
                print(f"  Article exists in database but needs enhancement. Using existing content (skipping fetch).")
                content = existing_article.get('original_text', '')
        
        # Fetch article content if we don't have it from database
        if content is None:
            content = self.fetch_article_content(url)
            if not content:
                print(f"  Warning: Could not fetch content for {url}")
                return {**article, "main_ideas": [], "tags": [], "original_text": ""}
            
            print(f"  Fetched {len(content)} characters of content")
        
        # Extract main ideas and tags (use cleaned text for LLM analysis)
        # Content is already formatted text, so clean it for LLM but keep formatted for storage
        cleaned_content = ' '.join(content.split())  # Clean for LLM processing
        
        # Use provided client or get next one in round-robin
        if client is None:
            client = self._get_next_client()
        
        extracted = self.extract_main_ideas_and_tags(cleaned_content, title, description, client=client)
        print(f"  Extracted {len(extracted['main_ideas'])} main ideas and {len(extracted['tags'])} tags")
        
        # Reduced delay when using multiple keys (rate limits are per-key)
        # With multiple keys, we can process faster
        delay = 0.2 if self.num_keys > 1 else 1.0
        time.sleep(delay)
        
        # Return enhanced article with original text (formatted for readability)
        enhanced = {**article}
        enhanced["main_ideas"] = extracted["main_ideas"]
        enhanced["tags"] = extracted["tags"]
        # Store original article text with preserved formatting for readability
        enhanced["original_text"] = content
        return enhanced
    
    def enhance_articles(self, articles: List[Dict], max_workers: int = None, db_path: str = None) -> List[Dict]:
        """
        Enhance multiple articles with parallel processing when multiple API keys are available.
        
        Args:
            articles: List of article dictionaries to enhance
            max_workers: Maximum number of parallel workers. Defaults to number of API keys.
            db_path: Database path to check for existing articles. If not provided, uses self.db_path.
            
        Returns:
            List of enhanced article dictionaries
        """
        # Use provided db_path or fall back to instance variable
        db = db_path or self.db_path
        
        total = len(articles)
        
        # If only one key, process sequentially (backward compatible)
        if self.num_keys == 1:
            enhanced = []
            for i, article in enumerate(articles, 1):
                print(f"\n[{i}/{total}] Processing article...")
                enhanced_article = self.enhance_article(article, db_path=db)
                enhanced.append(enhanced_article)
            return enhanced
        
        # Multiple keys: use parallel processing
        if max_workers is None:
            max_workers = min(self.num_keys, total)  # Don't use more workers than articles or keys
        
        print(f"\nUsing {max_workers} parallel workers with {self.num_keys} API key(s)")
        
        enhanced = []
        completed = 0
        
        # Use ThreadPoolExecutor for parallel processing
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks with db_path parameter
            future_to_article = {
                executor.submit(self.enhance_article, article, None, db): article 
                for article in articles
            }
            
            # Process completed tasks as they finish
            for future in as_completed(future_to_article):
                article = future_to_article[future]
                completed += 1
                try:
                    enhanced_article = future.result()
                    enhanced.append(enhanced_article)
                    print(f"\n[{completed}/{total}] Completed: {article.get('title', 'Unknown')[:50]}...")
                except Exception as e:
                    print(f"\n[{completed}/{total}] Error processing article '{article.get('title', 'Unknown')}': {e}")
                    # Add article with empty enhancement on error
                    enhanced.append({**article, "main_ideas": [], "tags": [], "original_text": ""})
        
        # Sort results to maintain original order (since parallel execution may complete out of order)
        # Create a mapping of article links to their positions (link is unique identifier)
        article_positions = {article.get('link', ''): i for i, article in enumerate(articles)}
        enhanced.sort(key=lambda x: article_positions.get(x.get('link', ''), len(articles)))
        
        return enhanced
    
    def save_enhanced_articles_json(self, articles: List[Dict], filename: str = 'all_scraped_articles_enhanced.json'):
        """Save enhanced articles to JSON file (for debugging)"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(articles, f, indent=2, ensure_ascii=False)
        print(f"\nSaved {len(articles)} enhanced articles to {filename} (debug)")
    
    def init_database(self, db_path: str = 'articles_enhanced.db'):
        """Initialize SQLite database and create table if it doesn't exist"""
        # Store database path for later use
        self.db_path = db_path
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                date TEXT,
                link TEXT UNIQUE NOT NULL,
                description TEXT,
                source TEXT,
                main_ideas TEXT,
                tags TEXT,
                original_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create index on link for faster lookups
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_link ON articles(link)
        ''')
        
        # Create index on source for filtering
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_source ON articles(source)
        ''')
        
        conn.commit()
        conn.close()
        print(f"Database initialized: {db_path}")
    
    def save_enhanced_articles_db(self, articles: List[Dict], db_path: str = 'articles_enhanced.db'):
        """Save enhanced articles to SQLite database"""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        saved_count = 0
        updated_count = 0
        
        for article in articles:
            # Convert lists to JSON strings for storage
            main_ideas_json = json.dumps(article.get('main_ideas', []), ensure_ascii=False)
            tags_json = json.dumps(article.get('tags', []), ensure_ascii=False)
            original_text = article.get('original_text', '')
            
            # Exclude description for IBM articles
            source = article.get('source', '').lower()
            if source in ['ibm', 'ibm news']:
                description = ''  # Don't copy description for IBM articles
            else:
                description = article.get('description', '')
            
            # Check if article already exists
            cursor.execute('SELECT id FROM articles WHERE link = ?', (article.get('link', ''),))
            existing = cursor.fetchone()
            
            if existing:
                # Update existing article
                cursor.execute('''
                    UPDATE articles 
                    SET title = ?, date = ?, description = ?, source = ?,
                        main_ideas = ?, tags = ?, original_text = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE link = ?
                ''', (
                    article.get('title', ''),
                    article.get('date', ''),
                    description,  # Use filtered description
                    article.get('source', ''),
                    main_ideas_json,
                    tags_json,
                    original_text,
                    article.get('link', '')
                ))
                updated_count += 1
            else:
                # Insert new article
                cursor.execute('''
                    INSERT INTO articles 
                    (title, date, link, description, source, main_ideas, tags, original_text)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    article.get('title', ''),
                    article.get('date', ''),
                    article.get('link', ''),
                    description,  # Use filtered description
                    article.get('source', ''),
                    main_ideas_json,
                    tags_json,
                    original_text
                ))
                saved_count += 1
        
        conn.commit()
        conn.close()
        print(f"Saved {saved_count} new articles and updated {updated_count} existing articles to database: {db_path}")


def main():
    """Main function to run the enhancer"""
    # Get API key from .env file (loaded by load_dotenv()) or command line
    api_key = os.getenv("OPENAI_API_KEY") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not api_key:
        raise ValueError("OPENAI_API_KEY must be set in .env file or provided as command line argument")
    
    # Initialize enhancer
    enhancer = ArticleEnhancer(api_key=api_key)
    
    # Load articles
    articles = enhancer.load_articles('all_scraped_articles.json')
    if not articles:
        print("No articles to process")
        return
    
    # Group by source and select test articles (3 per vendor)
    grouped = enhancer.group_by_source(articles)
    print(f"\nFound articles from {len(grouped)} vendors:")
    for source, source_articles in grouped.items():
        print(f"  {source}: {len(source_articles)} articles")
    
    test_articles = enhancer.select_test_articles(grouped, per_vendor=3)
    print(f"\nSelected {len(test_articles)} articles for testing (3 per vendor)")
    
    # Initialize database
    enhancer.init_database('articles_enhanced.db')
    
    # Enhance articles
    enhanced_articles = enhancer.enhance_articles(test_articles)
    
    # Save enhanced articles to JSON (for debugging)
    enhancer.save_enhanced_articles_json(enhanced_articles, 'all_scraped_articles_enhanced.json')
    
    # Save enhanced articles to SQLite database
    enhancer.save_enhanced_articles_db(enhanced_articles, 'articles_enhanced.db')
    
    # Print summary
    print("\n=== Summary ===")
    for article in enhanced_articles:
        print(f"\n{article.get('title', 'N/A')}")
        print(f"  Source: {article.get('source', 'N/A')}")
        print(f"  Main Ideas: {len(article.get('main_ideas', []))}")
        print(f"  Tags: {', '.join(article.get('tags', [])[:5])}..." if article.get('tags') else "  Tags: None")


if __name__ == "__main__":
    main()

