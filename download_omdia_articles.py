"""
Script to download PDFs (or other formats) from Omdia article pages.
Reads links from omdia_articles.json and downloads articles from the download dropdown.
"""

import json
import time
import os
import re
from pathlib import Path
from typing import Dict, Optional, List
from contextlib import redirect_stderr
from io import StringIO
import requests
from urllib.parse import urljoin, urlparse
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException


class OmdiaArticleDownloader:
    def __init__(self, download_dir: str = "omdia_downloads"):
        """
        Initialize the downloader.
        
        Args:
            download_dir: Directory to save downloaded files
        """
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(exist_ok=True)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        self.driver = None
    
    def _init_driver(self):
        """Initialize the Selenium driver."""
        if self.driver is None:
            print("Initializing browser...")
            options = uc.ChromeOptions()
            options.add_argument('--start-maximized')
            options.add_argument('--disable-blink-features=AutomationControlled')
            # Allow popups (in case we need them for some edge cases)
            options.add_argument('--disable-popup-blocking')
            # Set download preferences
            prefs = {
                "download.default_directory": str(self.download_dir.absolute()),
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "safebrowsing.enabled": True,
                "profile.default_content_setting_values.popups": 1  # Allow popups
            }
            options.add_experimental_option("prefs", prefs)
            self.driver = uc.Chrome(options=options, version_main=None)
    
    def _close_driver(self):
        """Close the Selenium driver."""
        if self.driver:
            try:
                print("Closing browser...")
                with redirect_stderr(StringIO()):
                    self.driver.quit()
                time.sleep(1)
            except Exception:
                pass
            finally:
                self.driver = None
    
    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename to remove invalid characters."""
        # Remove invalid characters for Windows
        invalid_chars = r'[<>:"/\\|?*]'
        filename = re.sub(invalid_chars, '_', filename)
        # Remove leading/trailing spaces and dots
        filename = filename.strip(' .')
        # Limit length
        if len(filename) > 200:
            filename = filename[:200]
        return filename
    
    def _get_download_url_from_dropdown(self, article_url: str) -> Optional[Dict[str, str]]:
        """
        Visit article page and extract download URL from the download dropdown.
        
        Args:
            article_url: URL of the article page
            
        Returns:
            Dictionary with 'url' and 'format' keys, or None if not found
        """
        try:
            print(f"  Visiting: {article_url}")
            self.driver.get(article_url)
            
            # Wait for page to load
            time.sleep(3)
            
            # Wait for download dropdown to appear
            print("  Waiting for download dropdown...")
            wait = WebDriverWait(self.driver, 15)
            try:
                # Find the download dropdown container - try multiple selectors
                download_dropdown = None
                selectors = [
                    "div.download-dropdown",
                    ".download-dropdown",
                    "[class*='download']",
                    "div[class*='download-dropdown']"
                ]
                for selector in selectors:
                    try:
                        download_dropdown = wait.until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                        print(f"  Found download dropdown using selector: {selector}")
                        break
                    except TimeoutException:
                        continue
                
                if not download_dropdown:
                    # Try waiting a bit longer and check page source
                    time.sleep(3)
                    page_source = self.driver.page_source
                    if 'download-dropdown' in page_source.lower() or 'downloadType' in page_source:
                        print("  [INFO] Download dropdown found in page source, trying to locate...")
                        # Try to find it again
                        try:
                            download_dropdown = self.driver.find_element(By.CSS_SELECTOR, "div.download-dropdown")
                        except NoSuchElementException:
                            # Try to find by ID or name
                            try:
                                download_dropdown = self.driver.find_element(By.ID, "downloadType")
                                # Get parent
                                download_dropdown = download_dropdown.find_element(By.XPATH, "./..")
                            except NoSuchElementException:
                                pass
                
                if not download_dropdown:
                    print("  [WARNING] Download dropdown not found on page")
                    print("  [INFO] This might require login or the article may not have downloads available")
                    # Debug: check if page loaded correctly
                    page_title = self.driver.title
                    print(f"  [DEBUG] Page title: {page_title}")
                    # Check for login prompts
                    if 'login' in page_title.lower() or 'sign in' in page_title.lower():
                        print("  [INFO] Page appears to require login")
                    return None
            except TimeoutException:
                print("  [WARNING] Download dropdown not found on page")
                return None
            
            # The dropdown uses a custom selectivity component that loads options dynamically
            # We need to click on it to open and see available options
            # The actual download URLs are in the data-item-id attributes of the dropdown options
            download_url = None
            selected_format = None
            
            try:
                # Skip the select element - it only has the default option
                # Go straight to clicking the dropdown to see the real options
                try:
                    # Find the clickable selectivity input
                    selectivity_clickable = download_dropdown.find_element(By.CSS_SELECTOR, "div.selectivity-single-select, .selectivity-input, #downloadType")
                    print("  Clicking dropdown to open options...")
                    self.driver.execute_script("arguments[0].click();", selectivity_clickable)
                    time.sleep(2)  # Wait for dropdown menu to appear
                    
                    # Look for dropdown menu items
                    try:
                        # Selectivity dropdowns typically show options in a dropdown menu
                        # Look for options in various possible locations
                        print("  Waiting for dropdown menu to appear...")
                        dropdown_menu = WebDriverWait(self.driver, 5).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, ".selectivity-dropdown, .selectivity-results-container, ul.selectivity-results, [role='listbox']"))
                        )
                        print("  Dropdown menu appeared!")
                        
                        # Find all option elements
                        options = dropdown_menu.find_elements(By.CSS_SELECTOR, "li, .selectivity-result-item, [role='option']")
                        print(f"  Found {len(options)} dropdown options")
                        
                        # Look for PDF option
                        pdf_option_found = None
                        other_options_list = []
                        
                        for opt in options:
                            opt_text = opt.text.strip().lower()
                            opt_data_id = opt.get_attribute('data-item-id') or ''
                            opt_value = opt.get_attribute('value') or opt_text
                            print(f"    Option: {opt.text.strip()}")
                            print(f"      data-item-id: {opt_data_id}")
                            
                            # The download URL is in the data-item-id attribute!
                            # NEVER click - always extract URL from data-item-id to avoid popup blocking
                            if 'pdf' in opt_text or 'pdf' in opt_data_id.lower() or opt_data_id.endswith('.pdf'):
                                pdf_option_found = opt
                                selected_format = 'pdf'
                                # Extract URL from data-item-id - this is the download URL!
                                if opt_data_id and opt_data_id != 'Download' and opt_data_id.strip():
                                    download_url = opt_data_id.strip()
                                    if not download_url.startswith('http'):
                                        download_url = urljoin(article_url, download_url)
                                    print(f"  Found PDF download URL from data-item-id: {download_url}")
                                    # IMPORTANT: Don't click - we have the URL, so return immediately
                                    # This prevents popup blocking issues
                                    break
                                else:
                                    print(f"  [WARNING] PDF option found but data-item-id is empty or 'Download'")
                                    print(f"    data-item-id value: '{opt_data_id}'")
                                    # Still don't click - try to find URL another way
                                    break
                            elif opt_text and opt_text != 'download' and opt_data_id and opt_data_id != 'Download':
                                # Store option with its URL
                                other_options_list.append((opt, opt_data_id))
                        
                        # If no PDF, try first other option
                        if not pdf_option_found and other_options_list:
                            first_opt, first_url = other_options_list[0]
                            opt_text = first_opt.text.strip().lower()
                            if 'word' in opt_text or 'docx' in opt_text or first_url.endswith('.docx'):
                                selected_format = 'docx'
                            elif 'pptx' in opt_text or 'powerpoint' in opt_text or first_url.endswith('.pptx'):
                                selected_format = 'pptx'
                            else:
                                selected_format = 'other'
                            
                            # Use the URL from data-item-id - NEVER click to avoid popup blocking
                            if first_url and first_url != 'Download' and first_url.strip():
                                download_url = first_url.strip()
                                if not download_url.startswith('http'):
                                    download_url = urljoin(article_url, download_url)
                                print(f"  Found alternative format download URL from data-item-id: {download_url} ({selected_format})")
                            else:
                                print(f"  [WARNING] Alternative format option found but data-item-id is empty or 'Download'")
                                print(f"    data-item-id value: '{first_url}'")
                                # Don't click - try to find URL another way
                        
                    except TimeoutException:
                        print("  [WARNING] Dropdown menu did not appear after clicking")
                        print("  This might mean the page needs more time to load or requires login")
                
                except NoSuchElementException as e:
                    print(f"  [WARNING] Could not interact with dropdown: {e}")
            
            except Exception as e:
                print(f"  [WARNING] Error interacting with dropdown: {e}")
            
            # If we already found download_url from data-item-id, return it
            if download_url:
                if not download_url.startswith('http'):
                    download_url = urljoin(article_url, download_url)
                print(f"  Using download URL from dropdown option: {download_url}")
                return {'url': download_url, 'format': selected_format or 'pdf'}
            
            # After selecting an option, wait a moment and look for download URL/button
            # Method 1: Look for download links/buttons in the dropdown or nearby
            try:
                # Look for download button or link (may appear after selection)
                time.sleep(1)  # Give time for UI to update
                download_elements = download_dropdown.find_elements(
                    By.CSS_SELECTOR, 
                    "a[href*='download'], button, a.btn, a.button, a[download], [data-download], "
                    "a[href*='.pdf'], a[href*='.pptx'], a[href*='.docx']"
                )
                
                # Also check parent containers
                if not download_elements:
                    parent = download_dropdown.find_element(By.XPATH, "./..")
                    download_elements = parent.find_elements(
                        By.CSS_SELECTOR,
                        "a[href*='download'], button, a.btn, a.button, a[download], [data-download]"
                    )
                
                for elem in download_elements:
                    href = elem.get_attribute('href')
                    if href and ('download' in href.lower() or href.endswith(('.pdf', '.pptx', '.docx'))):
                        download_url = href
                        break
                    # Check data attributes
                    data_url = elem.get_attribute('data-download-url') or elem.get_attribute('data-href')
                    if data_url:
                        download_url = data_url
                        break
                    # Check onclick
                    onclick = elem.get_attribute('onclick')
                    if onclick:
                        url_match = re.search(r"['\"](https?://[^'\"]+)['\"]", onclick)
                        if url_match:
                            download_url = url_match.group(1)
                            break
            except NoSuchElementException:
                pass
            
            # Method 2: Check page source for download URLs
            if not download_url:
                page_source = self.driver.page_source
                # Look for media URLs (common pattern for Omdia)
                url_patterns = [
                    r'["\']([^"\']*\/media\/[^"\']*\.pdf[^"\']*)["\']',
                    r'["\']([^"\']*\/media\/[^"\']*\.pptx[^"\']*)["\']',
                    r'href=["\']([^"\']*download[^"\']*\.pdf[^"\']*)["\']',
                    r'href=["\']([^"\']*download[^"\']*\.pptx[^"\']*)["\']',
                    r'url\(["\']?([^"\']*\/media\/[^"\']*\.pdf[^"\']*)["\']?\)',
                ]
                for pattern in url_patterns:
                    matches = re.findall(pattern, page_source, re.IGNORECASE)
                    if matches:
                        download_url = matches[0]
                        break
            
            # Method 3: Try to find download URL in network requests or data attributes
            if not download_url:
                try:
                    # Look for any element with download-related data attributes
                    download_elem = self.driver.find_element(
                        By.CSS_SELECTOR,
                        "[data-download-url], [data-pdf-url], [data-file-url]"
                    )
                    download_url = (
                        download_elem.get_attribute('data-download-url') or
                        download_elem.get_attribute('data-pdf-url') or
                        download_elem.get_attribute('data-file-url')
                    )
                except NoSuchElementException:
                    pass
            
            # Method 4: Look for download button that might appear after selection
            if not download_url:
                try:
                    # Look for buttons or links that might trigger download
                    download_buttons = self.driver.find_elements(
                        By.CSS_SELECTOR,
                        "button:contains('Download'), a:contains('Download'), "
                        "[class*='download'], [id*='download'], "
                        "button[type='submit'], form button"
                    )
                    for btn in download_buttons:
                        btn_text = btn.text.lower()
                        if 'download' in btn_text or btn.get_attribute('type') == 'submit':
                            # Try to get href or onclick
                            href = btn.get_attribute('href')
                            if href:
                                download_url = href
                                break
                            # Check if clicking triggers download (we'll handle this separately)
                            # For now, just note that we found a button
                except Exception:
                    pass
            
            if download_url:
                if not download_url.startswith('http'):
                    download_url = urljoin(article_url, download_url)
                print(f"  Found download URL: {download_url}")
                return {'url': download_url, 'format': selected_format or 'pdf'}
            else:
                print("  [WARNING] Could not extract download URL from dropdown")
                return None
        
        except Exception as e:
            print(f"  [ERROR] Error extracting download URL: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _get_download_url_from_assets(self, article: Dict) -> Optional[Dict[str, str]]:
        """
        Try to get download URL from article assets if available in JSON.
        
        Args:
            article: Article dictionary from JSON
            
        Returns:
            Dictionary with 'url' and 'format' keys, or None if not found
        """
        assets = article.get('assets', [])
        if not assets:
            return None
        
        # Prefer PDF
        for asset in assets:
            if asset.get('extension', '').lower() == 'pdf':
                return {
                    'url': asset.get('url'),
                    'format': 'pdf'
                }
        
        # Otherwise, return first available asset
        if assets:
            first_asset = assets[0]
            return {
                'url': first_asset.get('url'),
                'format': first_asset.get('extension', 'other').lower()
            }
        
        return None
    
    def download_file(self, url: str, filename: str) -> bool:
        """
        Download a file from URL.
        
        Args:
            url: URL to download from
            filename: Local filename to save as
            
        Returns:
            True if successful, False otherwise
        """
        try:
            print(f"  Downloading: {url}")
            response = requests.get(url, headers=self.headers, stream=True, timeout=60)
            response.raise_for_status()
            
            filepath = self.download_dir / filename
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            file_size = filepath.stat().st_size
            print(f"  [OK] Downloaded: {filename} ({file_size:,} bytes)")
            return True
        except Exception as e:
            print(f"  [ERROR] Download failed: {e}")
            return False
    
    def download_article(self, article: Dict, use_assets_fallback: bool = True) -> bool:
        """
        Download an article PDF/other format.
        
        Args:
            article: Article dictionary with 'link', 'title', etc.
            use_assets_fallback: If True, try using assets from JSON if dropdown fails
            
        Returns:
            True if download successful, False otherwise
        """
        title = article.get('title', 'Unknown')
        link = article.get('link', '')
        
        if not link:
            print(f"[SKIP] No link for article: {title}")
            return False
        
        print(f"\nProcessing: {title}")
        
        # Try to get download URL from dropdown first
        download_info = None
        if self.driver:
            try:
                download_info = self._get_download_url_from_dropdown(link)
            except Exception as e:
                print(f"  [ERROR] Exception in _get_download_url_from_dropdown: {e}")
                import traceback
                traceback.print_exc()
                download_info = None
        
        # Fallback to assets from JSON if available
        if not download_info and use_assets_fallback:
            download_info = self._get_download_url_from_assets(article)
            if download_info:
                print("  Using download URL from article assets")
        
        if not download_info or not download_info.get('url'):
            print(f"  [ERROR] Could not find download URL for: {title}")
            return False
        
        download_url = download_info['url']
        file_format = download_info.get('format', 'pdf')
        
        # Generate filename
        safe_title = self._sanitize_filename(title)
        extension = file_format if file_format != 'other' else 'pdf'
        filename = f"{safe_title}.{extension}"
        
        # Download the file
        return self.download_file(download_url, filename)
    
    def download_articles(self, articles: List[Dict], limit: Optional[int] = None, use_assets_fallback: bool = True) -> Dict[str, int]:
        """
        Download articles from a list.
        
        Args:
            articles: List of article dictionaries
            limit: Maximum number of articles to download (None for all)
            use_assets_fallback: If True, use assets from JSON if dropdown fails
            
        Returns:
            Dictionary with 'success' and 'failed' counts
        """
        if limit:
            articles = articles[:limit]
        
        results = {'success': 0, 'failed': 0}
        
        try:
            self._init_driver()
            
            for idx, article in enumerate(articles, 1):
                print(f"\n[{idx}/{len(articles)}]")
                if self.download_article(article, use_assets_fallback=use_assets_fallback):
                    results['success'] += 1
                else:
                    results['failed'] += 1
                
                # Be respectful - wait between downloads
                if idx < len(articles):
                    time.sleep(2)
        
        finally:
            self._close_driver()
        
        return results


def main():
    """Main entry point."""
    import sys
    
    # Parse arguments
    limit = None
    json_file = "omdia_articles.json"
    download_dir = "omdia_downloads"
    no_assets_fallback = False
    
    for arg in sys.argv[1:]:
        if arg.startswith("--limit="):
            try:
                limit = int(arg.split("=")[1])
            except (ValueError, IndexError):
                pass
        elif arg.startswith("--json="):
            json_file = arg.split("=")[1]
        elif arg.startswith("--dir="):
            download_dir = arg.split("=")[1]
        elif arg == "--no-assets-fallback":
            no_assets_fallback = True
    
    # Load articles from JSON
    script_dir = Path(__file__).parent
    json_path = script_dir / json_file
    
    if not json_path.exists():
        print(f"Error: JSON file not found: {json_path}")
        return 1
    
    print(f"Loading articles from: {json_path}")
    with open(json_path, 'r', encoding='utf-8') as f:
        articles = json.load(f)
    
    print(f"Loaded {len(articles)} articles")
    if limit:
        print(f"Limiting to first {limit} articles for testing")
    
    # Initialize downloader
    downloader = OmdiaArticleDownloader(download_dir=download_dir)
    
    # Download articles
    print(f"\n{'='*80}")
    print("Starting downloads...")
    print(f"{'='*80}\n")
    
    results = downloader.download_articles(
        articles,
        limit=limit,
        use_assets_fallback=not no_assets_fallback
    )
    
    # Print summary
    print(f"\n{'='*80}")
    print("Download Summary:")
    print(f"{'='*80}")
    print(f"Success: {results['success']}")
    print(f"Failed:  {results['failed']}")
    print(f"Total:   {results['success'] + results['failed']}")
    print(f"\nFiles saved to: {downloader.download_dir.absolute()}")
    
    return 0 if results['failed'] == 0 else 1


if __name__ == "__main__":
    exit(main())

