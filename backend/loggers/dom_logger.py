from .logger import Logger

class ScreenshotLogger(Logger):
    def __init__(self):
        super().__init__()
        self.screenshot_count = 0

    async def init_on_page(self, page, url):
        # No initialization needed for screenshots
        pass

    async def log(self, page, url, environment):
        location = url.split("//")[1].split("/",1)[1]
        safe_url = location.replace('/', '_').replace('.', '_')
        const cdp = await page.context().newCDPSession(page);

        const snapshot = await cdp.send('DOMSnapshot.captureSnapshot', {
            computedStyles: [
            'display', 'position', 'top', 'left',
            'width',   'height',  'margin', 'padding'
            ],
        });

        self.screenshot_count += 1
        print(f"Screenshot taken for {url} ({environment})")

    def write_logs(self):
        # No need to write logs as screenshots are saved immediately
        print(f"Total screenshots taken: {self.screenshot_count}")

    def get_screenshot_count(self):
        return self.screenshot_count 