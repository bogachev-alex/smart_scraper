"""
Pipeline script to:
1. Run all scrapers sequentially
2. Combine all JSON files into a unified file
3. Enhance articles with main ideas and tags
4. Save enhanced data to database
"""

import os
import sys
import subprocess
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
log_filename = f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# File handler - logs everything including DEBUG
file_handler = logging.FileHandler(log_filename, encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)

# Console handler - logs INFO and above (less verbose)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

# Add handlers
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Import scrapers and utilities
from combine_scraped_data import combine_scraped_data
from article_enhancer import ArticleEnhancer


class ScrapingPipeline:
    """Pipeline to run all scrapers and enhance articles"""
    
    def __init__(self, api_key: str = None, api_keys: List[str] = None):
        """
        Initialize the pipeline.
        
        Args:
            api_key: Single OpenAI API key (for backward compatibility). If not provided, will try to get from environment.
            api_keys: List of OpenAI API keys for parallel processing. If provided, will use these instead of api_key.
        """
        # Support multiple API keys for parallel processing
        if api_keys:
            self.api_keys = api_keys
            if not all(api_keys):
                raise ValueError("All API keys in api_keys list must be non-empty")
            # Use first key for scrapers (they run sequentially)
            self.api_key = api_keys[0]
        else:
            # Single API key mode (backward compatible)
            single_key = api_key or os.getenv("OPENAI_API_KEY")
            if not single_key:
                raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY in .env file or provide it as argument.")
            self.api_key = single_key
            self.api_keys = [single_key]
        
        # List of all scrapers to run
        # Scrapers that don't need API key
        self.scrapers_no_api = ['ibm_news_scraper.py']
        
        # All scrapers
        self.scrapers = [
            'ibm_news_scraper.py',
            'cisco_scraper.py',
            'hpe_news_scraper.py',
            'oracle_news_scraper.py',
            'salesforce_news_scraper.py',
            'servicenow_news_scraper.py',
            'ericsson_news_scraper.py',
            'nokia_news_scraper.py'
        ]
        
        self.project_root = Path(__file__).parent
    
    def run_scraper(self, scraper_file: str, max_retries: int = 3) -> bool:
        """
        Run a single scraper script with retry logic.
        
        Args:
            scraper_file: Name of the scraper file to run
            max_retries: Maximum number of retry attempts
            
        Returns:
            True if successful, False otherwise
        """
        # Check scrapers/ folder first, then root directory for backward compatibility
        scraper_path = self.project_root / "scrapers" / scraper_file
        if not scraper_path.exists():
            scraper_path = self.project_root / scraper_file
        
        if not scraper_path.exists():
            logger.warning(f"  Warning: {scraper_file} not found, skipping...")
            return False
        
        last_exception = None
        
        for attempt in range(max_retries):
            if attempt > 0:
                wait_time = 2 ** attempt  # Exponential backoff
                logger.info(f"  Retry attempt {attempt + 1}/{max_retries} for {scraper_file} (waiting {wait_time}s)...")
                time.sleep(wait_time)
            
            logger.info(f"\n{'='*60}")
            logger.info(f"Running {scraper_file}... (attempt {attempt + 1}/{max_retries})")
            logger.info(f"{'='*60}")
            
            try:
                # Prepare environment
                env = os.environ.copy()
                # Only add API key if scraper needs it
                if scraper_file not in self.scrapers_no_api:
                    env['OPENAI_API_KEY'] = self.api_key
                
                # Run the scraper (use scraper's directory as working directory)
                scraper_dir = scraper_path.parent
                result = subprocess.run(
                    [sys.executable, str(scraper_path)],
                    cwd=str(scraper_dir),
                    env=env,
                    capture_output=False,  # Show output in real-time
                    text=True,
                    timeout=600  # 10 minute timeout per scraper
                )
                
                if result.returncode == 0:
                    logger.info(f"  ✓ {scraper_file} completed successfully")
                    return True
                else:
                    logger.error(f"  ✗ {scraper_file} failed with return code {result.returncode}")
                    last_exception = f"Return code: {result.returncode}"
                    if attempt < max_retries - 1:
                        continue  # Retry
                    return False
                    
            except subprocess.TimeoutExpired:
                logger.error(f"  ✗ {scraper_file} timed out after 10 minutes")
                last_exception = "Timeout expired"
                if attempt < max_retries - 1:
                    continue  # Retry
                return False
            except Exception as e:
                logger.error(f"  ✗ Error running {scraper_file}: {e}")
                last_exception = str(e)
                if attempt < max_retries - 1:
                    continue  # Retry
                return False
        
        # All retries failed
        logger.error(f"  ✗ {scraper_file} failed after {max_retries} attempts. Last error: {last_exception}")
        return False
    
    def run_all_scrapers(self) -> Dict[str, bool]:
        """
        Run all scrapers sequentially.
        
        Returns:
            Dictionary mapping scraper names to success status
        """
        logger.info("\n" + "="*60)
        logger.info("STEP 1: Running all scrapers")
        logger.info("="*60)
        
        results = {}
        total = len(self.scrapers)
        
        for i, scraper in enumerate(self.scrapers, 1):
            logger.info(f"\n[{i}/{total}] Processing {scraper}...")
            success = self.run_scraper(scraper)
            results[scraper] = success
            
            # Add a small delay between scrapers to avoid overwhelming servers
            if i < total:
                time.sleep(2)
        
        # Print summary
        logger.info("\n" + "="*60)
        logger.info("Scraping Summary:")
        logger.info("="*60)
        successful = sum(1 for v in results.values() if v)
        failed = total - successful
        
        for scraper, success in results.items():
            status = "✓" if success else "✗"
            logger.info(f"  {status} {scraper}")
        
        logger.info(f"\nTotal: {successful} successful, {failed} failed out of {total} scrapers")
        
        return results
    
    def combine_json_files(self) -> bool:
        """
        Combine all scraped JSON files into a single unified file.
        
        Returns:
            True if successful, False otherwise
        """
        logger.info("\n" + "="*60)
        logger.info("STEP 2: Combining JSON files")
        logger.info("="*60)
        
        try:
            combine_scraped_data('all_scraped_articles.json')
            
            # Check if file was created in data/ folder
            unified_file = self.project_root / 'data' / 'all_scraped_articles.json'
            if not unified_file.exists():
                # Fallback to root for backward compatibility
                unified_file = self.project_root / 'all_scraped_articles.json'
            if unified_file.exists():
                with open(unified_file, 'r', encoding='utf-8') as f:
                    articles = json.load(f)
                logger.info(f"\n✓ Successfully created unified file with {len(articles)} articles")
                return True
            else:
                logger.error("\n✗ Unified file was not created")
                return False
                
        except Exception as e:
            logger.error(f"\n✗ Error combining JSON files: {e}")
            return False
    
    def enhance_articles(self, test_mode: bool = False, articles_per_vendor: int = 3) -> bool:
        """
        Enhance articles with main ideas and tags, then save to database.
        
        Args:
            test_mode: If True, only process a limited number of articles per vendor
            articles_per_vendor: Number of articles to process per vendor in test mode
            
        Returns:
            True if successful, False otherwise
        """
        logger.info("\n" + "="*60)
        logger.info("STEP 3: Enhancing articles and saving to database")
        logger.info("="*60)
        
        try:
            # Use multiple API keys if available for parallel processing
            if len(self.api_keys) > 1:
                enhancer = ArticleEnhancer(api_keys=self.api_keys)
                logger.info(f"Using {len(self.api_keys)} API keys for parallel processing")
            else:
                enhancer = ArticleEnhancer(api_key=self.api_key)
            
            # Load articles
            articles = enhancer.load_articles('all_scraped_articles.json')
            if not articles:
                logger.error("✗ No articles to process")
                return False
            
            # Initialize database
            enhancer.init_database('articles_enhanced.db')
            
            # Select articles to process
            if test_mode:
                grouped = enhancer.group_by_source(articles)
                logger.info(f"\nTest mode: Processing {articles_per_vendor} articles per vendor")
                articles_to_process = enhancer.select_test_articles(grouped, per_vendor=articles_per_vendor)
            else:
                articles_to_process = articles
                logger.info(f"\nProcessing all {len(articles_to_process)} articles")
            
            # Enhance articles (pass db_path to enable duplicate checking)
            enhanced_articles = enhancer.enhance_articles(articles_to_process, db_path='articles_enhanced.db')
            
            # Save to JSON (for debugging)
            enhancer.save_enhanced_articles_json(
                enhanced_articles, 
                'all_scraped_articles_enhanced.json'
            )
            
            # Save to database
            enhancer.save_enhanced_articles_db(
                enhanced_articles, 
                'articles_enhanced.db'
            )
            
            logger.info(f"\n✓ Successfully enhanced {len(enhanced_articles)} articles")
            return True
            
        except Exception as e:
            logger.error(f"\n✗ Error enhancing articles: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def run_full_pipeline(self, test_mode: bool = False, articles_per_vendor: int = 3) -> bool:
        """
        Run the complete pipeline: scrape -> combine -> enhance -> save to DB.
        
        Args:
            test_mode: If True, only process a limited number of articles per vendor in enhancement step
            articles_per_vendor: Number of articles to process per vendor in test mode
            
        Returns:
            True if pipeline completed successfully, False otherwise
        """
        logger.info("\n" + "="*60)
        logger.info("STARTING FULL PIPELINE")
        logger.info("="*60)
        logger.info(f"Test mode: {'ON' if test_mode else 'OFF'}")
        if test_mode:
            logger.info(f"Articles per vendor: {articles_per_vendor}")
        logger.info("="*60)
        
        start_time = time.time()
        
        # Step 1: Run all scrapers
        scraping_results = self.run_all_scrapers()
        
        # Step 2: Combine JSON files
        combine_success = self.combine_json_files()
        
        if not combine_success:
            logger.error("\n✗ Pipeline stopped: Failed to combine JSON files")
            return False
        
        # Step 3: Enhance articles and save to database
        enhance_success = self.enhance_articles(test_mode=test_mode, articles_per_vendor=articles_per_vendor)
        
        # Calculate total time
        elapsed_time = time.time() - start_time
        minutes = int(elapsed_time // 60)
        seconds = int(elapsed_time % 60)
        
        # Final summary
        logger.info("\n" + "="*60)
        logger.info("PIPELINE COMPLETE")
        logger.info("="*60)
        logger.info(f"Scraping: {sum(1 for v in scraping_results.values() if v)}/{len(scraping_results)} successful")
        logger.info(f"Combining: {'✓' if combine_success else '✗'}")
        logger.info(f"Enhancement: {'✓' if enhance_success else '✗'}")
        logger.info(f"Total time: {minutes}m {seconds}s")
        logger.info("="*60)
        
        return combine_success and enhance_success


def main():
    """Main function to run the pipeline"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Run the complete scraping and enhancement pipeline')
    parser.add_argument(
        '--test',
        action='store_true',
        help='Run in test mode (only process 3 articles per vendor)'
    )
    parser.add_argument(
        '--articles-per-vendor',
        type=int,
        default=3,
        help='Number of articles to process per vendor in test mode (default: 3)'
    )
    parser.add_argument(
        '--skip-scraping',
        action='store_true',
        help='Skip scraping step (use existing JSON files)'
    )
    parser.add_argument(
        '--skip-combining',
        action='store_true',
        help='Skip combining step (use existing unified JSON)'
    )
    parser.add_argument(
        '--skip-enhancement',
        action='store_true',
        help='Skip enhancement step (only scrape and combine)'
    )
    parser.add_argument(
        '--api-keys',
        type=str,
        help='Comma-separated list of OpenAI API keys (e.g., "key1,key2,key3"). If not provided, will try to get from environment variables.'
    )
    
    args = parser.parse_args()
    
    # Get API keys from command line, environment, or .env file
    api_keys = None
    if args.api_keys:
        # Parse comma-separated keys from command line
        api_keys = [key.strip() for key in args.api_keys.split(',') if key.strip()]
        if not api_keys:
            raise ValueError("--api-keys must contain at least one valid API key")
    else:
        # Try to get multiple keys from environment (OPENAI_API_KEY_1, OPENAI_API_KEY_2, etc.)
        api_keys = []
        i = 1
        while True:
            key = os.getenv(f"OPENAI_API_KEY_{i}")
            if not key:
                # Also check for OPENAI_API_KEY (without number) as first key
                if i == 1:
                    key = os.getenv("OPENAI_API_KEY")
                if not key:
                    break
            api_keys.append(key)
            i += 1
        
        # If no numbered keys found, try comma-separated OPENAI_API_KEYS
        if not api_keys:
            keys_str = os.getenv("OPENAI_API_KEYS")
            if keys_str:
                api_keys = [key.strip() for key in keys_str.split(',') if key.strip()]
        
        # If still no keys, fall back to single OPENAI_API_KEY
        if not api_keys:
            single_key = os.getenv("OPENAI_API_KEY")
            if not single_key:
                raise ValueError("OPENAI_API_KEY must be set in .env file or provided via --api-keys")
            api_keys = [single_key]
    
    # Initialize pipeline with API keys
    if len(api_keys) == 1:
        pipeline = ScrapingPipeline(api_key=api_keys[0])
        logger.info("Using single API key")
    else:
        pipeline = ScrapingPipeline(api_keys=api_keys)
        logger.info(f"Using {len(api_keys)} API keys for parallel processing")
    
    # Run pipeline based on arguments
    if args.skip_scraping and args.skip_combining and args.skip_enhancement:
        logger.info("All steps skipped. Nothing to do.")
        return
    
    if not args.skip_scraping:
        scraping_results = pipeline.run_all_scrapers()
    else:
        logger.info("\nSkipping scraping step (using existing JSON files)")
        scraping_results = {}
    
    if not args.skip_combining:
        combine_success = pipeline.combine_json_files()
        if not combine_success:
            logger.error("\n✗ Pipeline stopped: Failed to combine JSON files")
            return
    else:
        logger.info("\nSkipping combining step (using existing unified JSON)")
    
    if not args.skip_enhancement:
        enhance_success = pipeline.enhance_articles(
            test_mode=args.test,
            articles_per_vendor=args.articles_per_vendor
        )
    else:
        logger.info("\nSkipping enhancement step")


if __name__ == "__main__":
    main()

