# Most code stolen from 
# * https://hackaday.io/project/5301-reverse-engineering-a-low-cost-usb-co-monitor
# * https://hackaday.io/project/5301-reverse-engineering-a-low-cost-usb-co-monitor/log/17909-all-your-base-are-belong-to-us
# * https://blog.wooga.com/woogas-office-weather-wow-67e24a5338

from collections import namedtuple
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import random, time, sys, fcntl, time, threading, signal, os, daemon

class CO2DevReader(object):
    @staticmethod
    def _decrypt(key,  data):
        cstate = [0x48,  0x74,  0x65,  0x6D,  0x70,  0x39,  0x39,  0x65]
        shuffle = [2, 4, 0, 7, 1, 6, 5, 3]
        
        phase1 = [0] * 8
        for i, o in enumerate(shuffle):
            phase1[o] = data[i]
        
        phase2 = [0] * 8
        for i in range(8):
            phase2[i] = phase1[i] ^ key[i]
        
        phase3 = [0] * 8
        for i in range(8):
            phase3[i] = ( (phase2[i] >> 3) | (phase2[ (i-1+8)%8 ] << 5) ) & 0xff
        
        ctmp = [0] * 8
        for i in range(8):
            ctmp[i] = ( (cstate[i] >> 4) | (cstate[i]<<4) ) & 0xff
        
        out = [0] * 8
        for i in range(8):
            out[i] = (0x100 + phase3[i] - ctmp[i]) & 0xff
        
        return out

    @staticmethod
    def _dev_read_next(fp):
        return list(ord(e) for e in fp.read(8))

    def __init__(self, device_path, key):
        self._fp = open(device_path, "a+b",  0)
        HIDIOCSFEATURE_9 = 0xC0094806
        set_report = "\x00" + "".join(chr(e) for e in key)
        fcntl.ioctl(self._fp, HIDIOCSFEATURE_9, set_report)

        self._key = key
        self._running = True

        self.co2 = None
        self.temp = None
        self.rel_humidity = None
        self.last_updated = None

        self._bg = threading.Thread(target=self._bg_update_readings)
        self._bg.start()

    def stop(self):
        self._running = False
        self._bg.join()

    def _get_next_op(self):
        decrypted = CO2DevReader._decrypt(self._key, CO2DevReader._dev_read_next(self._fp))
        if decrypted[4] != 0x0d or (sum(decrypted[:3]) & 0xff) != decrypted[3]:
            raise "Checksum error"

        op = decrypted[0]
        val = decrypted[1] << 8 | decrypted[2]
        return op, val

    def _bg_update_readings(self):
        while self._running:
            op, val = self._get_next_op()
            updated = True
            if op == 0x50:
                self.co2 = val
            if op == 0x42:
                self.temp = val/16.0-273.15
            if op == 0x44:
                self.rel_humidity = val/100.0
            else:
                updated = False

            if updated:
                self.last_updated = time.time()

class MultiReporter(object):
    def __init__(self, *reporters):
        self.start_timestamp = time.time()
        self.reporters = list(reporters)

    def attach(self, r):
        self.reporters.append(r)

    def add(self, **kv):
        for rep in self.reporters:
            rep.add(**kv)

    def report(self, path):
        for rep in self.reporters:
            rep.report(path)

    def reset(self):
        self.start_timestamp = time.time()
        for rep in self.reporters:
            rep.reset()

class TextReporter(object):
    def __init__(self, logger):
        self.logger = logger
        self.start_timestamp = time.time()

    def add(self, **kv):
        txt = ""
        for key in kv:
            txt += "{}={}, ".format(key, kv[key])
        self.logger.info(txt)

    def report(self, path):
        pass

    def reset(self):
        self.start_timestamp = time.time()


class PlotReporter(object):
    class TimeSeries(object):
        def __init__(self):
            self.series = []
            self.max = None
            self.min = None
            self.scale = None
        
        def add(self, val):
            self.series.append(val)
            if self.max is None or val > self.max:
                self.max = val
            if self.min is None or val < self.min:
                self.min = val

    def __init__(self, *kv):
        self.start_timestamp = time.time()
        self.series_map = {}
        for k in kv:
            self.series_map[k] = PlotReporter.TimeSeries()

    def add(self, **kv):
        for key in kv:
            self.series_map[key].add(kv[key])

    def set_scales(self, **kv):
        for key in kv:
            self.series_map[key].scale = kv[key]

    def reset(self):
        self.start_timestamp = time.time()
        for k in self.series_map:
            self.series_map[k] = PlotReporter.TimeSeries()

    def report(self, out_fn=None):
        fig, series_plot = plt.subplots()
        series_plot.set_xlabel('time (s)')
        colors = ['blue', 'red', 'green', 'cyan', 'magenta', 'yellow', 'black', 'white']
        series_i = 0

        for series_name in self.series_map:
            series_plot.plot(self.series_map[series_name].series, color=colors[series_i])

            series_plot.axhline(self.series_map[series_name].max, color=colors[series_i])
            txt = "Max {}: {}".format(series_name, self.series_map[series_name].max)
            series_plot.text(0.1, self.series_map[series_name].max, txt, color=colors[series_i])

            series_plot.axhline(self.series_map[series_name].min, color=colors[series_i])
            txt = "Min {}: {}".format(series_name, self.series_map[series_name].min)
            series_plot.text(0.1, self.series_map[series_name].min, txt, color=colors[series_i])

            series_plot.set_ylabel(series_name, color=colors[series_i])
            series_plot.yaxis.set_label_coords(1.05,0.5)
            series_plot.tick_params(axis='y', pad=1+35*series_i, labelcolor=colors[series_i])

            if self.series_map[series_name].scale is not None:
                series_plot.set_ylim(self.series_map[series_name].scale)

            series_plot = series_plot.twinx()
            series_i = (series_i + 1) % len(colors)

        fig.tight_layout()  # otherwise the right y-label is slightly clipped
        plt.axis('off')

        if out_fn is None: 
            plt.show()
        else:
            plt.savefig(out_fn)

        plt.close()


