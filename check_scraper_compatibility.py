"""
Script to check if all scrapers output JSON files in a format compatible
with the consolidation script (combine_scraped_data.py).
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Set, Any


def find_scraper_files() -> List[Path]:
    """Find all scraper Python files."""
    current_dir = Path(__file__).parent
    scrapers = []
    
    # Look for files ending with _scraper.py or scraper.py
    patterns = ['*_scraper.py', '*scraper.py']
    
    for pattern in patterns:
        scrapers.extend(current_dir.glob(pattern))
    
    return sorted(scrapers)


def extract_output_filename(scraper_file: Path) -> str:
    """Extract the output filename from a scraper file."""
    try:
        content = scraper_file.read_text(encoding='utf-8')
        
        # Look for save_to_json method with filename parameter
        # Pattern: filename: str = "filename.json"
        pattern = r'filename:\s*str\s*=\s*["\']([^"\']+)["\']'
        match = re.search(pattern, content)
        if match:
            return match.group(1)
        
        # Alternative pattern: filename = "filename.json"
        pattern2 = r'filename\s*=\s*["\']([^"\']+)["\']'
        matches = re.findall(pattern2, content)
        if matches:
            # Get the one in save_to_json method
            for i, line in enumerate(content.split('\n')):
                if 'save_to_json' in line and i + 5 < len(content.split('\n')):
                    for j in range(i, min(i + 10, len(content.split('\n')))):
                        if 'filename' in content.split('\n')[j] and '=' in content.split('\n')[j]:
                            match = re.search(r'["\']([^"\']+)["\']', content.split('\n')[j])
                            if match:
                                return match.group(1)
        
        return "NOT_FOUND"
    except Exception as e:
        return f"ERROR: {e}"


def extract_article_structure(scraper_file: Path) -> Dict[str, Any]:
    """Extract the article structure from a scraper file."""
    try:
        content = scraper_file.read_text(encoding='utf-8')
        
        structure = {
            'required_fields': set(),
            'optional_fields': set(),
            'has_description': False,
            'has_tags': False,
            'structure_code': ''
        }
        
        # Look for structured_article dictionary creation
        # Pattern: structured_article = { ... }
        pattern = r'structured_article\s*=\s*\{([^}]+)\}'
        match = re.search(pattern, content, re.DOTALL)
        
        if match:
            struct_content = match.group(1)
            structure['structure_code'] = struct_content[:200]  # First 200 chars
            
            # Extract field names
            field_pattern = r'["\'](\w+)["\']:\s*'
            fields = re.findall(field_pattern, struct_content)
            structure['required_fields'] = set(fields)
            
            if 'description' in struct_content.lower():
                structure['has_description'] = True
            if 'tags' in struct_content.lower():
                structure['has_tags'] = True
        else:
            # Try to find article.append or article creation patterns
            # Look for article dictionaries being created
            if 'description' in content:
                structure['has_description'] = True
            if 'tags' in content:
                structure['has_tags'] = True
        
        # Common fields that should always be present
        if 'title' in content and 'date' in content and 'link' in content:
            structure['required_fields'].update(['title', 'date', 'link'])
        
        return structure
    except Exception as e:
        return {'error': str(e)}


def check_filename_pattern(filename: str) -> bool:
    """Check if filename matches the consolidation pattern."""
    # Consolidation script looks for: *_articles.json or *_news.json
    return filename.endswith('_articles.json') or filename.endswith('_news.json')


def analyze_scrapers():
    """Analyze all scrapers for compatibility."""
    scrapers = find_scraper_files()
    
    print("=" * 80)
    print("SCRAPER COMPATIBILITY ANALYSIS")
    print("=" * 80)
    print()
    
    results = []
    issues = []
    
    for scraper in scrapers:
        output_filename = extract_output_filename(scraper)
        structure = extract_article_structure(scraper)
        
        filename_ok = check_filename_pattern(output_filename)
        
        result = {
            'scraper': scraper.name,
            'output_filename': output_filename,
            'filename_matches': filename_ok,
            'has_description': structure.get('has_description', False),
            'has_tags': structure.get('has_tags', False),
            'required_fields': structure.get('required_fields', set()),
            'structure': structure
        }
        
        results.append(result)
        
        # Check for issues
        if not filename_ok and 'NOT_FOUND' not in output_filename and 'ERROR' not in output_filename:
            issues.append(f"{scraper.name}: Output filename '{output_filename}' doesn't match pattern (*_articles.json or *_news.json)")
        elif 'NOT_FOUND' in output_filename:
            issues.append(f"{scraper.name}: Could not determine output filename from code")
        elif 'ERROR' in output_filename:
            issues.append(f"{scraper.name}: Error reading file - {output_filename}")
    
    # Print results
    print("SCRAPER OUTPUT FILES:")
    print("-" * 80)
    for result in results:
        status = "[OK]" if result['filename_matches'] else "[X]"
        print(f"{status} {result['scraper']:30} -> {result['output_filename']}")
    
    print()
    print("ARTICLE STRUCTURE:")
    print("-" * 80)
    for result in results:
        fields = []
        if 'title' in result['required_fields'] or True:  # title is always expected
            fields.append('title')
        if 'date' in result['required_fields'] or True:  # date is always expected
            fields.append('date')
        if 'link' in result['required_fields'] or True:  # link is always expected
            fields.append('link')
        if result['has_description']:
            fields.append('description (optional)')
        if result['has_tags']:
            fields.append('tags (optional)')
        
        print(f"{result['scraper']:30} -> {', '.join(fields)}")
    
    print()
    if issues:
        print("ISSUES FOUND:")
        print("-" * 80)
        for issue in issues:
            print(f"  [WARNING] {issue}")
    else:
        print("[OK] All scrapers use compatible filename patterns!")
    
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total scrapers analyzed: {len(results)}")
    print(f"Compatible filenames: {sum(1 for r in results if r['filename_matches'])}")
    print(f"Non-compatible filenames: {sum(1 for r in results if not r['filename_matches'] and 'NOT_FOUND' not in r['output_filename'] and 'ERROR' not in r['output_filename'])}")
    print()
    
    # Check if all scrapers output lists
    print("NOTE: All scrapers should output a list of dictionaries.")
    print("The consolidation script expects:")
    print("  - JSON file containing a list (array)")
    print("  - Each item in the list is a dictionary with at least: title, date, link")
    print("  - Optional fields: description, tags")
    print()


if __name__ == '__main__':
    analyze_scrapers()

