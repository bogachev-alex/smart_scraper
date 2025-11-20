"""
Interactive test to see what happens when we click the dropdown and select an option.
"""

import time
from contextlib import redirect_stderr
from io import StringIO
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

def test_interactive_download():
    """Test clicking dropdown and seeing what happens."""
    driver = None
    try:
        url = "https://omdia.tech.informa.com/om138386/whatever-happened-to-digital-transformation"
        print(f"Testing URL: {url}")
        print("Initializing browser...")
        
        options = uc.ChromeOptions()
        options.add_argument('--start-maximized')
        options.add_argument('--disable-blink-features=AutomationControlled')
        # Allow popups by default
        options.add_argument('--disable-popup-blocking')
        
        # Enable performance logging to capture network requests
        options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
        
        # Set preferences to allow popups
        prefs = {
            "profile.default_content_setting_values.popups": 1  # Allow popups
        }
        options.add_experimental_option("prefs", prefs)
        
        driver = uc.Chrome(options=options, version_main=None)
        
        print("Loading page...")
        driver.get(url)
        time.sleep(5)
        
        print("\n=== Finding dropdown ===")
        wait = WebDriverWait(driver, 15)
        download_dropdown = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.download-dropdown"))
        )
        print("Found download dropdown")
        
        # Find the clickable element
        print("\n=== Clicking dropdown ===")
        selectivity_input = download_dropdown.find_element(By.CSS_SELECTOR, "#downloadType, div.selectivity-input")
        print("Clicking to open dropdown...")
        driver.execute_script("arguments[0].click();", selectivity_input)
        time.sleep(3)  # Wait for dropdown to open
        
        # Take a screenshot to see what's visible
        driver.save_screenshot("debug/dropdown_opened.png")
        print("Screenshot saved: debug/dropdown_opened.png")
        
        # Look for dropdown menu
        print("\n=== Looking for dropdown options ===")
        try:
            # Try multiple selectors for the dropdown menu
            selectors = [
                ".selectivity-dropdown",
                ".selectivity-results-container",
                "ul.selectivity-results",
                "[role='listbox']",
                ".selectivity-dropdown-menu",
                "div[class*='selectivity'][class*='dropdown']"
            ]
            
            dropdown_menu = None
            for selector in selectors:
                try:
                    dropdown_menu = WebDriverWait(driver, 3).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    print(f"Found dropdown menu with selector: {selector}")
                    break
                except TimeoutException:
                    continue
            
            if dropdown_menu:
                # Get all options
                options_list = dropdown_menu.find_elements(By.CSS_SELECTOR, "li, .selectivity-result-item, [role='option'], a")
                print(f"Found {len(options_list)} options")
                
                for idx, opt in enumerate(options_list):
                    print(f"  Option {idx+1}: '{opt.text.strip()}'")
                    print(f"    - Tag: {opt.tag_name}")
                    print(f"    - Classes: {opt.get_attribute('class')}")
                    print(f"    - data-item-id: {opt.get_attribute('data-item-id')}")
                    print(f"    - href: {opt.get_attribute('href')}")
                
                # Try to find PDF option
                pdf_option = None
                for opt in options_list:
                    opt_text = opt.text.strip().lower()
                    if 'pdf' in opt_text:
                        pdf_option = opt
                        print(f"\n=== Clicking PDF option ===")
                        print(f"Found PDF option: '{opt.text.strip()}'")
                        driver.execute_script("arguments[0].click();", opt)
                        time.sleep(3)
                        break
                
                if not pdf_option:
                    print("\n[WARNING] No PDF option found, trying first available option")
                    if options_list:
                        first_opt = options_list[0]
                        print(f"Clicking first option: '{first_opt.text.strip()}'")
                        driver.execute_script("arguments[0].click();", first_opt)
                        time.sleep(3)
            else:
                print("[WARNING] Dropdown menu not found after clicking")
                print("Page source snippet around dropdown:")
                page_source = driver.page_source
                dropdown_idx = page_source.find('download-dropdown')
                if dropdown_idx >= 0:
                    print(page_source[dropdown_idx:dropdown_idx+500])
        
        except Exception as e:
            print(f"[ERROR] Error finding options: {e}")
            import traceback
            traceback.print_exc()
        
        # After clicking, check for download URLs
        print("\n=== Checking for download URLs after selection ===")
        time.sleep(2)
        
        # Check page source for download links
        page_source = driver.page_source
        
        # Look for download links
        download_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='download'], a[href*='.pdf'], a[href*='.pptx']")
        print(f"Found {len(download_links)} download links")
        for link in download_links:
            print(f"  - {link.get_attribute('href')} (text: {link.text.strip()})")
        
        # Check network logs for download requests
        print("\n=== Checking network logs ===")
        logs = driver.get_log('performance')
        pdf_requests = []
        for log in logs:
            message = log.get('message', '')
            if 'pdf' in message.lower() or 'download' in message.lower():
                pdf_requests.append(message)
        
        if pdf_requests:
            print(f"Found {len(pdf_requests)} relevant network requests")
            for req in pdf_requests[:5]:  # Show first 5
                print(f"  - {req[:200]}...")
        else:
            print("No PDF/download requests found in network logs")
        
        # Look for media URLs in page source
        import re
        media_patterns = [
            r'href=["\']([^"\']*\/media\/[^"\']*\.pdf[^"\']*)["\']',
            r'["\']([^"\']*\/media\/[^"\']*\/om138386[^"\']*\.pdf[^"\']*)["\']',
        ]
        for pattern in media_patterns:
            matches = re.findall(pattern, page_source, re.IGNORECASE)
            if matches:
                print(f"\nFound media URLs with pattern: {pattern[:50]}...")
                for match in matches[:3]:
                    print(f"  - {match}")
        
        print("\n=== Keeping browser open for 30 seconds for manual inspection ===")
        print("You can manually click the dropdown and see what happens")
        time.sleep(30)
        
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
    test_interactive_download()

