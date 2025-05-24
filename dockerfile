FROM python:3.12.9-slim

# Install build dependencies and curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
#    libpcre3 libpcre3-dev \
    nginx \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uwsgi

# Copy requirements file and install dependencies
COPY ./requirements.txt /home/host/requirements.txt
RUN pip install --no-cache-dir -r /home/host/requirements.txt
RUN sed -i 's/from numpy import NaN as npNaN/from numpy import nan as npNaN/' /usr/local/lib/python3.12/site-packages/pandas_ta/momentum/squeeze_pro.py
COPY ./modlib/bitget.py /usr/local/lib/python3.12/site-packages/ccxt/bitget.py
# Copy the rest of the project files
COPY . /home/host

#Add user to not run as root
RUN useradd --no-create-home noar

RUN rm /etc/nginx/sites-enabled/default
RUN rm -r /root/.cache

COPY nginx.conf /etc/nginx/
COPY flask-site-nginx.conf /etc/nginx/conf.d/
COPY uwsgi.ini /etc/uwsgi/
COPY supervisord.conf /etc/supervisor/conf.d/

RUN chown -R noar:noar /home/host/
RUN chown noar:noar /run


# Working directory
WORKDIR /home/host
COPY ./start.sh /home/host/start.sh
RUN chmod +x /home/host/start.sh
CMD ["sh","-c", "/home/host/start.sh"]

# Expose the server port
#EXPOSE 8080

# Calculate the number of worker processes based on the number of CPU cores
#CMD ["sh", "-c", "gunicorn -b 0.0.0.0:8080 --workers $(($(nproc --all) * 2 + 1)) app:app"]
