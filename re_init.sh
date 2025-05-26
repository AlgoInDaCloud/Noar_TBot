#!/bin/bash
docker stop noar_tbot-certbot-1
docker stop noar_tbot-web-1
docker rm noar_tbot-certbot-1
docker rm noar_tbot-web-1
docker rmi -f $(docker images -aq)
sudo rm -r ./data
./init.sh