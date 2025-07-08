import json
import hashlib
from .logger import Logger
import os
from bs4 import BeautifulSoup
import threading
import queue
from concurrent.futures import ThreadPoolExecutor

class SourceLogger(Logger):

    
    def __init__(self):
        super().__init__()
        self.source_dict = {}
        self.block_map = {}
        self.snapshot_queue = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="snapshot_writer")
        self.pending_snapshots = set()  # Track URLs with pending snapshots
    

    async def init_on_page(self, page, url):
        self.source_dict[url] = []
        self.block_map = {}
        self.page = page
        self.pending_requests = 0
        page.on("response", lambda response: self._filter_source_files(response.request.url, self.source_dict[url]))
        
    

    async def log(self, page, url, environment):
        # Queue snapshot writing in background thread (non-blocking)
        html_content = await page.content()
        self.pending_snapshots.add(url)
        self.executor.submit(self._write_snapshot_threaded, url, html_content)

    def _write_snapshot_threaded(self, url, html_content):
        """
        Writes snapshot to disk in a separate thread.
        """
        try:
            output_path = f'./qa/dom_snapshots/{url.replace("://", "_").replace("/", "_")}.html'
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
                
            print(f"DOM snapshot saved to {output_path}")
            
        except Exception as e:
            print(f"Error writing snapshot for {url}: {e}")
        finally:
            # Remove from pending set when done
            self.pending_snapshots.discard(url)

    def write_logs(self):
        # Wait for all pending snapshots to complete
        print("Waiting for snapshot writing to complete...")
        self.executor.shutdown(wait=True)
        
        # Now process all snapshots
        print("Processing snapshots...")
        for url in self.source_dict.keys():
            self.query_dom_snapshot(url)
        
        # Load existing logs if they exist
        existing_source_files = {}
        existing_block_map = {}
        
        try:
            with open('./qa/source_files.json', 'r') as f:
                existing_source_files = json.load(f)
        except FileNotFoundError:
            pass  # No existing file, start fresh
        
        try:
            with open('./qa/block_map.json', 'r') as f:
                existing_block_map = json.load(f)
        except FileNotFoundError:
            pass  # No existing file, start fresh
        
        # Merge new data with existing data
        # For source_files, merge URL lists
        for url, sources in self.source_dict.items():
            if url in existing_source_files:
                # Merge and deduplicate
                existing_source_files[url] = list(set(existing_source_files[url] + sources))
            else:
                existing_source_files[url] = sources
        
        # For block_map, merge hash entries
        for hash_key, hash_data in self.block_map.items():
            if hash_key in existing_block_map:
                # Merge URLs and deduplicate
                existing_urls = set(existing_block_map[hash_key].get('urls', []))
                new_urls = set(hash_data.get('urls', []))
                existing_block_map[hash_key]['urls'] = list(existing_urls | new_urls)
                # Keep the class_names from the new data (should be the same)
                existing_block_map[hash_key]['class_names'] = hash_data.get('class_names', [])
            else:
                existing_block_map[hash_key] = hash_data
        
        # Write merged data
        with open('./qa/source_files.json', 'w') as f:
            json.dump(existing_source_files, f, indent=2)
        print(f"Source files saved to source_files.json (merged {len(self.source_dict)} new entries)")

        with open('./qa/block_map.json', 'w') as f:
            json.dump(existing_block_map, f, indent=2)
        print(f"Block map saved to block_map.json (merged {len(self.block_map)} new entries)")

    def _filter_source_files(self, response_url, source_files):
        block_path = "/express/code/blocks/"
        if response_url.endswith(".js") and block_path in response_url:
            source_files.append(response_url)
    
    async def query_variants(self, block_name):
        output = []
        variants = await self.page.query_selector_all(f"main .{block_name}")
        if variants:
            for variant in variants:
                class_attr = await variant.get_attribute("class")
                output.append(class_attr.split() if class_attr else [])
            return output
        else:
            return None

    def hash_variants(self, variants):
        if not variants:
            return None
            
        # Create a dictionary mapping hashes to original arrays
        hash_map = {}
        for variant_array in variants:
            # Sort and join each subarray
            variant_str = ' '.join(sorted(variant_array))
            # Create hash
            variant_hash = hashlib.sha256(variant_str.encode()).hexdigest()
            # Map hash to original array
            hash_map[variant_hash] = variant_array
            
        return hash_map
    
    def query_dom_snapshot(self, url):
        """
        Loads a previously saved DOM snapshot and queries the main element's direct children.
        Extracts class names, computes hashes, and saves to block map.
        
        Args:
            url: The URL of the page being queried
        """
        snapshot_path = f'./qa/dom_snapshots/{url.replace("://", "_").replace("/", "_")}.html'
        
        try:
            # Read the HTML file directly
            with open(snapshot_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            soup = BeautifulSoup(html_content, 'html.parser')
            main_element = soup.find('main')
            if not main_element:
                print(f"No main element found in {snapshot_path}")
                return
            section_elements = main_element.find_all(class_='section', recursive=False)
            for section in section_elements:
                direct_children = section.find_all(recursive=False)
                for element in direct_children:
                    class_names = element.get('class', [])
                    if class_names:
                        # Sort class names for consistent hashing
                        sorted_class_names = sorted(class_names)
                        
                        # Compute hash
                        class_str = ' '.join(sorted_class_names)
                        element_hash = hashlib.sha256(class_str.encode()).hexdigest()
                        
                        # Initialize block map entry if it doesn't exist
                        if element_hash not in self.block_map:
                            self.block_map[element_hash] = {
                                "class_names": class_names,
                                "urls": []
                            }
                        
                        # Add URL if not already present
                        if url not in self.block_map[element_hash]["urls"]:
                            self.block_map[element_hash]["urls"].append(url)
                        
        except FileNotFoundError:
            print(f"Snapshot file not found: {snapshot_path}")
        except Exception as e:
            print(f"Error processing snapshot {snapshot_path}: {e}")
        
    def cleanup(self):
        """
        Cleanup method to properly shutdown the thread executor.
        """
        if hasattr(self, 'executor') and self.executor:
            self.executor.shutdown(wait=True)
            print("SourceLogger thread executor shutdown complete")
        
        