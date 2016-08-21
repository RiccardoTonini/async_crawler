"""A simple web crawler -- class implementing crawling logic."""

import asyncio
import cgi
import logging
import re
import time
import urllib.parse
from bs4 import BeautifulSoup, SoupStrainer
from collections import namedtuple, OrderedDict

try:
    # Python 3.4.
    from asyncio import JoinableQueue as Queue
except ImportError:
    # Python 3.5.
    from asyncio import Queue

import aiohttp  # Install with "pip install aiohttp".

LOGGER = logging.getLogger(__name__)


FetchStatistic = namedtuple('FetchStatistic',
                            ['url',
                             'next_url',
                             'status',
                             'exception',
                             'size',
                             'content_type',
                             'encoding',
                             'num_urls',
                             'num_new_urls'])


class Crawler:
    """Crawl a set of URLs.

    This manages two sets of URLs: 'urls' and 'done'.  'urls' is a set of
    URLs seen, and 'done' is a list of FetchStatistics.
    """
    def __init__(self, root, max_redirect=10, max_tasks=10, *, loop=None):
        self.loop = loop or asyncio.get_event_loop()
        self.root = root
        self.max_redirect = max_redirect
        self.max_tasks = max_tasks
        self.q = Queue(loop=self.loop)
        self.seen_urls = set()
        self.visited = []
        self.session = aiohttp.ClientSession(loop=self.loop)
        self.root_domain = self.extract_domain(root)
        self.add_url(root)
        self.t0 = time.time()
        self.t1 = None
        self.sitemap = {}
        linkregex = re.compile(b'<a [^>]*href=[\'|"](.*?)[\'"].*?>')

    def extract_domain(self, root):
        parts = urllib.parse.urlparse(root)
        host, port = urllib.parse.splitport(parts.netloc)

        if re.match(r'\A[\d\.]*\Z', host):
            return host

        return host.lower()

    def close(self):
        """Close resources."""
        self.session.close()

    def is_redirect(self, response):
        return response.status in (300, 301, 302, 303, 307)

    def host_okay(self, host):
        """
            Check if a host should be crawled.
        """
        host = host.lower()

        if host == self.root_domain:
            return True

        if re.match(r'\A[\d\.]*\Z', host):
            return False

        host = host[4:] if host.startswith('www.') else 'www.' + host
        return host == self.root_domain

    def record_statistic(self, fetch_statistic):
        """Record the FetchStatistic for completed / failed URL."""
        self.visited.append(fetch_statistic)

    def update_sitemap(self, url, response, urls):
        css_tags = BeautifulSoup(response, 'html.parser',
            parse_only=SoupStrainer(name='link', attrs={'rel': 'stylesheet'})
        )
        image_tags = BeautifulSoup(response, 'html.parser',
            parse_only=SoupStrainer(name='img'))
        script_tags = BeautifulSoup(response, 'html.parser',
            parse_only=SoupStrainer(name='script')
        )

        self.sitemap.update({
            url: {'assets': [css_tags, image_tags, script_tags],
            'links': urls}}
        )

    def normalize_url(self, url, response):
        normalized = urllib.parse.urljoin(response.url, url)
        defragmented, frag = urllib.parse.urldefrag(normalized)
        return defragmented

    @asyncio.coroutine
    def parse_response(self, response, url):
        """Return a FetchStatistic and list of links."""
        links = set()
        content_type = None
        encoding = None
        body = yield from response.read()

        if response.status == 200:
            content_type = response.headers.get('content-type')
            pdict = {}

            if content_type:
                content_type, pdict = cgi.parse_header(content_type)

            encoding = pdict.get('charset', 'utf-8')
            if content_type in ('text/html', 'application/xml'):
                text = yield from response.text()

                # Replace href with (?:href|src) to follow image links.
                # urls = set(re.findall(r'''(?i)href=["']([^\s"'<>]+)''', text))
                urls = set([tag['href'] for tag in
                    BeautifulSoup(text, 'html.parser',
                        parse_only=SoupStrainer(name='a', href=True)
                    )
                ])
                normalized_urls = set()
                for url in urls:
                    normalized = self.normalize_url(url, response)
                    normalized_urls.add(normalized)
                    if self.url_allowed(normalized):
                        links.add(normalized)

                self.update_sitemap(response.url, text, normalized_urls)

        stat = FetchStatistic(
            url=response.url,
            next_url=None,
            status=response.status,
            exception=None,
            size=len(body),
            content_type=content_type,
            encoding=encoding,
            num_urls=len(links),
            num_new_urls=len(links - self.seen_urls))

        return stat, links

    def process_redirect(self, response, url, max_redirect):
        location = response.headers['location']
        next_url = urllib.parse.urljoin(url, location)

        if next_url in self.seen_urls:
            # We have been down this path before.
            return
        if max_redirect > 0:
            LOGGER.info('redirect to %r from %r', next_url, url)
            # Follow the redirect. One less redirect remains.
            self.add_url(next_url, max_redirect - 1)
        else:
            LOGGER.error('redirect limit reached for %r from %r',
                         next_url, url)

    @asyncio.coroutine
    def fetch(self, url, max_redirect):
        """Fetch one URL."""

        try:
            response = yield from self.session.get(
                url, allow_redirects=False)
        except aiohttp.ClientError as client_error:
            msg = '{0} raised client error {1}. Aborting...'
            LOGGER.error(msg.format(url, client_error))
            return

        try:
            if self.is_redirect(response):
                self.process_redirect(response, url, max_redirect)
            else:
                stat, links = yield from self.parse_response(response, url)
                self.record_statistic(stat)
                # Queue the links we haven't seen yet
                for link in links.difference(self.seen_urls):
                    self.q.put_nowait((link, self.max_redirect))
                # Remember we have seen this URL.
                self.seen_urls.update(links)
        finally:
            # Return connection to pool.
            yield from response.release()

    @asyncio.coroutine
    def work(self):
        """Process queue items forever."""
        try:
            while True:
                url, max_redirect = yield from self.q.get()
                assert url in self.seen_urls
                yield from self.fetch(url, max_redirect)
                self.q.task_done()
        except asyncio.CancelledError:
            pass

    def url_allowed(self, url):
        parts = urllib.parse.urlparse(url)
        if parts.scheme not in ('http', 'https'):
            LOGGER.debug('skipping non-http scheme in %r', url)
            return False
        host, port = urllib.parse.splitport(parts.netloc)
        if not self.host_okay(host):
            LOGGER.debug('skipping non-root host in %r', url)
            return False
        return True

    def add_url(self, url, max_redirect=None):
        """Add a URL to the queue if not seen before."""
        if max_redirect is None:
            max_redirect = self.max_redirect
        LOGGER.debug('adding %r %r', url, max_redirect)
        self.seen_urls.add(url)
        self.q.put_nowait((url, max_redirect))

    @asyncio.coroutine
    def crawl(self):
        """Run the crawler until all finished."""
        workers = [asyncio.Task(self.work(), loop=self.loop)
                   for _ in range(self.max_tasks)]
        self.t0 = time.time()
        yield from self.q.join()
        self.t1 = time.time()
        for w in workers:
            w.cancel()