class CO2Daemon(object):
    def __init__(self, update_interval_seconds, report_interval_seconds,
                        reports_path, logger, co2_reader, reporter):

        self.update_interval_seconds = update_interval_seconds
        self.report_interval_seconds = report_interval_seconds
        self.reports_path = reports_path
        self.logger = logger
        self.reader = co2_reader
        self.history = reporter

        signal.signal(signal.SIGUSR1, self.sigusr1_handler)
        signal.signal(signal.SIGUSR2, self.sigusr2_handler)

    def sigusr1_handler(self, *_):
        self.write_report()

    def sigusr2_handler(self, *_):
        self.history.reset()

    def _run_main_loop_step(self):
        self.history.add(co2=self.reader.co2, temp=self.reader.temp)
        self.logger.debug(self.get_last_known_status())

        if time.time() - self.history.start_timestamp > self.report_interval_seconds:
            self.write_report()
            self.history.reset()

    def main_loop(self):
        try:
            self.logger.info("LOOP1")
            while True:
                self.logger.info("LOOP2")
                self._run_main_loop_step()
                self.logger.info("SHHH")
                time.sleep(self.update_interval_seconds)
                self.logger.info("LOOP AGAIN")
        except KeyboardInterrupt:
            self.reader.stop()

        self.logger.info("OUT OF LOOP")
        # Write report outside catch block; uses matplotlib, so it has a non-0
        # chance of failing. If it fails before stopping reader it may zombify.
        self.write_report()

    def write_report(self):
        try:
            fn = self.reports_path + "co2_report_{}.png".format(datetime.now().strftime('%Y%m%d-%H%M%S'))
            self.logger.info("Wrote report to {}".format(fn))
            self.history.report(fn)
        except Exception as ex:
            # Usually run in a daemon loop, so don't let exceptions propagate
            self.logger.error("Can't write report", ex)

    def get_last_known_status(self):
        return "{}: t={}, co2={}, rh={}, updated={}".format(
                            time.time(), self.reader.temp, self.reader.co2,
                            self.reader.rel_humidity, self.reader.last_updated)


def parse_argv(app_descr):
    import argparse
    class ArgsDescrFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
        pass

    parser = argparse.ArgumentParser(description=app_descr.format("$PID"),
       formatter_class=ArgsDescrFormatter)

    parser.add_argument('--update_interval', default=UPDATE_INTERVAL_SECONDS, type=int,
                           help='Sensor read interval (seconds)')
    parser.add_argument('--report_interval', default=REPORT_INTERVAL_SECONDS, type=int,
                           help='Report write interval (seconds)')
    parser.add_argument('--reports_path', default=REPORTS_PATH,
                           help='Directory where reports will be stored.')
    parser.add_argument('--dont_daemonize', help='Don\'t demonize', action='store_true')
    #parser.add_argument('--plot_report', help='Create a graph report', action='store_false')
    #parser.add_argument('--text_report', help='Create a text report of logged values', action='store_true')
    parser.add_argument('device', help='Device filename (eg: /dev/hidraw1)')

    return parser.parse_args()


def mk_logger(log_name):
    import logging
    import logging.handlers
    import sys

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(log_name)
    logger.setLevel(logging.DEBUG)

    handler = logging.handlers.SysLogHandler(address = '/dev/log')
    handler.setFormatter(formatter)
    handler.setLevel(logging.INFO)
    logger.addHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


UPDATE_INTERVAL_SECONDS = 60 * 3
REPORT_INTERVAL_SECONDS = 60 * 60 * 24
REPORTS_PATH = "./"

APP_DESCR = """Periodically log CO2 and temperature readings from a sensor. For device details, see:

 https://hackaday.io/project/5301-reverse-engineering-a-low-cost-usb-co-monitor

Signals accepted (kill -s $SIGNAL {}):
  USR1   Write report with current history data
  USR2   Clean history data
"""

APP_RUN_STATUS = """
Reading from sensor {} every {} seconds.
Will write reports to {} every {} seconds ({} hours).
"""

args = parse_argv(APP_DESCR)
logger = mk_logger('CO2 Reader')

if __name__ == "__main__":
    # Arbitrary key
    KEY = [0xc4, 0xc6, 0xc0, 0x92, 0x40, 0x23, 0xdc, 0x96]
    reader = CO2DevReader(args.device, KEY)

    plotter = PlotReporter('temp', 'co2')
    plotter.set_scales(temp=[0,30], co2=[0,2500])
    reports = MultiReporter(plotter)
    # reports.attach(TextReporter(logger))

    svc = CO2Daemon(args.update_interval, args.report_interval,
                    args.reports_path, logger, reader, reports)

    msg = APP_DESCR.format(os.getpid())
    msg += APP_RUN_STATUS.format(args.device, args.update_interval, args.reports_path,
                     args.report_interval, (args.report_interval/60/60))
    logger.info(msg)

    if args.dont_daemonize:
        logger.info("NO DEMON")
        svc.main_loop()
    else:
        logger.info("DEMON")
        with daemon.DaemonContext():
            logger.info("DEMON LOOP")
            svc.main_loop()



