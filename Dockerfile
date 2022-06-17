#FROM debian:buster-slim
FROM python:3.9-slim-buster
#
# httpredir.debian.org is often unreliable
# https://github.com/docker-library/buildpack-deps/issues/40
#

# RUN echo \
#    'deb ftp://ftp.us.debian.org/debian/ jessie main\n \
#     deb ftp://ftp.us.debian.org/debian/ jessie-updates main\n \
#     deb http://security.debian.org jessie/updates main\n' \
#     > /etc/apt/sources.list
#RUN echo \
#    "deb http://http.us.debian.org/debian/ testing non-free contrib main" >> /etc/apt/sources.list

RUN apt-get update && \
	apt-get install -y --no-install-recommends \
				curl \
				gcc \
#				python3-pip \
#    			python3-dev \
#    			python3-minimal \
#    			python3-setuptools \
#    			python2-minimal \
#    			python-minimal \
    			make \
    			git \
    			vim \
    			bzip2 \
				gnupg \
				nginx redis-server \
				g++ \
				procps \
				net-tools \
	&& \
	apt-get clean -y && \
	rm -rf /var/lib/apt/lists/*
#RUN apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv 0C49F3730359A14518585931BC711F9BA15703C6
RUN /usr/bin/curl -sLO https://www.mongodb.org/static/pgp/server-4.4.asc && /usr/bin/apt-key add server-4.4.asc
#RUN echo "deb http://repo.mongodb.org/apt/debian buster/mongodb-org/4.4 main" > /etc/apt/sources.list.d/mongodb-org-4.4.list
#RUN /usr/bin/curl -sLO https://www.mongodb.org/static/pgp/server-4.4.asc && sudo /usr/bin/apt-key add server-4.4.asc
RUN echo "deb http://repo.mongodb.org/apt/debian buster/mongodb-org/4.4 main" > /etc/apt/sources.list.d/mongodb-org-4.4.list
RUN apt-get update && apt-get install -y mongodb-org

## Upgrade Python
#RUN echo "deb http://http.us.debian.org/debian/ testing non-free contrib main" >> /etc/apt/sources.list
#RUN apt update
#RUN apt upgrade python3 python3-dev python3-minimal

RUN curl -sL https://deb.nodesource.com/setup_12.x | bash -
RUN apt-get install -y --no-install-recommends nodejs

## Upgrade Python
RUN echo \
    "deb http://http.us.debian.org/debian/ testing non-free contrib main" >> /etc/apt/sources.list
#RUN apt update
#RUN apt upgrade python3

# Download pypy
RUN curl -sL 'https://github.com/squeaky-pl/portable-pypy/releases/download/pypy-7.2.0/pypy-7.2.0-linux_x86_64-portable.tar.bz2' > /pypy.tar.bz2 && tar jxvf /pypy.tar.bz2 && rm -rf /pypy.tar.bz2 && mv /pypy* /pypy

# Upgrade pip
#RUN pip install --upgrade --ignore-installed pip
#RUN pip3 install --upgrade --ignore-installed setuptools_scm
RUN pip3 install --upgrade --ignore-installed pip
RUN /pypy/bin/pypy -m ensurepip
RUN /pypy/bin/pip install setuptools_scm

ADD requirements-heroku.txt /app/requirements-heroku.txt
ADD requirements-base.txt /app/requirements-base.txt
ADD requirements-dev.txt /app/requirements-dev.txt
ADD requirements-dashboard.txt /app/requirements-dashboard.txt

RUN python3 -m pip install -r /app/requirements-heroku.txt && \
	python3 -m pip install -r /app/requirements-base.txt && \
	python3 -m pip install -r /app/requirements-dev.txt && \
	python3 -m pip install -r /app/requirements-dashboard.txt && \
	rm -rf ~/.cache


RUN /pypy/bin/pip install -r /app/requirements-heroku.txt && \
	/pypy/bin/pip install -r /app/requirements-base.txt && \
	/pypy/bin/pip install -r /app/requirements-dev.txt && \
	/pypy/bin/pip install -r /app/requirements-dashboard.txt && \
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
