FROM python:3.12.9-slim

# Install build dependencies and curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    nginx \
    supervisor \
    libnginx-mod-http-modsecurity modsecurity-crs \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uwsgi


#Add user to not run as root / id must be the same as host user having permissions on volumes mounted in docker-compose
RUN groupadd -g 1002 noar && \
    useradd -g noar --uid 1002 noar

# Copy requirements file and install dependencies
COPY ./requirements.txt /home/noar/requirements.txt
RUN pip install --no-cache-dir -r /home/noar/requirements.txt
RUN sed -i 's/from numpy import NaN as npNaN/from numpy import nan as npNaN/' /usr/local/lib/python3.12/site-packages/pandas_ta/momentum/squeeze_pro.py
COPY ./modlib/bitget.py /usr/local/lib/python3.12/site-packages/ccxt/bitget.py


# Copy the rest of the project files
COPY --chown=noar:noar . /home/noar

RUN rm /etc/nginx/sites-enabled/default
RUN rm -r /root/.cache

COPY nginx.conf /etc/nginx/
COPY flask-site-nginx.conf /etc/nginx/conf.d/
COPY uwsgi.ini /etc/uwsgi/
COPY supervisord.conf /etc/supervisor/conf.d/

#RUN chown -R noar:noar /home/noar/
RUN chown noar:noar /run


# Working directory
WORKDIR /home/noar
COPY ./start.sh /home/noar/start.sh
RUN chmod +x /home/noar/start.sh

RUN sed -i 's|#||g' /etc/nginx/modsecurity_includes.conf
RUN sed -i 's|IncludeOptional|#IncludeOptional|g'  /usr/share/modsecurity-crs/owasp-crs.load
RUN sed -i 's|SecRuleEngine DetectionOnly|SecRuleEngine On|' /etc/nginx/modsecurity.conf

#Set proper permissions
RUN chown noar:noar /home/noar/
RUN chown noar:noar /var/lib/nginx

USER noar
CMD ["sh","-c", "/home/noar/start.sh"]

# Expose the server port
#EXPOSE 8080

# Calculate the number of worker processes based on the number of CPU cores
#CMD ["sh", "-c", "gunicorn -b 0.0.0.0:8080 --workers $(($(nproc --all) * 2 + 1)) app:app"]
