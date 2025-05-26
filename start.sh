#!/bin/bash
#nginx -c /etc/nginx/nginx.conf
touch /home/noar/supervisord.log

/usr/bin/supervisord
while :
do
  sleep 6h
  wait ${!}
  nginx -s reload
done