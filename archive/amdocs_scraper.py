"""
LLM-based scraper for extracting structured data from Amdocs insights blog page.
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
        self.url = "https://www.amdocs.com/insights"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def fetch_html(self, use_selenium: bool = True) -> str:
        """
        Fetch HTML content from the Amdocs insights page.
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
                    # Check if we have actual content - look for article elements
                    articles = driver.find_elements(By.CSS_SELECTOR, "article[about]")
                    links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/insights/']")
                    main_content = driver.find_elements(By.CSS_SELECTOR, "[class*='views-infinite-scroll-content-wrapper']")
                    
                    if len(articles) > 0 or len(links) > 5 or len(main_content) > 0 or len(page_source) > 20000:
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
            test_articles = temp_soup.find_all('article', about=True)
            print(f"[DEBUG] Found {len(test_articles)} article elements in full HTML")
            
            return html
        except Exception as e:
            raise Exception(f"Failed to fetch HTML with Selenium: {str(e)}")
        finally:
            if driver:
                try:
                    print("Closing browser...")
                    driver.quit()
                except (OSError, Exception):
                    # Ignore cleanup errors (common on Windows with undetected_chromedriver)
                    pass
    
    def extract_article_links(self, html: str) -> List[Dict]:
        """
        Extract article links using BeautifulSoup.
        Targets article elements with about attributes.
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with basic article info (link, title, date)
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Find all article elements with about attributes
        article_elements = soup.find_all('article', about=True)
        
        print(f"[DEBUG] Found {len(article_elements)} article elements")
        
        # Process each article element
        for idx, article in enumerate(article_elements):
            # Extract link from about attribute
            about_attr = article.get('about', '')
            if not about_attr:
                continue
            
            # Make URL absolute
            if about_attr.startswith('/'):
                full_url = f"https://www.amdocs.com{about_attr}"
            elif about_attr.startswith('http'):
                full_url = about_attr
            else:
                full_url = f"https://www.amdocs.com/{about_attr.lstrip('/')}"
            
            # Avoid duplicates
            if full_url in seen_links:
                continue
            seen_links.add(full_url)
            
            # Extract title from h5 element with specific class
            title = "N/A"
            title_elem = article.find('h5', class_=lambda x: x and 'coh-style-title' in str(x))
            if title_elem:
                title = title_elem.get_text(strip=True)
            
            # If no title found, try alternative methods
            if title == "N/A" or len(title) < 10:
                # Try to find any heading
                for heading in article.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                    heading_text = heading.get_text(strip=True)
                    if heading_text and len(heading_text) > 10:
                        title = heading_text
                        break
            
            # If still no title, try link text
            if title == "N/A" or len(title) < 10:
                link_elem = article.find('a', href=lambda x: x and '/insights/' in str(x))
                if link_elem:
                    link_text = link_elem.get_text(strip=True)
                    if link_text and len(link_text) > 10:
                        title = link_text
                    else:
                        title_attr = link_elem.get('title', '')
                        if title_attr and len(title_attr) > 10:
                            title = title_attr
            
            # Extract date from paragraph with specific class
            # Validate that the extracted text is actually a date (not an author name)
            date_text = "N/A"
            date_elem = article.find('p', class_=lambda x: x and 'coh-style-amd-author' in str(x) and 'coh-ce-cpt_author-b7b53071' in str(x))
            if date_elem:
                potential_date = date_elem.get_text(strip=True)
                # Validate that it contains a date pattern (not just author name)
                date_patterns = [
                    r'\b\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b',
                    r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b',
                    r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',
                    r'\b\d{4}-\d{2}-\d{2}\b',
                    r'\b\d{1,2}/\d{1,2}/\d{4}\b',
                ]
                for pattern in date_patterns:
                    match = re.search(pattern, potential_date, re.IGNORECASE)
                    if match:
                        date_text = match.group(0)
                        break
                # If no date pattern found, it's likely an author name, so keep as "N/A"
            
            # If no date found, try to find date patterns in article text
            if date_text == "N/A":
                article_text = article.get_text()
                date_patterns = [
                    r'\b\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b',
                    r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b',
                    r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',
                    r'\b\d{4}-\d{2}-\d{2}\b',
                    r'\b\d{1,2}/\d{1,2}/\d{4}\b',
                ]
                for pattern in date_patterns:
                    match = re.search(pattern, article_text, re.IGNORECASE)
                    if match:
                        date_text = match.group(0)
                        break
            
            articles.append({
                'link': full_url,
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
        
        # Find the views-infinite-scroll-content-wrapper container
        content_wrapper = soup.find('div', class_=lambda x: x and 'views-infinite-scroll-content-wrapper' in str(x))
        
        if content_wrapper:
            # Extract all article elements HTML
            article_elements = content_wrapper.find_all('article', about=True)
            articles_html = [str(article) for article in article_elements]
            content_str = '\n'.join(articles_html)
        else:
            # Fallback: look for the main container
            main_container = soup.find('div', class_=lambda x: x and 'coh-style-view-pagination' in str(x))
            if main_container:
                # Find all article elements within the container
                article_elements = main_container.find_all('article', about=True)
                if article_elements:
                    articles_html = [str(article) for article in article_elements]
                    content_str = '\n'.join(articles_html)
                else:
                    content_str = str(main_container)
            else:
                # Fallback: find all article elements directly
                article_elements = soup.find_all('article', about=True)
                if article_elements:
                    articles_html = [str(article) for article in article_elements]
                    content_str = '\n'.join(articles_html)
                else:
                    # Last resort: get body
                    body = soup.find('body')
                    content_str = str(body) if body else html
        
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
        prompt = f"""You are analyzing HTML from Amdocs insights blog page (https://www.amdocs.com/insights). Your task is to extract ALL blog articles from the page.

CRITICAL INSTRUCTIONS:
1. Extract ALL blog articles you can find on the page - be extremely thorough
2. Each article should be in an <article> element with an "about" attribute containing the link
3. Each article should become a separate entry
4. Do NOT extract filter links, navigation links, or category links
5. Extract ALL articles you can find (typically 10-50+ on a listing page)
6. Look for ALL article elements - don't miss any
7. If articles are in a list or grid, extract EVERY single one

What to look for:
- Article elements with <article about="/insights/..."> containing the link path
- Titles in <h5> elements with class containing "coh-style-title" within the article
- Dates in <p> elements with class containing "coh-style-amd-author" and "coh-ce-cpt_author-b7b53071" within the article
- Dates in formats like "17 Nov 2025", "Nov 17, 2025", "2025-11-17", etc.
- Links can be extracted from the "about" attribute of the <article> tag, or from <a> href within the article

For EACH article you find, extract:
- title: The headline or title from h5 element with class containing "coh-style-title" (required - use link text if no explicit title)
- date: Publication date from p element with class containing "coh-style-amd-author" (format as YYYY-MM-DD if possible, otherwise keep original format like "17 Nov 2025", use "N/A" if not found)
- link: Full URL from article "about" attribute or from a href (if relative, prepend https://www.amdocs.com. Use "N/A" only if absolutely no link exists)

EXAMPLES of what to extract:
- Articles with dates, titles, and links from the insights page
- Blog posts, articles, whitepapers, case studies, videos, etc. from the insights listing

EXAMPLES of what to SKIP:
- Filter links
- Navigation links
- Category/tag links
- Links that don't point to actual articles
- "Load more" buttons

Return a JSON array with ALL articles found.

JSON structure:
[
  {{
    "title": "First Article Title",
    "date": "2025-11-17",
    "link": "https://www.amdocs.com/insights/article/article-1"
  }},
  {{
    "title": "Second Article Title",
    "date": "2025-11-14",
    "link": "https://www.amdocs.com/insights/video/video-1"
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
                    {"role": "system", "content": "You are a web scraping expert that extracts ALL articles from HTML. You MUST find every single article on the page. Return only valid JSON arrays with all articles found. Be extremely thorough - typical blog listing pages have 10-50+ articles."},
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
        print("Fetching HTML from Amdocs insights page...")
        html = self.fetch_html()
        
        if debug:
            with open("debug_amdocs_full_html.html", "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[DEBUG] Full HTML saved to debug_amdocs_full_html.html ({len(html)} chars)")
        
        # First, try to extract article links directly
        print("Extracting article links directly from HTML...")
        direct_articles = self.extract_article_links(html)
        print(f"[DEBUG] Found {len(direct_articles)} article links using BeautifulSoup")
        
        print("Extracting HTML structure for LLM analysis...")
        html_structure = self.extract_html_structure(html)
        
        if debug:
            with open("debug_amdocs_extracted_html.html", "w", encoding="utf-8") as f:
                f.write(html_structure)
            print(f"[DEBUG] Extracted HTML saved to debug_amdocs_extracted_html.html ({len(html_structure)} chars)")
        
        # Count potential articles in HTML
        soup = BeautifulSoup(html_structure, 'html.parser')
        article_elements = soup.find_all('article', about=True)
        print(f"[DEBUG] Found {len(article_elements)} article elements in extracted HTML")
        
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
        for llm_art in llm_articles:
            llm_link = llm_art.get('link', '')
            # Only add if not already found and is a valid article link
            if llm_link not in direct_links and llm_link != "N/A" and '/insights/' in llm_link:
                articles.append(llm_art)
        
        print(f"Final result: {len(articles)} articles found")
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
    
    def save_to_json(self, articles: List[Dict], filename: str = "amdocs_blog_articles.json"):
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
        print("  3. Provide it as a command line argument: python amdocs_scraper.py your_api_key")
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

