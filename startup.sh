#!/bin/sh
python3 -m pip install -r requirements.txt
[ -f urls.txt ] || echo 'https://funkpd.com' > urls.txt
