"""
Utility functions for Selenium-based web scraping with error handling,
access denied detection, non-headless fallback, and retry logic.
"""

import time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from typing import Optional, Callable, List
import os
import shutil


def detect_access_denied(html: str) -> bool:
    """
    Detect if the HTML content indicates access denied or blocking.
    
    Args:
        html: HTML content to check
        
    Returns:
        True if access denied indicators are found
    """
    if not html:
        return False
    
    html_lower = html.lower()
    
    # Common access denied/blocking indicators
    error_indicators = [
        'access denied',
        'access forbidden',
        'you don\'t have permission',
        'you do not have permission',
        '403 forbidden',
        'forbidden',
        'blocked',
        'errors.edgesuite.net',  # Akamai CDN error
        'reference #',  # Akamai error reference
        'cloudflare',  # Cloudflare blocking page
        'checking your browser',  # Cloudflare challenge
        'ddos protection',  # DDoS protection page
        'captcha',  # CAPTCHA page
        'bot detection',
        'automated access',
        'please verify you are human',
    ]
    
    return any(indicator in html_lower for indicator in error_indicators)


def find_chrome_executable() -> Optional[str]:
    """
    Find Chrome executable path on Windows.
    
    Returns:
        Path to Chrome executable or None if not found
    """
    # Common Chrome installation paths on Windows
    possible_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    # Try to find it using shutil
    return shutil.which('chrome') or shutil.which('chromium') or shutil.which('google-chrome')


def create_chrome_options(headless: bool = True, additional_args: List[str] = None) -> uc.ChromeOptions:
    """
    Create Chrome options with common anti-detection settings.
    
    Args:
        headless: Whether to run in headless mode
        additional_args: Additional Chrome arguments to add
        
    Returns:
        Configured ChromeOptions object
    """
    options = uc.ChromeOptions()
    
    if headless:
        options.add_argument('--headless=new')  # Use new headless mode
    else:
        # Use non-headless mode for better stealth
        options.add_argument('--start-maximized')
        options.add_argument('--window-size=1920,1080')
    
    # Anti-detection options
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    
    # Force HTTP/1.1 to avoid HTTP/2 protocol errors
    options.add_argument('--disable-http2')
    options.add_argument('--disable-quic')
    
    # Additional options for better compatibility
    options.add_argument('--disable-web-security')
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--ignore-ssl-errors')
    options.add_argument('--allow-running-insecure-content')
    
    # Set user agent
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    # Add any additional arguments
    if additional_args:
        for arg in additional_args:
            options.add_argument(arg)
    
    # Set Chrome binary location if found
    chrome_path = find_chrome_executable()
    if chrome_path:
        options.binary_location = chrome_path
    
    return options


def fetch_with_selenium_retry(
    url: str,
    max_retries: int = 3,
    initial_headless: bool = True,
    wait_for_content: Optional[Callable] = None,
    wait_timeout: int = 30,
    additional_wait: int = 3,
    logger=None
) -> str:
    """
    Fetch HTML using Selenium with retry logic, access denied detection,
    and automatic fallback to non-headless mode.
    
    Args:
        url: URL to fetch
        max_retries: Maximum number of retry attempts
        initial_headless: Whether to start with headless mode
        wait_for_content: Optional function to wait for specific content (takes driver, returns bool)
        wait_timeout: Maximum time to wait for content (seconds)
        additional_wait: Additional wait time after content loads (seconds)
        logger: Optional logger object for logging
        
    Returns:
        HTML content as string
        
    Raises:
        Exception: If all retry attempts fail
    """
    log = logger.info if logger else print
    log_error = logger.error if logger else print
    
    driver = None
    last_exception = None
    
    # Try headless first, then non-headless
    headless_modes = [initial_headless, False] if initial_headless else [False]
    
    for attempt in range(max_retries):
        for use_headless in headless_modes:
            try:
                if attempt > 0 or (use_headless != initial_headless):
                    log(f"Retry attempt {attempt + 1}/{max_retries} (headless={use_headless})...")
                    time.sleep(2 ** attempt)  # Exponential backoff
                
                log(f"Initializing browser (headless={use_headless})...")
                options = create_chrome_options(headless=use_headless)
                driver = uc.Chrome(options=options, version_main=None)
                
                log(f"Loading page: {url}")
                driver.get(url)
                
                # Wait for content to load
                log("Waiting for page content to load...")
                waited = 0
                content_loaded = False
                
                while waited < wait_timeout:
                    page_source = driver.page_source
                    
                    # Check for access denied
                    if detect_access_denied(page_source):
                        log_error(f"[ERROR] Access denied detected in page source")
                        if driver:
                            try:
                                driver.quit()
                            except:
                                pass
                            driver = None
                        
                        # If we're in headless mode, try non-headless next
                        if use_headless:
                            log("[RETRY] Retrying with non-headless browser (better stealth)...")
                            break  # Break inner loop to try non-headless
                        else:
                            # Already tried non-headless, raise exception
                            raise Exception("Access denied by server even with non-headless browser")
                    
                    # Check if content is loaded (using custom function or default check)
                    if wait_for_content:
                        content_loaded = wait_for_content(driver)
                    else:
                        # Default: check if page has substantial content
                        content_loaded = len(page_source) > 20000
                    
                    if content_loaded:
                        log("[OK] Content loaded successfully!")
                        break
                    
                    time.sleep(2)
                    waited += 2
                    if waited % 4 == 0:
                        log(f"  Still waiting... ({waited}s)")
                
                # Additional wait for JavaScript to fully render
                time.sleep(additional_wait)
                
                html = driver.page_source
                log(f"Retrieved HTML: {len(html)} characters")
                
                # Final check for access denied
                if detect_access_denied(html):
                    log_error(f"[ERROR] Access denied detected in final HTML")
                    if driver:
                        try:
                            driver.quit()
                        except:
                            pass
                        driver = None
                    
                    # If we're in headless mode and got access denied, try non-headless
                    if use_headless and detect_access_denied(html):
                        log("[RETRY] Retrying with non-headless browser (better stealth)...")
                        continue  # Continue to next iteration (non-headless)
                    
                    # If we still have access denied after non-headless, raise exception
                    if detect_access_denied(html):
                        raise Exception("Access denied by server even with non-headless browser")
                
                # Success - return HTML
                if driver:
                    try:
                        driver.quit()
                    except:
                        pass
                
                return html
                
            except Exception as e:
                last_exception = e
                log_error(f"Error during fetch attempt: {str(e)}")
                if driver:
                    try:
                        driver.quit()
                    except:
                        pass
                    driver = None
                
                # If this was the last headless mode and we have more retries, continue
                if use_headless == headless_modes[-1] and attempt < max_retries - 1:
                    continue
                elif attempt < max_retries - 1:
                    # Wait before next retry
                    wait_time = 2 ** attempt
                    log(f"Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
    
    # All retries failed
    raise Exception(f"Failed to fetch HTML after {max_retries} attempts: {str(last_exception)}")


