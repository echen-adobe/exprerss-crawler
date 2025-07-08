import json
from .logger import Logger

class FailureLogger(Logger):
    def __init__(self):
        super().__init__()
        self.failed_urls = []

    async def init_on_page(self, page, url):
        # No initialization needed for failure logging
        pass

    async def log(self, page, url, environment, error=None, stack_trace=None):
        if error:
            self.failed_urls.append({
                'url': url,
                'environment': environment,
                'error': str(error)
            })
            print(f"Failed to process {url}: {str(error)}")
            print(stack_trace)

    def write_logs(self):
        # Load existing failed URLs if they exist
        existing_failed_urls = []
        
        try:
            with open('./qa/failed_urls.json', 'r') as f:
                existing_failed_urls = json.load(f)
        except FileNotFoundError:
            pass  # No existing file, start fresh
        
        # Merge new failures with existing ones
        # Create a set of existing URL+environment combinations to avoid duplicates
        existing_combinations = {(item['url'], item['environment']) for item in existing_failed_urls}
        
        # Add new failures that aren't already recorded
        for new_failure in self.failed_urls:
            combination = (new_failure['url'], new_failure['environment'])
            if combination not in existing_combinations:
                existing_failed_urls.append(new_failure)
        
        # Write merged data
        with open('./qa/failed_urls.json', 'w') as f:
            json.dump(existing_failed_urls, f, indent=2)
        print(f"Failed URLs saved to failed_urls.json (merged {len(self.failed_urls)} new failures)")
        print(f"Total failures: {len(existing_failed_urls)}")

    def get_failure_count(self):
        return len(self.failed_urls) 