# twitter_crawler.py
import asyncio, json, os, time, argparse
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from loggers.screenshot_logger import ScreenshotLogger
from loggers.source_logger import SourceLogger
from loggers.failure_logger import FailureLogger
from loggers.logger import Logger
import random 
from playwright_stealth import stealth_sync , stealth_async
from typing import List, Dict, Optional
from asyncio import Queue

load_dotenv()

# Replace the hardcoded SITE_MAP with config loading
async def load_config(sitemap_file):
    with open(sitemap_file, 'r') as f:
        config = json.load(f)
    return config

async def get_sitemap(page, sitemap_url):
    await page.goto(sitemap_url)
    await asyncio.sleep(10)
    page_content = await page.content()
    urls = []
    for line in page_content.split('\n'):
        if 'loc' in line:
            start = line.find('<loc>') + 5
            end = line.find('</loc>', start)
            url = line[start:end]   
            if url.startswith("https://www.adobe.com/express/"):
                urls.append(url + '?martech=off')
    return urls

async def get_urls(browser, sitemap_file):
    config = await load_config(sitemap_file)
    urls = config['urls']
    if len(config['urls']) == 0:
        # If urls array is empty, fetch from sitemap
        page = await browser.new_page()
        urls = await get_sitemap(page, config['sitemap_url'])
        await page.close()
    return await get_urls_for_environment(urls, config['control_branch_host']), await get_urls_for_environment(urls, config['experimental_branch_host'])

async def load_failed_urls(failed_urls_path='./qa/failed_urls.json'):
    """Load failed URLs from previous runs"""
    try:
        with open(failed_urls_path, 'r') as f:
            failed_data = json.load(f)
            
        control_urls = [item['url'] for item in failed_data if item['environment'] == 'control']
        experimental_urls = [item['url'] for item in failed_data if item['environment'] == 'experimental']
        
        return control_urls, experimental_urls
    except FileNotFoundError:
        print(f"No failed URLs file found at {failed_urls_path}")
        return [], []

async def get_urls_for_environment(urls, environment):
    environment_urls = []
    for url in urls:
        if url.startswith("/"):
            environment_urls.append(environment + url)
        else:
            location = url.split("//")[1].split("/",1)[1]
            environment_urls.append(environment + "/" + location)
    return environment_urls

async def process_page_with_context(context, url, environment, loggers: dict[str, Logger]):
    page = await context.new_page()
    await page.evaluate("document.documentElement.style.setProperty('--animation-speed', '0s')")
    await page.evaluate("document.documentElement.style.setProperty('transition', 'none')")
    await asyncio.sleep(random.randint(1, 5) / 10.0)
    try:
        # await page.set_viewport_size({"width": 1920, "height": 1080})
        
        # Initialize all loggers for this page
        for logger in loggers.values():
            await logger.init_on_page(page, url)
        
        await page.goto(url)
        await asyncio.sleep(random.randint(1, 5))
        # Add a small delay to allow initial page load
       
        
        await page.wait_for_load_state('networkidle', timeout=45000)
        #await page.wait_for_load_state("load")
        # Log data for this page with all loggers
        for logger in loggers.values():
            await logger.log(page, url, environment)
            
    except Exception as e:
        # On error, only call failure logger
        if 'failure' in loggers:
            import traceback
            stack_trace = traceback.format_exc()
            await loggers['failure'].log(page, url, environment, error=e, stack_trace=stack_trace)
    finally:
        await page.close()

