# CO2
CO2 reader & logger - reads CO2 values from a sensor and creates a pretty plot out of them. Will also keep a file with latest sensor state.

Run as a service from systemd (recommended and easier) or trigger this script from udev.

For details on the supported devices, see: https://hackaday.io/project/5301-reverse-engineering-a-low-cost-usb-co-monitor

# systemd install guide
NB: This is written for a RapsberryPi. Other platforms might be slightly different.

1. Edit the run configuration @ co2reader.service
2. Link co2reader.service to systemd's directory: sudo ln -s co2reader.service /etc/systemd/system
3. Reload systemd: sudo systemctl daemon-reload
4. Start the service: systemctl start co2reader
5. If everything seems to work, enable the service so it'll be restarted on reboot: sudo systemctl enable co2reader

You may still want to install a udev rule to alias your device: this will enable a pretty name such as /dev/co2, instead of a pseudo-random /dev/hidraw0.

# udev install guide
Use udev to automatically start this script whenever the sensor is plugged:
1. Fix paths in 99-co2dev.rules
2. Copy or link 99-co2dev.rules to /etc/udev/rules.d/
3. udev restart might be necessary: sudo service udev restart
4. Reload rules with sudo udevadm control --reload-rules && udevadm trigger
5. Plug and unplug the sensor

