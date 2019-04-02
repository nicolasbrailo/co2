# Most code stolen from 
# * https://hackaday.io/project/5301-reverse-engineering-a-low-cost-usb-co-monitor
# * https://hackaday.io/project/5301-reverse-engineering-a-low-cost-usb-co-monitor/log/17909-all-your-base-are-belong-to-us
# * https://blog.wooga.com/woogas-office-weather-wow-67e24a5338

import time, fcntl, threading, os

class CO2DevReader(object):
    class Disconnected(Exception):
        pass

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

    def __init__(self, logger, device_path, key):
        self._logger = logger
        self._device_path = device_path
        self._device_key = key
        self._fp = None
        self.last_updated = None
        self._reset()

    def _reset(self):
        try:
            if self._fp is not None:
                self._fp.close()
        except Exception:
            pass

        self._fp = None
        self.co2 = None
        self.temperature = None
        self.rel_humidity = None
        self.last_reading = None
        self.status = 'disconnected'

    def connect(self):
        self._reset()
        self._logger.info("Connecting to CO2 sensor @ {}".format(self._device_path))
        try:
            self._fp = open(self._device_path, "a+b",  0)
            HIDIOCSFEATURE_9 = 0xC0094806
            set_report = "\x00" + "".join(chr(e) for e in self._device_key)
            fcntl.ioctl(self._fp, HIDIOCSFEATURE_9, set_report)
            self.status = 'connected'
        except Exception as ex:
            self._logger.error("Connection failed: {}".format(ex))
            raise ex

    def _get_next_op(self):
        if self._fp is None:
            raise IOError

        decrypted = CO2DevReader._decrypt(self._device_key, CO2DevReader._dev_read_next(self._fp))
        if decrypted[4] != 0x0d or (sum(decrypted[:3]) & 0xff) != decrypted[3]:
            raise "Checksum error"

        op = decrypted[0]
        val = decrypted[1] << 8 | decrypted[2]
        return op, val

    def update_sensor_values(self):
        self.last_updated = time.time()
        try:
            op, val = self._get_next_op()
            updated = True
            if op == 0x50:
                self.co2 = val
            elif op == 0x42:
                self.temperature = val/16.0-273.15
            elif op == 0x44:
                self.rel_humidity = val/100.0
            else:
                updated = False

            if updated:
                self.last_reading = time.time()
        except IOError:
            self._fp = None
            self.status = 'disconnected'
            raise CO2DevReader.Disconnected


class CO2DevReaderDaemon(object):
    def __init__(self, logger, co2_dev_reader, args, 
                    on_new_reading_available_callback, on_shutdown_callback):
        self._logger = logger
        self._co2_dev_reader = co2_dev_reader
        self._args = args
        self._on_new_reading_available_callback = on_new_reading_available_callback
        self._on_shutdown_callback = on_shutdown_callback
        self._running = False

    def run(self):
        if self._args.dont_daemonize:
            self._logger.info("Running as normal (non-daemon) task")
        else:
            self._logger.info("Daemonizing...")
            pid = os.fork()
            if pid > 0:
                self._logger.info("Daemon started!")
                os._exit(0)

        self._running = True
        self._bg = threading.Thread(target=self._bg_update_readings)
        self._bg.start()

        self._logger.info("Starting. Will update sensor status every {} seconds".\
                                format(self._args.read_freq_seconds))
        try:
            while True:
                time.sleep(self._args.read_freq_seconds)

                last_stat = "{}: t={}, co2={}, rh={}".format(
                                    self._co2_dev_reader.last_updated,
                                    self._co2_dev_reader.temperature,
                                    self._co2_dev_reader.co2,
                                    self._co2_dev_reader.rel_humidity)
                logger.debug(last_stat)

                self._on_new_reading_available_callback(self._co2_dev_reader)
        except KeyboardInterrupt:
            self._logger.info("Shutdown requested")
            self._on_shutdown_callback()
            service.stop()
 
    def stop(self):
        self._running = False
        self._bg.join()

    def _bg_update_readings(self):
        while self._running:
            try:
                self._co2_dev_reader.update_sensor_values()
            except CO2DevReader.Disconnected:
                try:
                    self._co2_dev_reader.connect()
                except:
                    self._logger.error("Reconnect fail. Retry in {} seconds".
                                            format(self._args.device_reconnection_backoff_seconds)) 
                    time.sleep(self._args.device_reconnection_backoff_seconds)


