"""
Script to combine all scraped JSON files into a single consolidated file.
Each article will be tagged with its source company and type (news/blog).
Only title, date, and link fields are kept.
"""

import json
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime


def get_scraped_json_files() -> List[Path]:
    """Find all JSON files that are results of scraping from data folder."""
    current_dir = Path(__file__).parent
    data_dir = current_dir / "data"
    
    if not data_dir.exists():
        print(f"Data directory not found: {data_dir}")
        return []
    
    json_files = []
    
    # Look for files matching the pattern: *_blog_articles.json or *_news.json in data/ folder
    patterns = ['*_blog_articles.json', '*_news.json']
    
    for pattern in patterns:
        json_files.extend(data_dir.glob(pattern))
    
    return sorted(json_files)


def extract_source_name(filename: str) -> str:
    """Extract company name from filename."""
    # Remove extension and common suffixes
    name = filename.replace('_blog_articles.json', '').replace('_news.json', '')
    # Capitalize first letter
    return name.capitalize()


def extract_article_type(filename: str) -> str:
    """Extract article type from filename."""
    if filename.endswith('_news.json'):
        return 'news'
    elif filename.endswith('_blog_articles.json'):
        return 'blog'
    else:
        return 'unknown'


def load_json_file(filepath: Path) -> List[Dict[str, Any]]:
    """Load and parse a JSON file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, list):
                print(f"Warning: {filepath.name} does not contain a list, skipping...")
                return []
            return data
    except json.JSONDecodeError as e:
        print(f"Error parsing {filepath.name}: {e}")
        return []
    except Exception as e:
        print(f"Error reading {filepath.name}: {e}")
        return []


def filter_article_fields(article: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only title, date, and link fields from article."""
    return {
        'title': article.get('title', ''),
        'date': article.get('date', ''),
        'link': article.get('link', '')
    }


def normalize_link(link: str) -> str:
    """Normalize link for comparison (lowercase, strip trailing slashes)."""
    if not link:
        return ''
    # Convert to lowercase and strip whitespace
    normalized = link.lower().strip()
    # Remove trailing slash for consistency
    if normalized.endswith('/'):
        normalized = normalized[:-1]
    return normalized


def remove_duplicates_from_file(filepath: str) -> None:
    """
    Check a JSON file for duplicates and create a deduplicated version.
    Duplicates are identified by the 'link' field.
    
    Args:
        filepath: Path to the JSON file to check for duplicates
    """
    file_path = Path(filepath)
    
    if not file_path.exists():
        print(f"Error: File not found: {filepath}")
        return
    
    # Load the file
    articles = load_json_file(file_path)
    
    if not articles:
        print(f"No articles found in {file_path.name}")
        return
    
    print(f"\nChecking {file_path.name} for duplicates...")
    print(f"Original article count: {len(articles)}")
    
    # Track seen links and unique articles
    seen_links = set()
    unique_articles = []
    duplicate_count = 0
    duplicate_links = []
    
    for article in articles:
        link = article.get('link', '')
        normalized_link = normalize_link(link)
        
        if not normalized_link:
            # Articles without links are kept but warned about
            unique_articles.append(article)
            continue
        
        if normalized_link in seen_links:
            duplicate_count += 1
            duplicate_links.append({
                'link': link,
                'title': article.get('title', 'N/A'),
                'source': article.get('source', 'N/A'),
                'type': article.get('type', 'N/A')
            })
        else:
            seen_links.add(normalized_link)
            unique_articles.append(article)
    
    if duplicate_count == 0:
        print(f"✓ No duplicates found. All {len(articles)} articles are unique.")
        return
    
    # Create output filename with _unique suffix
    file_stem = file_path.stem
    file_suffix = file_path.suffix
    output_filename = f"{file_stem}_unique{file_suffix}"
    output_path = file_path.parent / output_filename
    
    # Sort unique articles by date (same logic as combine_scraped_data)
    def get_sort_key(article: Dict[str, Any]) -> str:
        date_str = article.get('date', '')
        if date_str == 'N/A' or not date_str:
            return '0000-00-00'
        return date_str
    
    try:
        unique_articles.sort(key=get_sort_key, reverse=True)
    except Exception as e:
        print(f"Warning: Could not sort articles by date: {e}")
    
    # Write deduplicated file
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(unique_articles, f, indent=2, ensure_ascii=False)
    
    # Print report
    print("\n" + "="*60)
    print("DUPLICATE REMOVAL REPORT")
    print("="*60)
    print(f"Original articles: {len(articles)}")
    print(f"Unique articles: {len(unique_articles)}")
    print(f"Duplicates removed: {duplicate_count}")
    print(f"\nDeduplicated file saved as: {output_filename}")
    
    if duplicate_links:
        print(f"\nSample duplicates found (showing first 10):")
        print("-" * 60)
        for i, dup in enumerate(duplicate_links[:10], 1):
            print(f"{i}. [{dup['source']}/{dup['type']}] {dup['title'][:60]}...")
            print(f"   Link: {dup['link']}")
        if len(duplicate_links) > 10:
            print(f"\n... and {len(duplicate_links) - 10} more duplicates")
    print("="*60)


