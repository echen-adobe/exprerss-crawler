# Retry Failed URLs Feature

## Overview
The crawler now supports retrying failed URLs from previous crawl attempts without overwriting existing logs. This is perfect for handling network issues like unstable WiFi connections.

## Usage

### Normal Crawl
```bash
python crawl.py --sitemap ./sitemaps/my_sitemap.json
```

### Retry Failed URLs
```bash
python crawl.py --retry
```

### Retry with Custom Failed URLs File
```bash
python crawl.py --retry --failed-urls ./custom/failed_urls.json
```

## How It Works

### 1. **Failed URL Tracking**
- During normal crawls, any failed URLs are saved to `./qa/failed_urls.json`
- Each failure includes: URL, environment (control/experimental), and error message

### 2. **Retry Mode**
- Loads failed URLs from the JSON file
- Groups them by environment (control/experimental)
- Processes them in smaller batches (10 URLs per batch)
- Merges results with existing logs

### 3. **Log Merging**
- **Source files**: Merges and deduplicates source file lists per URL
- **Block map**: Merges hash entries and deduplicates URL lists
- **Failed URLs**: Adds new failures without duplicating existing ones

## Example Workflow

```bash
# Initial crawl (some URLs fail due to WiFi issues)
python crawl.py --sitemap ./sitemaps/express_pages.json
# Output: 85 successful, 15 failed URLs

# Retry the failed ones
python crawl.py --retry
# Output: 12 successful, 3 still failed

# Retry again if needed
python crawl.py --retry
# Output: 3 successful, 0 failed
```

## Benefits

- **Resilient to network issues**: Don't lose progress due to temporary failures
- **Incremental processing**: Build up complete datasets over multiple runs
- **No data loss**: Existing logs are preserved and merged
- **Flexible**: Can retry specific failure files or use defaults

## Files Generated

- `./qa/source_files.json` - Merged source file data
- `./qa/block_map.json` - Merged block mapping data  
- `./qa/failed_urls.json` - Updated failure list (removes successful retries)
- `./qa/dom_snapshots/` - HTML snapshots for all processed pages 