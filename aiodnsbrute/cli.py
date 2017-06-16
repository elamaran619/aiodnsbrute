import asyncio
import functools
import os
import uvloop
import aiodns
import click
from tqdm import tqdm
import ptpdb


class aioDNSBrute(object):
    """Description goes here eventually..."""

    def __init__(self, verbosity=0, max_tasks=512):
        self.verbosity = verbosity
        self.tasks = []
        self.errors = []
        self.fqdn = []
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        self.loop = asyncio.get_event_loop()
        self.resolver = aiodns.DNSResolver(loop=self.loop)
        self.sem = asyncio.BoundedSemaphore(max_tasks)
        self.pbar = None
        self.c = 0

    def logger(self, msg, msg_type='info', level=1):
        """A quick and dirty msfconsole style stdout logger."""
        if level <= self.verbosity:
            style = {'info': ('[*]', 'blue'), 'pos': ('[+]', 'green'), 'err': ('[-]', 'red'),
                     'warn': ('[!]', 'yellow'), 'dbg': ('[D]', 'cyan')}
            if msg_type is not 0:
                decorator = click.style('{}'.format(style[msg_type][0]), fg=style[msg_type][1], bold=True)
            else:
                decorator = ''
            m = "{} {}".format(decorator, msg)
            tqdm.write(m)

    async def lookup(self, name):
        """Performs a DNS request using aiodns, returns an asyncio future."""
        response = await self.resolver.query(name, 'A')
        return response

    def got_result(self, name, future):
        """Handles the result passed by the lookup function."""
        if future.exception() is not None:
            try:
                err_num = future.exception().args[0]
                err_text = future.exception().args[1]
            except IndexError:
                logger("Couldn't parse exception: {}".format(future.exception()), 'err')
            if (err_num == 4): # This is domain name not found, ignore it.
                pass
            elif (err_num == 12): # Timeout from DNS server
                self.logger("Timeout for {}".format(name), 'warn', 2)
            elif (err_num == 1): # Server answered with no data
                pass
            else:
                self.logger('{} generated an unexpected exception: {}'.format(name, future.exception()), 'err')
            self.errors.append({'hostname': name, 'error': err_text})
        else:
            ip = ', '.join([ip.host for ip in future.result()])
            self.fqdn.append((name, ip))
            self.logger("{:<30}\t{}".format(name, ip), 'pos')
        if self.verbosity >= 1:
            self.pbar.update()
        self.sem.release()

    async def tasker(self, subdomains, domain):
        """ describe this """
        for n in subdomains:
            await self.sem.acquire()
            host = '{}.{}'.format(n, domain)
            task = asyncio.ensure_future(self.lookup(host))
            task.add_done_callback(functools.partial(self.got_result, host))
            self.tasks.append(task)
        await asyncio.gather(*self.tasks, return_exceptions=True)

    def run(self, wordlist, domain):
        # Read the wordlist file
        self.logger("Opening wordlist: {}".format(wordlist), 'dbg', 2)
        with open(wordlist) as f:
            subdomains = f.read().splitlines()
        # Initialize the progress bar
        if self.verbosity >= 1:
            self.pbar = tqdm(total=len(subdomains), unit="rec", maxinterval=0.1, mininterval=0)
        self.logger("Starting {} DNS lookups for {}...".format(len(subdomains), domain))
        try:
            self.loop.run_until_complete(self.tasker(subdomains, domain))
        except KeyboardInterrupt:
            self.logger("Caught keyboard interrupt, cleaning up...")
            asyncio.gather(*asyncio.Task.all_tasks()).cancel()
            self.loop.stop()
        finally:
            self.loop.close()
            self.pbar.close()
            self.logger("Completed, {} subdomains found.".format(len(self.fqdn)))


@click.command()
@click.option('--wordlist', '-w', help='Wordlist to use for brute force.',
              default='{}/wordlists/bitquark_20160227_subdomains_popular_1000'.format(os.path.dirname(os.path.realpath(__file__))))
@click.option('--max-tasks', '-t', default=512,
              help='Maximum number of tasks to run asynchronosly.')
@click.option('--verbosity', '-v', count=True, default=1, help="Turn on/increase output.")
@click.argument('domain', required=True)
def main(wordlist, domain, max_tasks, verbosity):
    """Brute force DNS domain names asynchronously"""
    import csv
    bf = aioDNSBrute(verbosity=verbosity, max_tasks=max_tasks)
    bf.run(wordlist=wordlist, domain=domain)
    # TODO: Add CSV output options to command line
    with open("{}.csv".format(domain.replace(".", "_")), "w") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(['Hostname', 'IPs'])
        writer.writerows(bf.fqdn)

if __name__ == '__main__':
    main()
