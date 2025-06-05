#!/bin/sh
python3 -m pip install -r requirements.txt
mkdir -p /home/ffunk/PROJECTS/UPTIME_MONITOR
[ -f urls.txt ] || echo 'https://funkpd.com' > urls.txt
