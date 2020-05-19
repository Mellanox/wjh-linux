#!/usr/bin/env python
"""Collect devlink metrics and publish them via http or save them to a file."""
import argparse
import json
import logging
import os
import prometheus_client
import re
import subprocess
import sys
import time

from prometheus_client.core import CounterMetricFamily


class DevlinkCollector(object):
    """Collect devlink metrics and publish them via http or save them to a
       file."""

    def __init__(self, args=None):
        """Construct the object and parse the arguments."""
        self.args = None
        if not args:
            args = sys.argv[1:]
        self._parse_args(args)

    def _parse_args(self, args):
        """Parse CLI args and set them to self.args."""
        parser = argparse.ArgumentParser()
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            '-f',
            '--textfile-name',
            dest='textfile_name',
            help=('Full file path where to store data for node '
                  'collector to pick up')
        )
        group.add_argument(
            '-l',
            '--listen',
            dest='listen',
            help='Listen host:port, i.e. 0.0.0.0:9417'
        )
        parser.add_argument(
            '-i',
            '--interval',
            dest='interval',
            type=int,
            help=('Number of seconds between updates of the textfile. '
                  'Default is 5 seconds')
        )
        parser.add_argument(
            '-1',
            '--oneshot',
            dest='oneshot',
            action='store_true',
            default=False,
            help='Run only once and exit. Useful for running in a cronjob'
        )
        arguments = parser.parse_args(args)
        if arguments.oneshot and not arguments.textfile_name:
            logging.error('Oneshot has to be used with textfile mode')
            parser.print_help()
            sys.exit(1)
        if arguments.interval and not arguments.textfile_name:
            logging.error('Interval has to be used with textfile mode')
            parser.print_help()
            sys.exit(1)
        if not arguments.interval:
            arguments.interval = 5
        self.args = vars(arguments)

    def update_devlink_stats(self, counter):
        """Update counter with statistics from devlink trap."""
        command = ['devlink', '-s', 'trap', '-jp']
        try:
            proc = subprocess.Popen(command, stdout=subprocess.PIPE)
        except FileNotFoundError:
            logging.critical('devlink not found. Giving up')
            sys.exit(1)
        except PermissionError as e:
            err_str = 'Permission error trying to run devlink: {}'
            logging.critical(err_str.format(e))
            sys.exit(1)
        data = proc.communicate()[0]
        if proc.returncode != 0:
            logging.critical('devlink returned non-zero return code')
            return
        jsonout = json.loads(data)

        for devhandle in jsonout["trap"]:
            for trap in jsonout["trap"][devhandle]:
                labels = [devhandle, trap["name"], trap["group"], trap["type"],
                          trap["action"]]
                counter.add_metric(labels + ["rx_bytes"],
                                   trap["stats"]["rx"]["bytes"])
                counter.add_metric(labels + ["rx_packets"],
                                   trap["stats"]["rx"]["packets"])

    def collect(self):
        """
        Collect the metrics.

        Collect the metrics and yield them. Prometheus client library
        uses this method to respond to http queries or save them to disk.
        """
        counter = CounterMetricFamily('node_net_devlink', 'Devlink data',
                                      labels=['device', 'trap', 'group',
                                              'trap_type', 'action', 'type'])
        self.update_devlink_stats(counter)
        yield counter


if __name__ == '__main__':
    collector = DevlinkCollector()
    registry = prometheus_client.CollectorRegistry()
    registry.register(collector)
    args = collector.args
    if args['listen']:
        (ip, port) = args['listen'].split(':')
        prometheus_client.start_http_server(port=int(port),
                                            addr=ip, registry=registry)
        while True:
            time.sleep(3600)
    if args['textfile_name']:
        while True:
            collector.collect()
            prometheus_client.write_to_textfile(args['textfile_name'],
                                                registry)
            if collector.args['oneshot']:
                sys.exit(0)
            time.sleep(args['interval'])
