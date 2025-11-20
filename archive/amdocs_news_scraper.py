"""
LLM-based scraper for extracting structured data from Amdocs news-press page.
Extracts: title, date, link, tags
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


class AmdocsScraper:
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
        self.url = "https://www.amdocs.com/news-press"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def fetch_html(self, use_selenium: bool = True) -> str:
        """
        Fetch HTML content from the Amdocs news-press page.
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
        """Fetch HTML using undetected-chromedriver to bypass Imperva/Incapsula protection."""
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
            time.sleep(8)  # Give time for Imperva check to complete
            
            # Check if we're on a security check page
            page_source_lower = driver.page_source.lower()
            security_keywords = ['imperva', 'incapsula', 'security check', 'additional security', 'verify you are human']
            
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
                    links = driver.find_elements(By.CSS_SELECTOR, "a[href*='news'], a[href*='press'], a[href*='article']")
                    main_content = driver.find_elements(By.TAG_NAME, "main")
                    
                    if len(articles) > 0 or len(links) > 5 or len(main_content) > 0 or len(page_source) > 20000:
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
            test_links = temp_soup.find_all('a', href=lambda x: x and any(kw in x.lower() for kw in ['news', 'press']))
            print(f"[DEBUG] Found {len(test_links)} news/press links in full HTML")
            
            return html
        except Exception as e:
            raise Exception(f"Failed to fetch HTML with Selenium: {str(e)}")
        finally:
            if driver:
                print("Closing browser...")
                driver.quit()
    
    def extract_article_links(self, html: str) -> List[Dict]:
        """
        Extract only Press Release article links using BeautifulSoup.
        Targets the element with id="news_press" which contains all PR articles.
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with basic article info (link, title, date, tags)
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # First, try to find the main container with id="news_press"
        news_press_container = soup.find(id='news_press')
        if not news_press_container:
            # Fallback: look for article with id containing "news_press"
            news_press_container = soup.find('article', id=re.compile(r'news_press', re.IGNORECASE))
        
        if news_press_container:
            print(f"[DEBUG] Found news_press container")
            # Find all article elements within this container that have "Press release" label
            press_release_articles = []
            
            # Find all articles within the news_press container
            for article in news_press_container.find_all('article'):
                # Check if this article has "Press release" label
                has_press_release = False
                marker = article.find(class_=re.compile(r'page-label-test|marker', re.IGNORECASE))
                if marker and 'press release' in marker.get_text(strip=True).lower():
                    has_press_release = True
                else:
                    # Also check if article text contains "Press release"
                    if 'press release' in article.get_text().lower():
                        has_press_release = True
                
                if has_press_release:
                    press_release_articles.append(article)
            
            print(f"[DEBUG] Found {len(press_release_articles)} Press Release articles in news_press container")
        else:
            print("[DEBUG] news_press container not found, using fallback method...")
            # Fallback: find all articles with "Press release" label
            press_release_articles = []
            for article in soup.find_all('article'):
                marker = article.find(class_=re.compile(r'page-label-test|marker', re.IGNORECASE))
                if marker and 'press release' in marker.get_text(strip=True).lower():
                    press_release_articles.append(article)
        
        print(f"[DEBUG] Processing {len(press_release_articles)} Press Release articles")
        
        # Extract data from each Press Release article
        for idx, article in enumerate(press_release_articles):
            # Find the main article link (usually the title link or image link)
            article_links = article.find_all('a', href=True)
            
            # Find the link that points to the actual article (not filter links)
            main_link = None
            for link in article_links:
                href = link.get('href', '')
                # Skip filter links
                if '?f[' in href or '?f%5B' in href:
                    continue
                # Look for links to /news-press/ or /press-release/
                if '/news-press/' in href or '/press-release/' in href:
                    main_link = link
                    break
            
            if not main_link:
                continue
            
            href = main_link.get('href', '')
            if href in ['/news-press', '/news-press/']:
                continue
            
            # Make URL absolute
            if href.startswith('/'):
                full_url = f"https://www.amdocs.com{href}"
            elif href.startswith('http'):
                full_url = href
            else:
                continue
            
            # Avoid duplicates
            if full_url in seen_links:
                continue
            seen_links.add(full_url)
            
            # Extract title
            title = "N/A"
            # Try to find title in h2, h3, h4, h5 within the article
            for heading in article.find_all(['h2', 'h3', 'h4', 'h5']):
                heading_text = heading.get_text(strip=True)
                if heading_text and len(heading_text) > 15:
                    title = heading_text
                    break
            
            # If no heading found, use link text
            if title == "N/A" or len(title) < 15:
                link_text = main_link.get_text(strip=True)
                if link_text and len(link_text) > 15:
                    title = link_text
                else:
                    # Try title attribute
                    title_attr = main_link.get('title', '')
                    if title_attr and len(title_attr) > 15:
                        title = title_attr
            
            # Extract date
            date_text = "N/A"
            article_text = article.get_text()
            date_patterns = [
                r'\b(\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b',
                r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b',
                r'\b\d{4}-\d{2}-\d{2}\b',
            ]
            for pattern in date_patterns:
                match = re.search(pattern, article_text, re.IGNORECASE)
                if match:
                    date_text = match.group(1) if match.lastindex >= 1 else match.group(0)
                    break
            
            # Extract tags
            tags = []
            # Look for tag links within the article
            tag_links = article.find_all('a', href=re.compile(r'/taxonomy/term/|/insights\?f'))
            for tag_link in tag_links:
                tag_text = tag_link.get_text(strip=True)
                if tag_text and tag_text.lower() not in ['press release', 'news'] and len(tag_text) < 50:
                    if tag_text not in tags:
                        tags.append(tag_text)
            
            if not tags:
                tags = ['Press Release']
            
            articles.append({
                'link': full_url,
                'title': title,
                'date': date_text,
                'tags': tags[:5]  # Limit to 5 tags
            })
            
            print(f"[DEBUG] Extracted article {idx+1}: {title[:50]}...")
        
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
            ('div', {'class': lambda x: x and any(keyword in str(x).lower() for keyword in ['news', 'press', 'article', 'release', 'content', 'listing'])}),
            ('section', {'class': lambda x: x and any(keyword in str(x).lower() for keyword in ['news', 'press', 'article', 'release'])}),
            ('ul', {'class': lambda x: x and any(keyword in str(x).lower() for keyword in ['news', 'press', 'article', 'list'])}),
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
                    if text and len(text) > 10 and ('news' in href.lower() or 'press' in href.lower() or 'article' in href.lower() or '/20' in href):
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
        if len(content_str) < 5000 or "incapsula" in content_str.lower() or "imperva" in content_str.lower():
            body = soup.find('body')
            if body:
                # Get ALL links and their full context - be more aggressive
                all_links_context = []
                seen_contexts = set()  # Avoid duplicates
                
                for link in body.find_all('a', href=True):
                    href = link.get('href', '').lower()
                    link_text = link.get_text(strip=True)
                    
                    # Look for news/press/article links
                    if any(keyword in href for keyword in ['news', 'press', 'article', '/20']) or \
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
        # Increased limit to capture more articles
        if len(content_str) > 150000:
            content_str = content_str[:150000] + "..."
        
        return content_str
    
    def analyze_with_llm(self, html_content: str) -> List[Dict]:
        """
        Use OpenAI LLM to extract structured data from HTML.
        
        Args:
            html_content: HTML content to analyze
            
        Returns:
            List of dictionaries with title, date, link, tags
        """
        prompt = f"""You are analyzing HTML from https://www.amdocs.com/news-press page. Your task is to extract ONLY Press Release articles (items labeled as "Press release").

