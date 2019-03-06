# CO2
CO2 reader & logger - reads CO2 values from a sensor and creates a pretty plot out of them.

For details on the supported devices, see: https://hackaday.io/project/5301-reverse-engineering-a-low-cost-usb-co-monitor

# udev install guide
Use udev to automatically start this script whenever the sensor is plugged:
1. Fix paths in 99-co2dev.rules
2. Copy or link 99-co2dev.rules to /etc/udev/rules.d/
3. udev restart might be necessary: sudo service udev restart
4. Reload rules with sudo udevadm control --reload-rules && udevadm trigger
5. Plug and unplug the sensor

