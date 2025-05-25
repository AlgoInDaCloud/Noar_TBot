#!/bin/bash
docker stop noar_tbot-certbot-1
docker stop noar_tbot-web-1
docker rm noar_tbot-certbot-1
docker rm noar_tbot-web-1
docker rmi -f $(docker images -aq)
sudo rm -r /home/ubuntu/Noar_TBot/data
/home/ubuntu/Noar_TBot/init.sh