CRITICAL INSTRUCTIONS:
1. Extract ONLY items that are labeled as "Press release" - ignore other content types
2. Look for containers/elements that have "Press release" text or label
3. Each Press Release article card should become a separate entry
4. Do NOT extract filter links (those with ?f[0]= or ?f%5B in URL)
5. Do NOT extract navigation links, category links, or tag links
6. Extract ALL Press Release articles you can find (typically 6-20+ on a listing page)

What to look for:
- Article cards/containers that contain "Press release" label or text
- Links within those containers that point to actual article pages (href containing "/news-press/" with descriptive path)
- Titles/headlines in headings (<h1>, <h2>, <h3>, <h4>) within Press Release containers
- Dates in formats like "11 Nov 2025", "Nov 11, 2025", "2025-11-11", etc.
- Tags/categories within the Press Release container (like "Corporate", "Earnings", "OSS", etc.)
- Skip any links with query parameters like ?f[0]= (these are filter links, not articles)

For EACH article/press release you find, extract:
- title: The headline or title (required - use link text if no explicit title)
- date: Publication date (format as YYYY-MM-DD if possible, otherwise keep original format, use "N/A" if not found)
- link: Full URL (if relative, prepend https://www.amdocs.com. Use "N/A" only if absolutely no link exists)
- tags: List of tags/categories like ["Press Release", "News", "Earnings", "Awards", "Partnership", etc.]. Can be empty [] if none found.

EXAMPLES of what to extract:
- Press releases labeled as "Press release" with dates
- Press release articles with tags like "Corporate", "Earnings", "OSS", "GenAI", etc.

EXAMPLES of what to SKIP:
- Filter links (URLs with ?f[0]= or ?f%5B)
- Navigation links
- Category/tag links
- Links that just say "Press release" (those are filters, not articles)
- Links to /news-press without a specific article path

Return a JSON array with ALL Press Release articles found. Only include items that are clearly labeled as "Press release".

JSON structure:
[
  {{
    "title": "First Article Title",
    "date": "2025-11-11",
    "link": "https://www.amdocs.com/news-press/article-1",
    "tags": ["Press Release"]
  }},
  {{
    "title": "Second Article Title",
    "date": "2025-10-15",
    "link": "https://www.amdocs.com/news-press/article-2",
    "tags": ["News", "Partnership"]
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
                    {"role": "system", "content": "You are a web scraping expert that extracts ALL articles from HTML. You MUST find every single article on the page. Return only valid JSON arrays with all articles found. Be extremely thorough - typical news listing pages have 10-50+ articles."},
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
                        "tags": article.get("tags", []) if isinstance(article.get("tags"), list) else []
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
        print("Fetching HTML from Amdocs news-press page...")
        html = self.fetch_html()
        
        if debug:
            with open("debug_full_html.html", "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[DEBUG] Full HTML saved to debug_full_html.html ({len(html)} chars)")
        
        # First, try to extract article links directly
        print("Extracting article links directly from HTML...")
        direct_articles = self.extract_article_links(html)
        print(f"[DEBUG] Found {len(direct_articles)} article links using BeautifulSoup")
        
        print("Extracting HTML structure for LLM analysis...")
        html_structure = self.extract_html_structure(html)
        
        if debug:
            with open("debug_extracted_html.html", "w", encoding="utf-8") as f:
                f.write(html_structure)
            print(f"[DEBUG] Extracted HTML saved to debug_extracted_html.html ({len(html_structure)} chars)")
        
        # Count potential articles in HTML
        soup = BeautifulSoup(html_structure, 'html.parser')
        news_links = soup.find_all('a', href=lambda x: x and any(kw in x.lower() for kw in ['news', 'press', 'article']))
        print(f"[DEBUG] Found {len(news_links)} potential news/press links in extracted HTML")
        
        print("Analyzing content with LLM to extract detailed information...")
        llm_articles = self.analyze_with_llm(html_structure)
        print(f"[DEBUG] LLM found {len(llm_articles)} articles")
        
        # Combine results - prefer direct extraction (more accurate for filtering)
        # Use direct extraction as primary, LLM as supplement
        articles = []
        direct_links = {art['link'] for art in direct_articles}
        
        # Start with direct extraction results (already filtered to Press Releases only)
        for art in direct_articles:
            articles.append({
                'title': art['title'],
                'date': art['date'],
                'link': art['link'],
                'tags': art.get('tags', ['Press Release'])
            })
        
        # Add any LLM results that weren't found by direct extraction
        # (but only if they look like actual Press Release articles)
        for llm_art in llm_articles:
            llm_link = llm_art.get('link', '')
            # Only add if not already found and is a valid article link
            if llm_link not in direct_links and '/news-press/' in llm_link and '?f[' not in llm_link:
                articles.append(llm_art)
        
        print(f"Final result: {len(articles)} Press Release articles found")
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
            print(f"  Tags:  {', '.join(article['tags']) if article['tags'] else 'N/A'}")
            print("-" * 80)
    
    def save_to_json(self, articles: List[Dict], filename: str = "amdocs_news.json"):
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
        print("  3. Provide it as a command line argument: python amdocs_news_scraper.py your_api_key")
        return 1
    
    try:
        scraper = AmdocsScraper(api_key=api_key)
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