class TabWorker:
    def __init__(self, worker_id: int, page, url_queue: Queue, loggers: dict[str, Logger], crawler_shepherd: 'ConcurrentCrawler'):
        self.worker_id = worker_id
        self.page = page
        self.url_queue = url_queue
        self.loggers = loggers
        self.is_running = True
        self.crawler_shepherd = crawler_shepherd
        
    async def process_urls(self):
        while self.is_running:
            try:
                # Get URL from queue with timeout
                url_data = await asyncio.wait_for(self.url_queue.get(), timeout=5.0)
                if url_data is None:  # Poison pill to stop worker
                    break
                    
                url, environment = url_data
                
                await self.process_single_url(url, environment)
                self.crawler_shepherd.completed_tasks += 1
                print(f"Worker {self.worker_id} completed task number {self.crawler_shepherd.completed_tasks}")
                    
            except asyncio.TimeoutError:
                # No URLs in queue, continue waiting
                continue
            except Exception as e:
                print(f"Worker {self.worker_id} error: {e}")
                
    async def process_single_url(self, url: str, environment: str):
        try:
            # Clear any existing state
            await self.page.evaluate("document.documentElement.style.setProperty('--animation-speed', '0s')")
            await self.page.evaluate("document.documentElement.style.setProperty('transition', 'none')")
            await self.page.evaluate("if (window.gc) window.gc()")
            await asyncio.sleep(random.randint(1, 5) / 10.0)
            
            # Initialize all loggers for this page
            for logger in self.loggers.values():
                await logger.init_on_page(self.page, url)
            
            # Navigate to URL
            await self.page.goto(url)
            await asyncio.sleep(random.randint(1, 5))
            
            await self.page.wait_for_load_state('networkidle', timeout=45000)
            
            # Log data for this page with all loggers
            for logger in self.loggers.values():
                await logger.log(self.page, url, environment)
                
            print(f"Worker {self.worker_id} processed {url}")
            
        except Exception as e:
            # On error, only call failure logger
            if 'failure' in self.loggers:
                import traceback
                stack_trace = traceback.format_exc()
                await self.loggers['failure'].log(self.page, url, environment, error=e, stack_trace=stack_trace)
            print(f"Worker {self.worker_id} error processing {url}: {e}")
            
    def stop(self):
        self.is_running = False

class ConcurrentCrawler:
    def __init__(self, browser, loggers: dict[str, Logger], max_tabs: int = 5, queue_refill_threshold: int = 10):
        self.browser = browser
        self.loggers = loggers
        self.max_tabs = max_tabs
        self.queue_refill_threshold = queue_refill_threshold
        self.url_queue = Queue()  # Single unified queue
        self.workers: List[TabWorker] = []
        self.completed_tasks = 0
        self.control_host = ""
        self.experimental_host = ""
        
    async def initialize_workers(self, context_options: dict):
        # Create control context and workers
        self.control_context = await self.browser.new_context(**context_options)
        await stealth_async(self.control_context)
        
        for i in range(self.max_tabs):
            page = await self.control_context.new_page()
            worker = TabWorker(i, page, self.url_queue, self.loggers, self)
            self.workers.append(worker)
            
        # Create experimental context and workers
        self.experimental_context = await self.browser.new_context(**context_options)
        await stealth_async(self.experimental_context)
        
        for i in range(self.max_tabs):
            page = await self.experimental_context.new_page()
            worker = TabWorker(i + self.max_tabs, page, self.url_queue, self.loggers, self)
            self.workers.append(worker)
            
    async def crawl_urls(self, control_urls: List[str], experimental_urls: List[str], limit: int = 30):
        # Set host information for worker context determination
        if control_urls:
            self.control_host = control_urls[0].split('/')[2]
        if experimental_urls:
            self.experimental_host = experimental_urls[0].split('/')[2]
            
        # Start worker tasks
        worker_tasks = []
        for worker in self.workers:
            worker_tasks.append(asyncio.create_task(worker.process_urls()))
            
        # URL feeder task
        feeder_task = asyncio.create_task(
            self._feed_urls(control_urls[:limit], experimental_urls[:limit])
        )
        
        # Wait for feeder to complete
        await feeder_task
        
        # Send poison pills to stop workers
        for _ in self.workers:
            await self.url_queue.put(None)
            
        # Wait for all workers to complete
        await asyncio.gather(*worker_tasks)
        
    async def _feed_urls(self, control_urls: List[str], experimental_urls: List[str]):
        # Combine all URLs into a single list
        all_urls = []
        for url in control_urls:
            all_urls.append((url, 'control'))
        for url in experimental_urls:
            all_urls.append((url, 'experimental'))
        
        while len(all_urls) > 0:
            if self.url_queue.qsize() < self.queue_refill_threshold: 
                await self.url_queue.put(all_urls.pop(0)) 
                    
            # Small delay to avoid busy waiting
            await asyncio.sleep(0.5)
            
    async def cleanup(self):
        # Stop all workers
        for worker in self.workers:
            worker.stop()
            
        # Close all pages first
        for worker in self.workers:
            try:
                if not worker.page.is_closed():
                    await worker.page.close()
            except Exception as e:
                print(f"Error closing page for worker {worker.worker_id}: {e}")
                
        # Clear worker references
        self.workers.clear()
            
        # Close contexts
        try:
            await self.control_context.close()
        except Exception as e:
            print(f"Error closing control context: {e}")
            
        try:
            await self.experimental_context.close()
        except Exception as e:
            print(f"Error closing experimental context: {e}")
            
        # Clear context references
        self.control_context = None
        self.experimental_context = None

