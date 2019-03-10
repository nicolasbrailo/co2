# udev will launch a process and after a time, kill it (And all its descendants. Cruel)
# Schedule the start of the monitor with `at` to get around this limitation

logger "CO2 sensor (probably) plugged. Scheduling monitor..."

# Exec monitor in 1 minute, so sensor has time to settle
echo "python /home/pi/co2/reader.py"\
         "/dev/co2_sensor --reports_path /home/pi/co2/ " \
     | at now + 1 minute

logger "Monitor start scheduled in 1 minute."

