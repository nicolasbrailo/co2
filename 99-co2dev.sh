# udev will launch a process and after a time, kill it (And all its descendants. Cruel)
# Schedule the start of the monitor with `at` to get around this limitation

logger "CO2 sensor (probably) plugged. Launching monitor..."

# Exec monitor in 1 minute, so it has time to settle
echo "python /home/pi/co2/reader.py"\
         "/dev/co2_sensor --reports_path /home/pi/co2/ --update_interval 3 --verbose " \
     | at now + 1 minute

logger "Monitor start scheduled in 1 minute."