async def main(sitemap_file, max_tabs=5, queue_refill_threshold=10, retry_mode=False, failed_urls_path='./qa/failed_urls.json'):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,  # Changed to False to allow manual login
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-web-security',
                '--disable-features=VizDisplayCompositor'
            ]
        )
        
        # Default user agent and headers for both contexts
        context_options = {
            'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'viewport': {'width': 1920, 'height': 1080},
            'extra_http_headers': {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Ch-Ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
                'Sec-Ch-Ua-Platform': '"macOS"',
                'Sec-Fetch-User': '?1'
            },
            'bypass_csp': True,  # Bypass Content Security Policy
            'ignore_https_errors': True  # Ignore HTTPS errors
        }
        
        # Get URLs based on mode
        if retry_mode:
            print("Running in retry mode - loading failed URLs...")
            control_urls, experimental_urls = await load_failed_urls(failed_urls_path)
            if not control_urls and not experimental_urls:
                print("No failed URLs to retry.")
                return
            print(f"Found {len(control_urls)} control and {len(experimental_urls)} experimental URLs to retry")
            limit = len(control_urls) + len(experimental_urls)  # Process all failed URLs
        else:
            # Create initial context for getting URLs
            initial_context = await browser.new_context(**context_options)
            await stealth_async(initial_context)
            control_urls, experimental_urls = await get_urls(initial_context, sitemap_file)
            await initial_context.close()
            limit = 100
        
        # Initialize loggers
        loggers = {
            'source': SourceLogger(),
            'screenshot': ScreenshotLogger(),
            'failure': FailureLogger()
        }
        
        # Initialize all loggers
        for logger in loggers.values():
            if hasattr(logger, 'initialize') and callable(logger.initialize):
                await logger.initialize()
        
        # Create concurrent crawler
        crawler = ConcurrentCrawler(
            browser=browser,
            loggers=loggers,
            max_tabs=max_tabs,
            queue_refill_threshold=queue_refill_threshold
        )
        
        try:
            # Initialize worker tabs
            await crawler.initialize_workers(context_options)
            
            # Start crawling
            if retry_mode:
                print(f"Starting retry crawl with {max_tabs} tabs per context...")
                # Process failed URLs in smaller batches
                await crawler.crawl_urls(control_urls, experimental_urls, limit)
            else:
                print(f"Starting concurrent crawl with {max_tabs} tabs per context...")
                await crawler.crawl_urls(control_urls, experimental_urls, limit)
            
            # Write all logs at the end
            for logger in loggers.values():
                if hasattr(logger, 'write_logs_async') and callable(logger.write_logs_async):
                    await logger.write_logs_async()
                else:
                    logger.write_logs()
                    
        finally:
            # Clean up crawler and browser
            await crawler.cleanup()
            
            # Clean up logger resources
            for logger in loggers.values():
                if hasattr(logger, 'cleanup'):
                    await logger.cleanup() if asyncio.iscoroutinefunction(logger.cleanup) else logger.cleanup()
                    
            # Clear logger references
            loggers.clear()
            
            await browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Web crawler for QA testing')
    parser.add_argument('--sitemap', type=str, default='./sitemaps/default_sitemap.json',
                      help='Path to the sitemap configuration file (default: default_sitemap.json)')
    parser.add_argument('--max-tabs', type=int, default=5,
                      help='Maximum number of tabs per context (default: 5)')
    parser.add_argument('--queue-threshold', type=int, default=10,
                      help='Queue refill threshold (default: 10)')
    parser.add_argument('--retry', action='store_true',
                      help='Retry failed URLs from previous run')
    
    args = parser.parse_args()
    
    if args.sitemap != 'default_sitemap.json':
        print(f"Using sitemap file: {args.sitemap}")
    else:
        print("Using default sitemap file: default_sitemap.json")
    
    print(f"Configuration: max_tabs={args.max_tabs}, queue_threshold={args.queue_threshold}")
    print("Starting crawler...")
    asyncio.run(main(args.sitemap, args.max_tabs, args.queue_threshold, args.retry))
