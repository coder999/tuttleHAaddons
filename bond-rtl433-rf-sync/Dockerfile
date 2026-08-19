FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends rtl-433 iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app/ /app/app/
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8100

CMD ["/run.sh"]
