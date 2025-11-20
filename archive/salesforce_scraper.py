"""
LLM-based scraper for extracting structured data from Salesforce news explorer page.
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


class SalesforceScraper:
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
        self.url = "https://www.salesforce.com/news/news-explorer/"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def fetch_html(self, use_selenium: bool = True) -> str:
        """
        Fetch HTML content from the Salesforce news explorer page.
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
        html_content = None
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
                
                # Check if we have actual content
                articles = driver.find_elements(By.CSS_SELECTOR, "article.content-card")
                links = driver.find_elements(By.CSS_SELECTOR, "a[href*='news'], a[href*='stories']")
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
            
            if len(html) < 10000:
                print(f"[WARNING] Retrieved HTML seems too short ({len(html)} chars). The page might still be loading.")
                print("Trying to wait a bit longer...")
                time.sleep(5)
                html = driver.page_source
                print(f"Retrieved HTML after additional wait: {len(html)} characters")
            
            # Try to find article links to verify we have content
            temp_soup = BeautifulSoup(html, 'html.parser')
            test_links = temp_soup.find_all('article', class_='content-card')
            print(f"[DEBUG] Found {len(test_links)} content-card articles in full HTML")
            
            html_content = html
            return html
        except Exception as e:
            raise Exception(f"Failed to fetch HTML with Selenium: {str(e)}")
        finally:
            if driver:
                print("Closing browser...")
                try:
                    # Try to close gracefully
                    try:
                        driver.quit()
                    except:
                        # If quit fails, try close
                        try:
                            driver.close()
                        except:
                            pass
                    time.sleep(0.5)  # Give it time to fully close
                except Exception:
                    # Ignore cleanup errors (common with undetected_chromedriver)
                    pass
                finally:
                    # Explicitly delete to help garbage collection
                    try:
                        del driver
                    except:
                        pass
                    driver = None
            # Return the HTML if we have it (in case of exception)
            if html_content:
                return html_content
    
    def extract_article_links(self, html: str) -> List[Dict]:
        """
        Extract article links using BeautifulSoup.
        Targets articles with class="content-card".
        
        Args:
            html: Raw HTML content
            
        Returns:
            List of dictionaries with basic article info (link, title, date)
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []
        seen_links = set()
        
        # Find all article elements with class="content-card"
        article_elements = soup.find_all('article', class_='content-card')
        
        print(f"[DEBUG] Found {len(article_elements)} content-card articles")
        
        # Process article elements
        seen_titles = set()  # Also track titles to avoid duplicates
        for idx, article in enumerate(article_elements):
            # Get link from data-clickable-area-link attribute or from title link
            link = None
            link_url = None
            
            # First, try data-clickable-area-link attribute
            if article.get('data-clickable-area-link'):
                link_url = article.get('data-clickable-area-link')
            else:
                # Try to find link in title
                title_link = article.find('a', class_='content-card__title-link')
                if title_link and title_link.get('href'):
                    link_url = title_link.get('href')
            
            if not link_url:
                continue
            
            # Make URL absolute
            if link_url.startswith('/'):
                full_url = f"https://www.salesforce.com{link_url}"
            elif link_url.startswith('http'):
                full_url = link_url
            else:
                continue
            
            # Extract title first to check for duplicates
            title = "N/A"
            title_elem = article.find('h3', class_='content-card__title')
            if title_elem:
                title_link_elem = title_elem.find('a', class_='content-card__title-link')
                if title_link_elem:
                    title = title_link_elem.get_text(strip=True)
                else:
                    title = title_elem.get_text(strip=True)
            
            # If no title found, try alternative methods
            if title == "N/A" or len(title) < 10:
                # Try to find any heading
                for heading in article.find_all(['h1', 'h2', 'h3', 'h4', 'h5']):
                    heading_text = heading.get_text(strip=True)
                    if heading_text and len(heading_text) > 10:
                        title = heading_text
                        break
            
            # Avoid duplicates by both URL and title
            if full_url in seen_links:
                continue
            # Also check if we've seen this title before (normalize for comparison)
            title_normalized = title.lower().strip() if title != "N/A" else ""
            if title_normalized and title_normalized in seen_titles:
                continue
            
            seen_links.add(full_url)
            if title_normalized:
                seen_titles.add(title_normalized)
            
            # Extract date
            date_text = "N/A"
            date_elem = article.find('div', class_='content-card__date')
            if date_elem:
                date_text = date_elem.get_text(strip=True)
            
            # If no date found, try to find date patterns in article text
            if date_text == "N/A":
                article_text = article.get_text()
                date_patterns = [
                    r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}\b',
                    r'\b\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b',
                    r'\b\d{4}-\d{2}-\d{2}\b',
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
        
        # Find all content-card articles
        articles = soup.find_all('article', class_='content-card')
        
        if articles:
            # Extract all article HTML
            articles_html = [str(article) for article in articles]
            content_str = '\n'.join(articles_html)
        else:
            # Fallback: look for main content area
            main_content = soup.find('main')
            if main_content:
                content_str = str(main_content)
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
        prompt = f"""You are analyzing HTML from Salesforce news explorer page (https://www.salesforce.com/news/news-explorer/). Your task is to extract ALL news articles from the page.

CRITICAL INSTRUCTIONS:
1. Extract ALL news articles you can find on the page
2. Each article should be in an <article> element with class="content-card"
3. Each article should become a separate entry
4. Do NOT extract filter links, navigation links, or category links
5. Extract ALL articles you can find (typically 10-50+ on a listing page)

What to look for:
- Article elements with class="content-card"
- Title in <h3 class="content-card__title"> with a link inside (<a class="content-card__title-link">)
- Date in <div class="content-card__date">
- Link in the href attribute of the title link, or in data-clickable-area-link attribute of the article
- Dates in formats like "Nov 06, 2025", "06 Nov 2025", "2025-11-06", etc.

For EACH article you find, extract:
- title: The headline or title from the content-card__title element (required)
- date: Publication date from content-card__date element (format as YYYY-MM-DD if possible, otherwise keep original format, use "N/A" if not found)
- link: Full URL from href attribute or data-clickable-area-link (if relative, prepend https://www.salesforce.com. Use "N/A" only if absolutely no link exists)

EXAMPLES of what to extract:
- Articles with class="content-card" that have titles, dates, and links
- News stories from the Salesforce newsroom

EXAMPLES of what to SKIP:
- Filter links
- Navigation links
- Category/tag links
- Links that don't point to actual articles

Return a JSON array with ALL articles found.

JSON structure:
[
  {{
    "title": "First Article Title",
    "date": "2025-11-06",
    "link": "https://www.salesforce.com/news/stories/article-1"
  }},
  {{
    "title": "Second Article Title",
    "date": "2025-11-05",
    "link": "https://www.salesforce.com/news/stories/article-2"
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
        print("Fetching HTML from Salesforce news explorer page...")
        html = self.fetch_html()
        
        if debug:
            with open("debug_salesforce_full_html.html", "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[DEBUG] Full HTML saved to debug_salesforce_full_html.html ({len(html)} chars)")
        
        # First, try to extract article links directly
        print("Extracting article links directly from HTML...")
        direct_articles = self.extract_article_links(html)
        print(f"[DEBUG] Found {len(direct_articles)} article links using BeautifulSoup")
        
        print("Extracting HTML structure for LLM analysis...")
        html_structure = self.extract_html_structure(html)
        
        if debug:
            with open("debug_salesforce_extracted_html.html", "w", encoding="utf-8") as f:
                f.write(html_structure)
            print(f"[DEBUG] Extracted HTML saved to debug_salesforce_extracted_html.html ({len(html_structure)} chars)")
        
        # Count potential articles in HTML
        soup = BeautifulSoup(html_structure, 'html.parser')
        news_links = soup.find_all('article', class_='content-card')
        print(f"[DEBUG] Found {len(news_links)} content-card articles in extracted HTML")
        
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
            if llm_link not in direct_links and llm_link != "N/A" and '/news/' in llm_link:
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
    
    def save_to_json(self, articles: List[Dict], filename: str = "salesforce_articles.json"):
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
        print("  3. Provide it as a command line argument: python salesforce_scraper.py your_api_key")
        return 1
    
    try:
        scraper = SalesforceScraper(api_key=api_key)
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

