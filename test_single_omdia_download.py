"""
Test script to download from a single Omdia article URL.
"""

import json
import time
from pathlib import Path
from contextlib import redirect_stderr
from io import StringIO
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup
import requests
from urllib.parse import urljoin
import re


def test_download_dropdown(url: str):
    """Test finding and interacting with download dropdown on a single page."""
    driver = None
    try:
        print(f"Testing URL: {url}")
        print("Initializing browser...")
        
        options = uc.ChromeOptions()
        options.add_argument('--start-maximized')
        options.add_argument('--disable-blink-features=AutomationControlled')
        
        driver = uc.Chrome(options=options, version_main=None)
        
        print("Loading page...")
        driver.get(url)
        time.sleep(5)
        
        print("\nPage loaded. Analyzing page structure...")
        print(f"Page title: {driver.title}")
        
        # Check page source for download-related elements
        page_source = driver.page_source
        soup = BeautifulSoup(page_source, 'html.parser')
        
        # Look for download dropdown
        print("\n=== Searching for download dropdown ===")
        download_dropdowns = soup.find_all('div', class_=lambda x: x and 'download' in str(x).lower())
        print(f"Found {len(download_dropdowns)} divs with 'download' in class")
        
        for idx, dd in enumerate(download_dropdowns):
            print(f"\n  Dropdown {idx+1}:")
            print(f"    Classes: {dd.get('class')}")
            print(f"    HTML snippet: {str(dd)[:200]}...")
        
        # Look for select elements with downloadType
        print("\n=== Searching for select[name='downloadType'] ===")
        selects = soup.find_all('select', {'name': 'downloadType'})
        print(f"Found {len(selects)} select elements with name='downloadType'")
        
        for idx, sel in enumerate(selects):
            print(f"\n  Select {idx+1}:")
            options = sel.find_all('option')
            print(f"    Options: {len(options)}")
            for opt in options:
                print(f"      - {opt.get('value')}: {opt.text.strip()}")
        
        # Try to find using Selenium
        print("\n=== Trying to find with Selenium ===")
        wait = WebDriverWait(driver, 10)
        
        try:
            # Try multiple selectors
            selectors = [
                "div.download-dropdown",
                ".download-dropdown",
                "select[name='downloadType']",
                "#downloadType",
                "[class*='download']",
            ]
            
            for selector in selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        print(f"  Found {len(elements)} element(s) with selector: {selector}")
                        for elem in elements:
                            print(f"    Tag: {elem.tag_name}, Text: {elem.text[:100]}")
                            if elem.tag_name == 'select':
                                select_obj = Select(elem)
                                options = select_obj.options
                                print(f"    Options: {len(options)}")
                                for opt in options:
                                    print(f"      - {opt.get_attribute('value')}: {opt.text}")
                    else:
                        print(f"  No elements found with selector: {selector}")
                except Exception as e:
                    print(f"  Error with selector {selector}: {e}")
        
        except Exception as e:
            print(f"Error in Selenium search: {e}")
        
        # Look for download links/buttons
        print("\n=== Searching for download links/buttons ===")
        download_links = soup.find_all('a', href=lambda x: x and 'download' in str(x).lower())
        print(f"Found {len(download_links)} links with 'download' in href")
        
        for idx, link in enumerate(download_links[:5]):  # Show first 5
            print(f"  Link {idx+1}: {link.get('href')} - {link.text.strip()[:50]}")
        
        # Look for media URLs in page source
        print("\n=== Searching for media URLs in page source ===")
        media_patterns = [
            r'["\']([^"\']*\/media\/[^"\']*\.pdf[^"\']*)["\']',
            r'["\']([^"\']*\/media\/[^"\']*\.pptx[^"\']*)["\']',
            r'["\']([^"\']*\/media\/[^"\']*\.docx[^"\']*)["\']',
        ]
        
        for pattern in media_patterns:
            matches = re.findall(pattern, page_source, re.IGNORECASE)
            if matches:
                print(f"  Found {len(matches)} matches for pattern: {pattern[:50]}...")
                for match in matches[:3]:  # Show first 3
                    print(f"    - {match}")
        
        # Save page source for inspection
        debug_dir = Path("debug")
        debug_dir.mkdir(exist_ok=True)
        debug_file = debug_dir / "test_omdia_page.html"
        with open(debug_file, 'w', encoding='utf-8') as f:
            f.write(page_source)
        print(f"\nPage source saved to: {debug_file}")
        
        print("\n=== Test complete ===")
        print("Keep browser open for manual inspection? (will close in 10 seconds)")
        time.sleep(10)
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if driver:
            try:
                print("Closing browser...")
                with redirect_stderr(StringIO()):
                    driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    test_url = "https://omdia.tech.informa.com/om138386/whatever-happened-to-digital-transformation"
    test_download_dropdown(test_url)

