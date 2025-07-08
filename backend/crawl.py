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
        if 'href="' in line:
            start = line.find('href="') + 6
            end = line.find('"', start)
            url = line[start:end]
            if url.startswith("https://www.adobe.com/express/"):
                urls.append(url)
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

async def main(sitemap_file):
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
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1'
            },
            'bypass_csp': True,  # Bypass Content Security Policy
            'ignore_https_errors': True  # Ignore HTTPS errors
        }
        
        # Create initial context for manual login
        initial_context = await browser.new_context(**context_options)
        await stealth_async(initial_context)
        
        # Open a page for manual login
        page = await initial_context.new_page()
        print("\nPlease complete the login process in the browser window that just opened.")
        print("Press Enter in this terminal after you have completed the login.\n")
        
        # Wait for user to press Enter
        input()
        
        # Close the initial context after login
        await initial_context.close()
        
        # Create two persistent contexts - one for control and one for experimental
        control_context = await browser.new_context(**context_options)
        experimental_context = await browser.new_context(**context_options)
        await stealth_async(control_context)
        await stealth_async(experimental_context)
        control_urls, experimental_urls = await get_urls(control_context,sitemap_file)
        limit = 10
        batch_size = 1
        
        # Initialize loggers
        loggers = {
            'screenshot': ScreenshotLogger(),
            'failure': FailureLogger()
        }
        
        # Initialize all loggers
        for logger in loggers.values():
            if hasattr(logger, 'initialize') and callable(logger.initialize):
                await logger.initialize()
        
        try:
            for i in range(0, min(limit, len(control_urls)), batch_size):
                control_batch = control_urls[i:i + batch_size]
                experimental_batch = experimental_urls[i:i + batch_size]
                control_tasks = [
                    process_page_with_context(control_context, url, 'control', loggers) 
                    for url in control_batch
                ]
                experimental_tasks = [
                    process_page_with_context(experimental_context, url, 'experimental', loggers) 
                    for url in experimental_batch
                ]
                await asyncio.gather(*(control_tasks + experimental_tasks))
                print(f"Completed batch {i//batch_size + 1}")
                await asyncio.sleep(3)
                control_context = await browser.new_context(**context_options)
                experimental_context = await browser.new_context(**context_options)
            
            # Write all logs at the end
            for logger in loggers.values():
                if hasattr(logger, 'write_logs_async') and callable(logger.write_logs_async):
                    await logger.write_logs_async()
                else:
                    logger.write_logs()
                    
            # Cleanup loggers
            for logger in loggers.values():
                if hasattr(logger, 'cleanup') and callable(logger.cleanup):
                    await logger.cleanup()
        finally:
            # Clean up browser contexts
            await control_context.close()
            await experimental_context.close()
            await browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Web crawler for QA testing')
    parser.add_argument('--sitemap', type=str, default='./sitemaps/default_sitemap.json',
                      help='Path to the sitemap configuration file (default: default_sitemap.json)')
    
    args = parser.parse_args()
    
    if args.sitemap != 'default_sitemap.json':
        print(f"Using sitemap file: {args.sitemap}")
    else:
        print("Using default sitemap file: default_sitemap.json")
    
    print("Starting crawler...")
    asyncio.run(main(args.sitemap))