class DevFileReporter(object):
    """ Keep a file with the latest status of sensor data """

    FORMATS = ['json', 'csv']

    def __init__(self, logger, file_path, fmt):
        self._logger = logger
        self._file_path = file_path

        if fmt == 'json':
            msg = '"updated":{}, "status":{}, "last_reading":{}, "temperature":{}, '+\
                  '"co2":{}, "rel_humidity":{}'
            self._msg_format = '{{' + msg + '}}'
        elif fmt == 'csv':
            self._msg_format = "{},{},{},{},{},{}"
        else:
            raise Exception("Invalid format {}".format(fmt))

        self._logger.info("Will report {} status to {}".format(fmt, self._file_path))

    def on_sensor_updated(self, sensor):
        msg = self._msg_format.format(
                        sensor.last_updated,
                        sensor.status,
                        sensor.last_reading,
                        sensor.temperature,
                        sensor.co2,
                        sensor.rel_humidity)

        with open(self._file_path, 'w+') as fp:
            fp.write(msg)

    def on_shutdown(self):
        self._logger.info("Clean up reporter {}".format(self._file_path))
        try:
            os.remove(self._file_path)
        except:
            self._logger.error("Failed to clean up {}".format(self._file_path))


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

    def __init__(self, logger, graph_fn):
        self._logger = logger
        self._out_fn = graph_fn
        self.start_timestamp = time.time()
        self.series_map = {
                'temp': PlotReporter.TimeSeries(),
                'co2': PlotReporter.TimeSeries(),
            }
        self.series_map['temp'].scale = [0,30]
        self.series_map['co2'].scale = [0,2500]
        self._logger.info("Will plot sensor values at the end of this run")

    def on_sensor_updated(self, sensor):
        if sensor.status != 'connected':
            return
        self.series_map['temp'].add(sensor.temperature)
        self.series_map['co2'].add(sensor.co2)

    def on_shutdown(self):
        self.report()

    def reset(self):
        self.start_timestamp = time.time()
        for k in self.series_map:
            self.series_map[k] = PlotReporter.TimeSeries()

    def report(self):
        self._logger.info("Try to create pretty graph at {}".format(self._out_fn))

        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

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

        if self._out_fn is None: 
            plt.show()
        else:
            plt.savefig(self._out_fn)

        plt.close()
        self._logger.info("Plot created")

class SensorUpdateCallbackComposer(object):
    def __init__(self, callbacks):
        self._callbacks = callbacks

    def on_sensor_updated(self, sensor):
        for cb in self._callbacks:
            cb.on_sensor_updated(sensor)

    def on_shutdown(self):
        for cb in self._callbacks:
            cb.on_shutdown()


def parse_argv(app_descr, device_reconnection_backoff_seconds, read_freq_seconds):
    import argparse
    class ArgsDescrFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
        pass

    parser = argparse.ArgumentParser(description=app_descr, formatter_class=ArgsDescrFormatter)

    parser.add_argument('--verbose', help='Write to syslog each measurement', action='store_true')
    parser.add_argument('--dont_daemonize', help='Don\'t demonize', action='store_true')
    parser.add_argument('--device_reconnection_backoff_seconds', default=device_reconnection_backoff_seconds,
                            type=int, help='If device disconnects: time to wait between reconnection attempts')
    parser.add_argument('--read_freq_seconds', default=read_freq_seconds, type=int,
                           help='Sensor read frequency (seconds)')
    parser.add_argument('--csv_report_decoded_sensor_status_path', default=None,
                           help='Path for a dev-like file which will contain the latest sensor status. CSV format.')
    parser.add_argument('--json_report_decoded_sensor_status_path', default=None,
                           help='Path for a dev-like file which will contain the latest sensor status. JSON format.')
    parser.add_argument('--plot_report_path', help='Create a graph report', default=None)
    parser.add_argument('device_path', help='Device path (eg: /dev/hidraw0)')

    args = parser.parse_args()
    args.app_name = 'CO2Reader'
    return args

def mk_logger(log_name, verbose):
    import logging
    import logging.handlers
    import sys

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(log_name)
    logger.setLevel(logging.DEBUG)

    handler = logging.handlers.SysLogHandler(address = '/dev/log')
    handler.setFormatter(formatter)
    if not verbose:
        handler.setLevel(logging.INFO)
    logger.addHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


READ_FREQ_SECONDS = 60 * 3
DEVICE_RECONNECTION_BACKOFF_SECONDS = 60
APP_DESCR = """Periodically log CO2 and temperature readings from a sensor. For device details, see:

 https://hackaday.io/project/5301-reverse-engineering-a-low-cost-usb-co-monitor

Source for CO2 reader service @ https://github.com/nicolasbrailo/co2
"""

if __name__ == "__main__":
    args = parse_argv(APP_DESCR, DEVICE_RECONNECTION_BACKOFF_SECONDS, READ_FREQ_SECONDS)
    logger = mk_logger(args.app_name, args.verbose)
    logger.info(APP_DESCR)
    logger.info(str(args))

    on_sensor_update_cbs = []

    if args.json_report_decoded_sensor_status_path is not None:
        on_sensor_update_cbs.append(DevFileReporter(logger, args.json_report_decoded_sensor_status_path, 'json'))

    if args.csv_report_decoded_sensor_status_path is not None:
        on_sensor_update_cbs.append(DevFileReporter(logger, args.csv_report_decoded_sensor_status_path, 'csv'))

    if args.plot_report_path is not None:
        on_sensor_update_cbs.append(PlotReporter(logger, args.plot_report_path))

    actions = SensorUpdateCallbackComposer(on_sensor_update_cbs)

    KEY = [0xc4, 0xc6, 0xc0, 0x92, 0x40, 0x23, 0xdc, 0x96]
    reader = CO2DevReader(logger, args.device_path, KEY)
    service = CO2DevReaderDaemon(logger, reader, args, actions.on_sensor_updated, actions.on_shutdown)
    service.run()

