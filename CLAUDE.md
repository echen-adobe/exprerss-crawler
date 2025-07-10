# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Express Crawler is a Python-based web crawling tool designed for QA testing of Adobe Express web pages. It uses Playwright for browser automation and supports parallel crawling of control and experimental branches for A/B testing.

## Development Commands

### Setup
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
source venv/bin/activate  # On macOS/Linux
# or
venv\Scripts\activate  # On Windows

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install
```

### Running the Crawler
```bash
# Run crawler with a specific sitemap
python crawl.py --sitemap ./sitemaps/[sitemap_name].json

# Retry failed URLs from previous run
python crawl.py --sitemap ./sitemaps/[sitemap_name].json --retry

# Run diff checker to compare screenshots
python diff-checker.py
```

## Architecture Overview

### Core Components

1. **crawl.py**: Main crawler orchestrator
   - Implements dual-context crawling (control vs experimental)
   - Uses Playwright with stealth mode to avoid detection
   - Processes URLs in batches (default: 3 URLs)
   - Limited to 30 URLs per run
   - Supports retry functionality for failed URLs

2. **Logger System** (backend/loggers/):
   - **BaseLogger**: Abstract interface for all loggers
   - **SourceLogger**: Tracks JavaScript sources and DOM snapshots
   - **FailureLogger**: Records failed URLs with error messages
   - **ScreenshotLogger**: Captures page screenshots (currently disabled)

3. **diff-checker.py**: Image comparison utility
   - Uses hamming distance algorithm
   - Generates visual diff images
   - Outputs results to diff_urls.json

### Data Flow

1. Sitemap Configuration → URL Generation
2. Parallel Crawling (Control + Experimental)
3. Screenshot Capture + DOM Snapshot
4. Source File Tracking
5. Diff Analysis
6. Results Output to /qa directory

### Output Structure
```
/qa/
├── control/          # Control branch screenshots
├── experimental/     # Experimental branch screenshots
├── diff/            # Difference images
├── dom_snapshots/   # HTML snapshots
├── source_files.json
├── block_map.json
├── failed_urls.json
└── diff_urls.json
```

## Key Technical Details

- **Concurrency**: Uses asyncio for parallel processing
- **Stealth Mode**: Implements playwright-stealth to bypass automation detection
- **Incremental Updates**: Logs are merged, not overwritten
- **Network Idle**: Waits for network activity to complete before capturing
- **Custom Headers**: Configurable user agent and HTTP headers

## Common Tasks

### Adding New Sitemap Configuration
Create a JSON file in /sitemaps/ with:
```json
{
  "experimental_branch_host": "https://stage.express.adobe.com",
  "control_branch_host": "https://express.adobe.com",
  "urls": [],
  "sitemap_url": "https://express.adobe.com/express-sitemap-en-us-0.xml"
}
```

### Debugging Failed URLs
1. Check /qa/failed_urls.json for error messages
2. Run with --retry flag to reprocess failures
3. Failed URLs are processed in batches of 10 during retry

### Modifying Crawl Behavior
- Batch size: Modify `batch_size` parameter in crawl.py
- URL limit: Change hardcoded limit (currently 30) in crawl.py
- Timeout settings: Adjust Playwright timeout configurations
- Stealth settings: Modify stealth plugin configuration

## Important Considerations

- Authentication is currently commented out - may need to implement login flow
- Limited to 30 URLs per run (consider removing this limitation for production use)
- No automated tests - consider adding pytest suite
- Logs are incremental - be aware when debugging that old data persists