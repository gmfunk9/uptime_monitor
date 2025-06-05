# uptime_monitor

Simple CLI to log HTTP status, cache hits, TTFB, and full load time.
The monitor stores `website_stats.db` and `urls.txt` in the directory it is run from.

## quick start
```
python3 -m pip install -r requirements.txt
bash startup.sh  # optional
python3 monitor.py
```
Create `urls.txt` with one domain per line.

## todo
- minimal web UI for DB browsing
- plot TTFB & total time
- alerts on repeated failures
- review what metrics actually drive action

Only monitor your own sites. Tested with `funkpd.com` and `akggroup.online`.
