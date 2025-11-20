"""
LLM-based scraper for extracting structured data from Oracle news page.
Extracts: title, date, link
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


class OracleScraper:
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
            options.add_argument('--headless')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            
            driver = uc.Chrome(options=options, version_main=None)
            
            print("Loading page...")
            driver.get(self.url)
            
            # Wait for content to load
            print("Waiting for page content to load...")
            max_wait = 30
            waited = 0
            while waited < max_wait:
                page_source = driver.page_source
                
                # Check if we have actual content - look for rc92w2 (news list)
                news_list = driver.find_elements(By.CSS_SELECTOR, "ul.rc92w2, ul[class*='rc92w2']")
                links = driver.find_elements(By.CSS_SELECTOR, "a[href*='news'], a[href*='announcement']")
                main_content = driver.find_elements(By.TAG_NAME, "main")
                
                if len(news_list) > 0 or len(links) > 5 or len(main_content) > 0 or len(page_source) > 20000:
                    print(f"[OK] Content loaded successfully!")
                    break
                
                time.sleep(2)
                waited += 2
                if waited % 4 == 0:
                    print(f"  Still waiting... ({waited}s)")
            
            # Additional wait for JavaScript to fully render
            time.sleep(4)
            
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
        
        # Find all news items (rc92w3 class)
        news_items = soup.find_all('li', class_=lambda x: x and 'rc92w3' in str(x))
        
        # Also look for the news list container
        news_list = soup.find('ul', class_=lambda x: x and 'rc92w2' in str(x))
        
        print(f"[DEBUG] Found {len(news_items)} news items (rc92w3)")
        
        # Process news items
        for idx, item in enumerate(news_items):
            # Find date in rc92w4 > rc92-dt
            date_text = "N/A"
            date_elem = item.find('div', class_=lambda x: x and 'rc92-dt' in str(x))
            if date_elem:
                date_text = date_elem.get_text(strip=True)
            
            # Find title and link in rc92w5 > h3 > a
            title = "N/A"
            link = "N/A"
            
            rc92w5 = item.find('div', class_=lambda x: x and 'rc92w5' in str(x))
            if rc92w5:
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
                'date': date_text
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
        
        # Try to find the rc92 section (news section)
        news_section = soup.find('section', class_=lambda x: x and 'rc92' in str(x))
        
        if news_section:
            # Extract the news section content
            content_str = str(news_section)
        else:
            # Fallback: look for news-related content
            content_selectors = [
                ('ul', {'class': lambda x: x and 'rc92w2' in str(x)}),
                ('div', {'class': lambda x: x and any(keyword in str(x).lower() for keyword in ['news', 'article', 'listing'])}),
                ('main', {}),
                ('section', {'class': lambda x: x and any(keyword in str(x).lower() for keyword in ['news', 'article'])}),
            ]
            
            main_content = None
            for tag, attrs in content_selectors:
                main_content = soup.find(tag, attrs)
                if main_content:
                    break
            
            if main_content:
                content_str = str(main_content)
            else:
                # Fallback: extract all links and their context
                body = soup.find('body')
                if body:
                    # Get all links with their surrounding context
                    links_html = []
                    for link in body.find_all('a', href=lambda x: x and any(kw in x.lower() for kw in ['news', 'announcement']))[:100]:
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
                    
                    # Look for news/announcement links
                    if any(keyword in href for keyword in ['news', 'announcement']) or \
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
        
        # Limit content size to avoid token limits
        if len(content_str) > 150000:
            content_str = content_str[:150000] + "..."
        
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

CRITICAL INSTRUCTIONS:
1. Extract ALL news articles you can find on the page - be extremely thorough
2. Each news article should become a separate entry
3. Do NOT extract filter links, navigation links, or category links
4. Extract ALL news articles you can find (typically 10-50+ on a listing page)
5. Look for ALL li.rc92w3 elements - don't miss any
6. If articles are in a list, extract EVERY single one

What to look for:
- News items in <li class="rc92w3"> elements
- Date in <div class="rc92-dt"> (format: "Nov 12, 2025", "Oct 28, 2025", etc.)
- Title and link in <div class="rc92w5"> > <h3> > <a href="...">Title</a>
- Links should point to /news/announcement/ paths
- Skip any navigation or filter links

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
            with open("debug_oracle_full_html.html", "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[DEBUG] Full HTML saved to debug_oracle_full_html.html ({len(html)} chars)")
        
        # First, try to extract article links directly
        print("Extracting article links directly from HTML...")
        direct_articles = self.extract_article_links(html)
        print(f"[DEBUG] Found {len(direct_articles)} article links using BeautifulSoup")
        
        print("Extracting HTML structure for LLM analysis...")
        html_structure = self.extract_html_structure(html)
        
        if debug:
            with open("debug_oracle_extracted_html.html", "w", encoding="utf-8") as f:
                f.write(html_structure)
            print(f"[DEBUG] Extracted HTML saved to debug_oracle_extracted_html.html ({len(html_structure)} chars)")
        
        # Count potential articles in HTML
        soup = BeautifulSoup(html_structure, 'html.parser')
        news_links = soup.find_all('a', href=lambda x: x and any(kw in x.lower() for kw in ['news', 'announcement']))
        print(f"[DEBUG] Found {len(news_links)} potential news/announcement links in extracted HTML")
        
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
    
    def save_to_json(self, articles: List[Dict], filename: str = "oracle_articles.json"):
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
        print("  3. Provide it as a command line argument: python oracle_scraper.py your_api_key")
        return 1
    
    try:
        scraper = OracleScraper(api_key=api_key)
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



