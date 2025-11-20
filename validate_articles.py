"""
Article Validation Script
Reads articles from database, validates each row using OpenAI API,
and updates database with validation status and comments.

Database columns added:
- validation_status: INTEGER (0 = issues found, 1 = everything is good) - filled by LLM
- validation_comment: TEXT (description of issues found) - filled by LLM
- relevance: INTEGER (0 = not relevant, 1 = somewhat relevant, 2 = relevant, NULL = not yet reviewed) - filled by HUMAN only, LLM does not modify this
"""

import os
import sys
import json
import sqlite3
import time
from typing import Dict, Optional, Tuple
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class ArticleValidator:
    """Validates articles using OpenAI API to check if all fields were scraped correctly"""
    
    def __init__(self, api_key: str = None, db_path: str = 'articles_enhanced.db'):
        """
        Initialize the validator with OpenAI API key.
        
        Args:
            api_key: OpenAI API key. If not provided, will try to get from environment.
            db_path: Path to the SQLite database file.
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY in .env file or provide it as argument.")
        
        self.client = OpenAI(api_key=self.api_key)
        self.db_path = db_path
    
    def add_validation_columns(self):
        """
        Add validation_status, validation_comment, and relevance columns to the database if they don't exist.
        
        Columns added:
        - validation_status: INTEGER (0 = issues found, 1 = everything is good) - filled by LLM
        - validation_comment: TEXT (description of issues found) - filled by LLM
        - relevance: INTEGER (0 = not relevant, 1 = somewhat relevant, 2 = relevant, NULL = not yet reviewed) - filled by HUMAN only, LLM does not modify this
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Check if columns already exist
            cursor.execute('PRAGMA table_info(articles)')
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'validation_status' not in columns:
                cursor.execute('''
                    ALTER TABLE articles 
                    ADD COLUMN validation_status INTEGER DEFAULT NULL
                ''')
                print("Added validation_status column")
            
            if 'validation_comment' not in columns:
                cursor.execute('''
                    ALTER TABLE articles 
                    ADD COLUMN validation_comment TEXT DEFAULT NULL
                ''')
                print("Added validation_comment column")
            
            if 'relevance' not in columns:
                cursor.execute('''
                    ALTER TABLE articles 
                    ADD COLUMN relevance INTEGER DEFAULT NULL
                ''')
                print("Added relevance column")
            
            conn.commit()
            print("Database schema updated successfully")
            
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print("Columns already exist, skipping...")
            else:
                raise
        finally:
            conn.close()
    
    def validate_article(self, article_data: Dict) -> Tuple[int, str]:
        """
        Validate an article using OpenAI API.
        
        Args:
            article_data: Dictionary containing article fields (title, date, link, description, source, main_ideas, tags, original_text)
            
        Returns:
            Tuple of (validation_status, comment) where:
            - validation_status: 1 if everything is good, 0 if there are issues
            - comment: Description of what's wrong (empty string if everything is good)
        """
        # Parse JSON fields if they are strings
        main_ideas = article_data.get('main_ideas') or ''
        tags = article_data.get('tags') or ''
        
        if isinstance(main_ideas, str) and main_ideas:
            try:
                main_ideas = json.loads(main_ideas)
            except json.JSONDecodeError:
                main_ideas = []
        elif main_ideas is None:
            main_ideas = []
        
        if isinstance(tags, str) and tags:
            try:
                tags = json.loads(tags)
            except json.JSONDecodeError:
                tags = []
        elif tags is None:
            tags = []
        
        # Prepare data for validation
        validation_data = {
            'title': article_data.get('title', ''),
            'date': article_data.get('date', ''),
            'link': article_data.get('link', ''),
            'description': article_data.get('description', ''),
            'source': article_data.get('source', ''),
            'main_ideas': main_ideas if isinstance(main_ideas, list) else [],
            'tags': tags if isinstance(tags, list) else [],
            'original_text': article_data.get('original_text', '')
        }
        
        # Limit original_text for prompt (first 5000 chars should be enough to check content)
        original_text_preview = validation_data['original_text'][:5000] if validation_data['original_text'] else ''
        
        # Create prompt for OpenAI
        prompt = f"""You are validating scraped article data. Check if all fields were scraped correctly and completely.

Article Data:
- Title: {validation_data['title']}
- Date: {validation_data['date']}
- Link: {validation_data['link']}
- Description: {validation_data['description']}
- Source: {validation_data['source']}
- Main Ideas: {json.dumps(validation_data['main_ideas'], ensure_ascii=False) if validation_data['main_ideas'] else 'None (empty array)'}
- Tags: {json.dumps(validation_data['tags'], ensure_ascii=False) if validation_data['tags'] else 'None (empty array)'}
- Original Text (first 5000 chars): {original_text_preview if original_text_preview else 'None (empty)'}
- Original Text Full Length: {len(validation_data['original_text'])} characters

IMPORTANT: Check ONLY for these 8 specific issues. Do NOT check for any other issues (like date format, URL validity, etc.). Only check for the issues listed below.

Check for the following SPECIFIC issues (mark as status=0 if ANY are found):

1. Title doesn't match the article content: Compare the title with the original_text. If the title is generic (like "Latest news", "News", "Article") or doesn't reflect what the article is actually about, this is an issue.

2. No title at all: Title field is empty, null, or contains only whitespace.

3. No date: Date field is empty, null, or contains only whitespace. NOTE: Future dates are ACCEPTABLE and should NOT be flagged as an issue. Only check if the date field is completely empty or null.

4. Description may be blank: Description is empty. This is ACCEPTABLE and should NOT cause status=0. Only note it in comments if other issues are found.

5. No main ideas: Main ideas array is empty or null (should contain extracted main ideas).

6. No tags: Tags array is empty or null (should contain relevant tags).

7. No original text: Original text is empty, null, or very short (less than 100 characters).

8. Original text contains error messages or irrelevant content: Check if the original_text contains error messages, "404 Not Found", "Access Denied", "Page not found", or other non-article content that suggests the scraping failed.

Return a JSON object with this structure:
{{
  "status": 1 or 0,  // 1 = everything is good, 0 = issues found (use 0 if ANY of issues 1,2,3,5,6,7,8 are present)
  "comment": "List all issues found (1-8), or empty string if everything is good. Be specific about which issues were detected."
}}

Return ONLY valid JSON. No explanations, no markdown, just the JSON object."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert at validating scraped article data. Check ONLY for 8 specific issues: 1) Title doesn't match content, 2) No title, 3) No date (future dates are OK), 4) Blank description (acceptable, don't flag), 5) No main ideas, 6) No tags, 7) No original text, 8) Error messages in original text. Do NOT check for any other issues. Return only valid JSON with status (0 or 1) and comment fields."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,
                max_tokens=500
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
            result = json.loads(result_text)
            
            # Extract status and comment
            status = result.get("status", 1)
            comment = result.get("comment", "")
            
            # Ensure status is 0 or 1
            validation_status = 1 if status == 1 else 0
            
            return validation_status, comment
            
        except json.JSONDecodeError as e:
            print(f"  Error parsing OpenAI response: {e}")
            print(f"  Response was: {result_text[:200]}")
            return 0, f"Error parsing validation response: {str(e)}"
        except Exception as e:
            print(f"  Error calling OpenAI API: {e}")
            return 0, f"Error during validation: {str(e)}"
    
    def validate_all_articles(self, batch_size: int = 1, delay: float = 1.0, only_unvalidated: bool = False):
        """
        Validate all articles in the database.
        
        Args:
            batch_size: Number of articles to process before committing (default: 1)
            delay: Delay in seconds between API calls to avoid rate limiting (default: 1.0)
            only_unvalidated: If True, only validate articles that haven't been validated yet (default: False)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Get all articles (optionally only unvalidated ones)
            if only_unvalidated:
                cursor.execute('''
                    SELECT id, title, date, link, description, source, main_ideas, tags, original_text
                    FROM articles
                    WHERE validation_status IS NULL
                    ORDER BY id
                ''')
            else:
                cursor.execute('''
                    SELECT id, title, date, link, description, source, main_ideas, tags, original_text
                    FROM articles
                    ORDER BY id
                ''')
            
            articles = cursor.fetchall()
            total = len(articles)
            
            if total == 0:
                print("No articles found in database")
                return
            
            print(f"\nFound {total} articles to validate")
            print("=" * 60)
            
            processed = 0
            valid_count = 0
            invalid_count = 0
            
            for i, article_row in enumerate(articles, 1):
                article_id = article_row[0]
                article_data = {
                    'title': article_row[1],
                    'date': article_row[2],
                    'link': article_row[3],
                    'description': article_row[4],
                    'source': article_row[5],
                    'main_ideas': article_row[6],
                    'tags': article_row[7],
                    'original_text': article_row[8]
                }
                
                print(f"\n[{i}/{total}] Validating article ID {article_id}: {article_data.get('title', 'N/A')[:50]}...")
                
                # Validate article
                validation_status, validation_comment = self.validate_article(article_data)
                
                # Update database
                cursor.execute('''
                    UPDATE articles
                    SET validation_status = ?, validation_comment = ?
                    WHERE id = ?
                ''', (validation_status, validation_comment, article_id))
                
                if validation_status == 1:
                    valid_count += 1
                    print(f"  ✓ Valid (Status: {validation_status})")
                else:
                    invalid_count += 1
                    print(f"  ✗ Issues found (Status: {validation_status})")
                    print(f"  Comment: {validation_comment[:100]}...")
                
                processed += 1
                
                # Commit in batches
                if processed % batch_size == 0:
                    conn.commit()
                    print(f"  Committed batch ({processed}/{total})")
                
                # Add delay to avoid rate limiting
                if i < total:
                    time.sleep(delay)
            
            # Final commit
            conn.commit()
            
            print("\n" + "=" * 60)
            print("Validation Complete")
            print("=" * 60)
            print(f"Total processed: {processed}")
            print(f"Valid (status=1): {valid_count}")
            print(f"Invalid (status=0): {invalid_count}")
            print("=" * 60)
            
        except Exception as e:
            print(f"\nError during validation: {e}")
            import traceback
            traceback.print_exc()
            conn.rollback()
        finally:
            conn.close()
    
    def validate_single_article(self, article_id: int):
        """
        Validate a single article by ID (for testing).
        
        Args:
            article_id: ID of the article to validate
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT id, title, date, link, description, source, main_ideas, tags, original_text
                FROM articles
                WHERE id = ?
            ''', (article_id,))
            
            article_row = cursor.fetchone()
            
            if not article_row:
                print(f"Article with ID {article_id} not found")
                return
            
            article_data = {
                'title': article_row[1],
                'date': article_row[2],
                'link': article_row[3],
                'description': article_row[4],
                'source': article_row[5],
                'main_ideas': article_row[6],
                'tags': article_row[7],
                'original_text': article_row[8]
            }
            
            print(f"\nValidating article ID {article_id}:")
            print(f"Title: {article_data.get('title', 'N/A')}")
            print(f"Link: {article_data.get('link', 'N/A')}")
            
            # Validate article
            validation_status, validation_comment = self.validate_article(article_data)
            
            # Update database
            cursor.execute('''
                UPDATE articles
                SET validation_status = ?, validation_comment = ?
                WHERE id = ?
            ''', (validation_status, validation_comment, article_id))
            
            conn.commit()
            
            print(f"\nValidation Status: {validation_status}")
            print(f"Comment: {validation_comment}")
            
        except Exception as e:
            print(f"Error validating article: {e}")
            import traceback
            traceback.print_exc()
            conn.rollback()
        finally:
            conn.close()


def main():
    """Main function to run the validator"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Validate articles in database using OpenAI API')
    parser.add_argument(
        '--db',
        type=str,
        default='articles_enhanced.db',
        help='Path to SQLite database file (default: articles_enhanced.db)'
    )
    parser.add_argument(
        '--id',
        type=int,
        help='Validate a single article by ID (for testing)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=1,
        help='Number of articles to process before committing (default: 1)'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=1.0,
        help='Delay in seconds between API calls (default: 1.0)'
    )
    parser.add_argument(
        '--only-unvalidated',
        action='store_true',
        help='Only validate articles that haven\'t been validated yet (validation_status IS NULL)'
    )
    
    args = parser.parse_args()
    
    # Get API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY must be set in .env file")
    
    # Initialize validator
    validator = ArticleValidator(api_key=api_key, db_path=args.db)
    
    # Add validation columns if they don't exist
    print("Checking database schema...")
    validator.add_validation_columns()
    
    # Validate articles
    if args.id:
        print(f"\nValidating single article (ID: {args.id})...")
        validator.validate_single_article(args.id)
    else:
        print("\nValidating all articles...")
        if args.only_unvalidated:
            print("Mode: Only unvalidated articles")
        validator.validate_all_articles(
            batch_size=args.batch_size,
            delay=args.delay,
            only_unvalidated=args.only_unvalidated
        )


if __name__ == "__main__":
    main()

