#!/bin/bash
#nginx -c /etc/nginx/nginx.conf
touch /home/noar/supervisord.log
sudo chmod ugo+rw
sudo chown noar:noar /etc/letsencrypt/live/noar-tbot.ip-ddns.com/privkey.pem
#sudo chmod ugo+r /etc/letsencrypt/live/noar-tbot.ip-ddns.com/privkey.pem

/usr/bin/supervisord
while :
do
  sleep 6h
  wait ${!}
  nginx -s reload
done