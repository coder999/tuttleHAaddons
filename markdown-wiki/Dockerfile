FROM python:3.12-slim

WORKDIR /app

COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app/ /app/
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8099

CMD ["/run.sh"]