def combine_scraped_data(reference_file: str = None):
    """
    Combine all scraped JSON files into a single file with timestamp.
    If a reference file is provided, removes duplicates that exist in that file.
    
    Args:
        reference_file: Optional path to a reference file to check for duplicates
    """
    json_files = get_scraped_json_files()
    
    if not json_files:
        print("No scraped JSON files found in data folder!")
        return
    
    print(f"Found {len(json_files)} scraped JSON files:")
    for f in json_files:
        print(f"  - {f.name}")
    
    # Load reference file links if provided
    reference_links = set()
    if reference_file:
        ref_path = Path(reference_file)
        if ref_path.exists():
            print(f"\nLoading reference file: {ref_path.name}")
            ref_articles = load_json_file(ref_path)
            for article in ref_articles:
                link = article.get('link', '')
                if link:
                    reference_links.add(normalize_link(link))
            print(f"  Found {len(reference_links)} unique links in reference file")
        else:
            print(f"Warning: Reference file not found: {reference_file}")
            print("  Proceeding without duplicate checking...")
    
    all_articles = []
    stats = {}  # {vendor: {news: count, blog: count}}
    duplicate_count = 0
    
    for json_file in json_files:
        source = extract_source_name(json_file.name)
        article_type = extract_article_type(json_file.name)
        articles = load_json_file(json_file)
        
        # Initialize stats for vendor if not exists
        if source not in stats:
            stats[source] = {'news': 0, 'blog': 0}
        
        # Process each article: keep only title, date, link, and add source and type
        for article in articles:
            filtered_article = filter_article_fields(article)
            filtered_article['source'] = source
            filtered_article['type'] = article_type
            
            # Check for duplicates against reference file
            if reference_links:
                link = filtered_article.get('link', '')
                normalized_link = normalize_link(link)
                if normalized_link and normalized_link in reference_links:
                    duplicate_count += 1
                    continue  # Skip duplicate
            
            all_articles.append(filtered_article)
        
        stats[source][article_type] = len(articles)
        print(f"  Loaded {len(articles)} {article_type} articles from {source}")
    
    # Sort by date (newest first) if date field exists
    def get_sort_key(article: Dict[str, Any]) -> str:
        date_str = article.get('date', '')
        # Handle "N/A" dates by putting them at the end
        if date_str == 'N/A' or not date_str:
            return '0000-00-00'
        return date_str
    
    try:
        all_articles.sort(key=get_sort_key, reverse=True)
    except Exception as e:
        print(f"Warning: Could not sort articles by date: {e}")
    
    # Generate output filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_filename = f'all_scraped_articles_{timestamp}.json'
    
    # Write combined data to current directory (not data/ folder to avoid confusion)
    current_dir = Path(__file__).parent
    output_path = current_dir / output_filename
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_articles, f, indent=2, ensure_ascii=False)
    
    print(f"\nSuccessfully combined {len(all_articles)} unique articles into {output_filename}")
    
    if reference_links and duplicate_count > 0:
        print(f"  Removed {duplicate_count} duplicate articles that exist in reference file")
    
    # Print detailed report
    print("\n" + "="*60)
    print("COLLECTION REPORT")
    print("="*60)
    print(f"\nTotal articles collected: {len(all_articles)}")
    if reference_links and duplicate_count > 0:
        print(f"Duplicates removed (vs reference file): {duplicate_count}")
    print("\nBreakdown by vendor and type:")
    print("-" * 60)
    
    total_news = 0
    total_blog = 0
    
    for vendor in sorted(stats.keys()):
        news_count = stats[vendor]['news']
        blog_count = stats[vendor]['blog']
        total_count = news_count + blog_count
        total_news += news_count
        total_blog += blog_count
        
        print(f"{vendor:20} | News: {news_count:4} | Blog: {blog_count:4} | Total: {total_count:4}")
    
    print("-" * 60)
    print(f"{'TOTAL':20} | News: {total_news:4} | Blog: {total_blog:4} | Total: {len(all_articles):4}")
    print("="*60)


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1:
        # If a file path is provided, use it as reference file when combining
        reference_file = sys.argv[1]
        combine_scraped_data(reference_file=reference_file)
    else:
        # Default: combine all scraped data without reference file
        combine_scraped_data()

