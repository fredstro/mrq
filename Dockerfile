FROM python:3.10.5-slim-bullseye

RUN apt-get update && \
	apt-get install -y --no-install-recommends \
				curl \
				gcc \
                systemd \
    			make \
    			git \
    			vim \
    			bzip2 \
				gnupg \
				nginx \
                redis-server \
				g++ \
				procps \
				net-tools \
                less \
    && \
	apt-get clean -y && \
	rm -rf /var/lib/apt/lists/*
    #RUN apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv 0C49F3730359A14518585931BC711F9BA15703C6
RUN /usr/bin/curl -sLO https://www.mongodb.org/static/pgp/server-4.4.asc && /usr/bin/apt-key add server-4.4.asc
RUN echo "deb http://repo.mongodb.org/apt/debian buster/mongodb-org/4.4 main" > /etc/apt/sources.list.d/mongodb-org-4.4.list
RUN apt-get update && apt-get install -y mongodb-org

# Install node
RUN curl -sL https://deb.nodesource.com/setup_12.x | bash -
RUN apt-get install -y --no-install-recommends nodejs

# Download pypy latest version
RUN curl -sL 'https://github.com/squeaky-pl/portable-pypy/releases/download/pypy-7.2.0/pypy-7.2.0-linux_x86_64-portable.tar.bz2' > /pypy.tar.bz2 && tar jxvf /pypy.tar.bz2 && rm -rf /pypy.tar.bz2 && mv /pypy* /pypy
RUN curl -sL 'https://downloads.python.org/pypy/pypy3.9-v7.3.9-linux64.tar.bz2' > /pypy.tar.bz2 && tar jxvf  /pypy.tar.bz2 && rm -rf /pypy.tar.bz2 && mv /pypy* /pypy
# Upgrade pip
#RUN pip install --upgrade --ignore-installed pip
#RUN pip3 install --upgrade --ignore-installed setuptools_scm
RUN pip3 install --upgrade --ignore-installed pip
RUN /pypy/bin/pypy -m ensurepip
RUN /pypy/bin/pip3 install setuptools_scm

ADD requirements-base.txt /app/requirements-base.txt
ADD requirements-dev.txt /app/requirements-dev.txt
ADD requirements-dashboard.txt /app/requirements-dashboard.txt

RUN python3 -m pip install -r /app/requirements-base.txt && \
	python3 -m pip install -r /app/requirements-dev.txt && \
	python3 -m pip install -r /app/requirements-dashboard.txt && \
	rm -rf ~/.cache


RUN /pypy/bin/pip3 install -r /app/requirements-base.txt && \
	/pypy/bin/pip3 install -r /app/requirements-dev.txt && \
	/pypy/bin/pip3 install -r /app/requirements-dashboard.txt && \
	rm -rf ~/.cache

RUN mkdir -p /data/db

RUN ln -s /app/mrq/bin/mrq_run.py /usr/bin/mrq-run
RUN ln -s /app/mrq/bin/mrq_worker.py /usr/bin/mrq-worker
RUN ln -s /app/mrq/bin/mrq_agent.py /usr/bin/mrq-agent
RUN ln -s /app/mrq/dashboard/app.py /usr/bin/mrq-dashboard

ENV PYTHONPATH /app

VOLUME ["/data"]
WORKDIR /app

# Redis and MongoDB services
EXPOSE 6379 27017

# Dashboard, monitoring and docs
EXPOSE 5555 20020 8000
