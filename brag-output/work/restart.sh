#!/bin/bash
# Restart the video data server with fresh data. Uses a PID file (never pkill -f: it can kill the calling shell).
W="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$W/server.pid" ]; then kill "$(cat "$W/server.pid")" 2>/dev/null; sleep 1; fi
# one-time cleanup of a server started by an older version of this script
for p in $(ps -eo pid,args | awk '$0 ~ /python .*work\/vid[e]o_serv/ && $0 !~ /awk/ {print $1}'); do kill "$p" 2>/dev/null; done
sleep 1
cd "$W/../../backend" || exit 1
PYTHONPATH=. nohup .venv/bin/python "$W/video_server.py" > "$W/server.log" 2>&1 &
echo $! > "$W/server.pid"
sleep 6; curl -s -H "Authorization: demo admin" localhost:8080/api/orders | head -c 80; echo
