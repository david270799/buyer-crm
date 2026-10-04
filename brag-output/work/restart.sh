#!/bin/bash
# restart the video server with fresh data
for p in $(ps -eo pid,args | awk '/[v]ideo_server/ {print $1}'); do kill $p; done
sleep 1
cd /home/user/buyer-crm/backend && PYTHONPATH=. nohup .venv/bin/python ../brag-output/work/video_server.py > ../brag-output/work/server.log 2>&1 &
sleep 5; curl -s -H "Authorization: demo admin" localhost:8080/api/orders | head -c 80; echo
