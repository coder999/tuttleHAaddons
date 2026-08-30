# Pinned to a specific Debian release, not the floating `python:3.12-slim`
# tag - see 1.0.9 CHANGELOG entry. That tag silently tracks whatever Debian
# release is currently "stable", and it rolled from bookworm to trixie
# underneath us, which bumped apt's `rtl-433` package from 22.11 to 25.02.
# 25.02 sends a stricter rtl_tcp handshake than the pi's old rtl-sdr 0.6.0-3
# rtl_tcp server supports, so every connection failed immediately with
# `[rtltcp_open] Bad rtl_tcp header (-1)`. Pin the release explicitly so a
# future rebuild can't silently break compatibility the same way again.
FROM python:3.12-slim-bookworm

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
