#!/usr/bin/env python3.4

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime
from crawler import Crawler


# Defaults
DEFAULT_DOMAIN = 'http://bbc.co.uk/'
DEFAULT_MAX_REDIRECT = 10
DEFAULT_MAX_TASKS = 10


# Args
ARGS = argparse.ArgumentParser(description="A web crawler")
ARGS.add_argument('--target', action="store", default=DEFAULT_DOMAIN,
    help="Target root url (default: http://bbc.co.uk/)")
ARGS.add_argument(
    '--max_redirect', action='store', type=int, metavar='N',
    default=DEFAULT_MAX_REDIRECT, help='Limit redirection chains (for 301, 302 etc.)')
ARGS.add_argument(
    '--max_tasks', action='store', type=int, metavar='N',
    default=DEFAULT_MAX_TASKS, help='Limit concurrent connections')


def start():
    """
        Parse arguments, set up event loop, run crawler, print report.
    """
    args = ARGS.parse_args()

    loop = asyncio.get_event_loop()

    url = args.target
    if '://' not in url:
        url = 'http://' + url

    crawler = Crawler(url, max_redirect=args.max_redirect,
        max_tasks=args.max_tasks
    )

    try:
        loop.run_until_complete(crawler.crawl())
    except KeyboardInterrupt:
        sys.stderr.flush()
        print('\nInterrupted\n')
    finally:
        # reporting.report(crawler)
        crawler.close()
        # Cleanup aiohttp resource
        loop.stop()
        loop.run_forever()
        loop.close()
        visited_data = list(crawler.visited)
        visited_data.sort(key=lambda data: data.url)
        t1 = crawler.t1 or time.time()
        dt = t1 - crawler.t0
        print('Crawling complete  in {}.'.format(dt))
        print('Writing file...')
        file_name = datetime.now().strftime('sitemap_%H_%M_%d_%m_%y.txt')
        with open(file_name, 'w') as file:
            file.write('***************** Sitemap ***************** \n')
            for i, data in enumerate(visited_data):
                count = i + 1
                file.write('{0}. {1}  {2}\n'.format(
                        count, data.url, data.status
                    )
                )
            file.write('\n\n')

            for url, data in crawler.sitemap.items():
                # assets = ', '.join(str(a) for a in data['assets'])
                txt = '\n\n ***************** Assets on {0} ***************** '
                file.write(txt.format(url))
                file.write('\n')
                for asset in data['assets']:
                    for a in asset:
                        file.write('\n - {0}'.format(a.prettify()))

                links = data['links']
                txt = '\n\n***************** Links on {0} ***************** '
                file.write(txt.format(url))
                file.write('\n')
                for link in links:
                    file.write('\n - {0}'.format(link))
                file.write('\n\n')


if __name__ == '__main__':
    start()
