"""
Test downloading from a single Omdia article URL.
"""

import json
from download_omdia_articles import OmdiaArticleDownloader

def test_single_url():
    """Test downloading from a single URL."""
    test_article = {
        "title": "Whatever happened to digital transformation?",
        "link": "https://omdia.tech.informa.com/om138386/whatever-happened-to-digital-transformation",
        "date": "2025-11-03",
        "description": "Test article",
        "assets": []
    }
    
    downloader = OmdiaArticleDownloader(download_dir="omdia_downloads")
    
    print("Testing download for single article...")
    print("Initializing browser...")
    downloader._init_driver()
    
    try:
        result = downloader.download_article(test_article, use_assets_fallback=True)
    finally:
        downloader._close_driver()
    
    if result:
        print("\n[SUCCESS] Download successful!")
    else:
        print("\n[FAILED] Download failed!")
    
    return result

if __name__ == "__main__":
    test_single_url()

