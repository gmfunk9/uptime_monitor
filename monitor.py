#!/usr/bin/env python3

import requests
import datetime
import logging.handlers
import sqlite3
from urllib.parse import urlparse
from pathlib import Path
from collections import defaultdict


class WebsiteMonitor:
    def __init__(self, urls_file, db_file):
        """Initialize with urls_file and db_file"""
        self.urls_file = Path(urls_file)
        self.db_file = Path(db_file)
        self.websites = []
        self.conn = None
        self.website_stats = {}
        self.consecutive_failures = defaultdict(int)
        self.summary_stats = {'total': 0, 'errors': 0, 'misses': 0}
        
        # Set up journal logging
        self._setup_logging()

    def _setup_logging(self):
        """Configure systemd journal logging"""
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        
        # Clear any existing handlers
        logger.handlers.clear()
        
        # Create syslog handler for systemd journal
        syslog_handler = logging.handlers.SysLogHandler(address='/dev/log')
        syslog_handler.setFormatter(logging.Formatter('uptime_monitor: %(message)s'))
        logger.addHandler(syslog_handler)

    def setup_database(self):
        """Create SQLite database and establish connection"""
        try:
            self.db_file.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(self.db_file)
            self.conn.execute('PRAGMA journal_mode=WAL')
        except Exception as e:
            logging.error(f"Database setup failed: {e}")
            raise

    def read_urls(self):
        """Read websites from urls_file"""
        try:
            if not self.urls_file.exists():
                raise FileNotFoundError(f"URLs file not found: {self.urls_file}")
            
            with open(self.urls_file, "r") as file:
                self.websites = [line.strip() for line in file if line.strip() and not line.startswith('#')]
        except Exception as e:
            logging.error(f"Failed to read URLs file: {e}")
            raise

    def validate_url(self, url):
        """Validate URL format"""
        try:
            parsed = urlparse(url)
            return bool(parsed.netloc) and parsed.scheme in ('http', 'https')
        except Exception:
            return False

    def send_request(self, url):
        """Send HTTP request and return response"""
        try:
            response = requests.get(
                url, 
                headers={"User-Agent": "Mozilla/5.0 (uptime-monitor)"},
                timeout=30,
                allow_redirects=True
            )
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logging.info(f"{url}: Request failed - {type(e).__name__}: {e}")
            return None
        except Exception as e:
            logging.error(f"{url}: Unexpected error - {e}")
            return None

    def get_website_stats(self, website_response, start_time):
        """Extract performance stats from response"""
        response_code = website_response.status_code
        cf_cache_status = website_response.headers.get("cf-cache-status")
        x_litespeed_cache = website_response.headers.get("x-litespeed-cache")
        ttfb = round(website_response.elapsed.total_seconds(), 3)
        total_time = round((datetime.datetime.now() - start_time).total_seconds(), 3)
        
        return {
            "response_code": response_code,
            "cf_cache_status": cf_cache_status,
            "x_litespeed_cache": x_litespeed_cache,
            "ttfb": ttfb,
            "total": total_time
        }

    def get_error_stats(self):
        """Return stats structure for failed requests"""
        return {
            "response_code": None,
            "cf_cache_status": None,
            "x_litespeed_cache": None,
            "ttfb": None,
            "total": None
        }

    def create_website_table(self, domain):
        """Create table for website domain"""
        try:
            table_name = self._sanitize_table_name(domain)
            query = f'''
                CREATE TABLE IF NOT EXISTS {table_name} (
                    timestamp TEXT PRIMARY KEY,
                    response_code INTEGER,
                    cf_cache_status TEXT,
                    x_litespeed_cache TEXT,
                    ttfb REAL,
                    total REAL
                )
            '''
            self.conn.execute(query)
        except Exception as e:
            logging.error(f"Failed to create table for {domain}: {e}")

    def _sanitize_table_name(self, domain):
        """Convert domain to valid SQLite table name"""
        return domain.replace(".", "_").replace("-", "_").lower()

    def prune_old_data(self):
        """Remove entries older than 30 days from all tables"""
        try:
            cutoff_date = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M")
            
            cursor = self.conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            
            total_deleted = 0
            for table in tables:
                table_name = table[0]
                cursor.execute(f"DELETE FROM {table_name} WHERE timestamp < ?", (cutoff_date,))
                deleted = cursor.rowcount
                total_deleted += deleted
            
            if total_deleted > 0:
                logging.info(f"Pruned {total_deleted} old records")
                
            self.conn.commit()
        except Exception as e:
            logging.error(f"Failed to prune old data: {e}")

    def save_website_stats(self, domain, timestamp, stats):
        """Save stats for a single website"""
        try:
            table_name = self._sanitize_table_name(domain)
            self.create_website_table(domain)
            
            self.conn.execute(f'''
                INSERT OR REPLACE INTO {table_name} 
                (timestamp, response_code, cf_cache_status, x_litespeed_cache, ttfb, total)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                timestamp,
                stats["response_code"],
                stats["cf_cache_status"],
                stats["x_litespeed_cache"],
                stats["ttfb"],
                stats["total"]
            ))
        except Exception as e:
            logging.error(f"Failed to save stats for {domain}: {e}")

    def get_domain_name(self, url):
        """Extract domain name from URL"""
        try:
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return None

    def check_cache_status(self, stats, url):
        """Check if response was cached and log cache misses"""
        cf_status = stats.get("cf_cache_status", "").lower() if stats.get("cf_cache_status") else ""
        ls_status = stats.get("x_litespeed_cache", "").lower() if stats.get("x_litespeed_cache") else ""
        
        # Consider it cached if either CF or LiteSpeed shows cache hit
        is_cached = ("hit" in cf_status) or ("hit" in ls_status)
        
        if not is_cached and stats.get("response_code") == 200:
            self.summary_stats['misses'] += 1
            logging.info(f"{url}: Cache miss (CF: {cf_status or 'none'}, LS: {ls_status or 'none'})")

    def monitor_websites(self):
        """Monitor all websites and collect stats"""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")
        
        for website in self.websites:
            if not self.validate_url(website):
                logging.error(f"Invalid URL format: {website}")
                continue
                
            self.summary_stats['total'] += 1
            domain = self.get_domain_name(website)
            if not domain:
                logging.error(f"Could not extract domain from: {website}")
                continue
                
            start_time = datetime.datetime.now()
            response = self.send_request(website)
            
            if response is not None:
                stats = self.get_website_stats(response, start_time)
                self.consecutive_failures[domain] = 0  # Reset failure counter
                
                # Log non-200 responses
                if stats["response_code"] != 200:
                    logging.info(f"{website}: HTTP {stats['response_code']}")
                
                # Check cache status
                self.check_cache_status(stats, website)
                
            else:
                stats = self.get_error_stats()
                self.summary_stats['errors'] += 1
                self.consecutive_failures[domain] += 1
                
                # Warn about consecutive failures
                if self.consecutive_failures[domain] >= 3:
                    logging.warning(f"{website}: {self.consecutive_failures[domain]} consecutive failures")
            
            self.save_website_stats(domain, timestamp, stats)
        
        self.conn.commit()

    def log_summary(self):
        """Log final summary statistics"""
        logging.info(f"Monitoring complete: {self.summary_stats['total']} sites, "
                    f"{self.summary_stats['errors']} errors, "
                    f"{self.summary_stats['misses']} cache misses")

    def close_connection(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()

    def run(self):
        """Main execution method"""
        try:
            self.setup_database()
            self.read_urls()
            self.prune_old_data()
            self.monitor_websites()
            self.log_summary()
        except Exception as e:
            logging.error(f"Monitor execution failed: {e}")
            raise
        finally:
            self.close_connection()


if __name__ == "__main__":
    monitor = WebsiteMonitor(
        "/home/ffunk/PROJECTS/UPTIME_MONITOR/urls.txt",
        "/home/ffunk/PROJECTS/UPTIME_MONITOR/website_stats.db"
    )
    monitor.run()
