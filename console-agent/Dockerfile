# Pinned to a specific Debian release, not the floating `python:3.12-slim`
# tag - that tag rolled bookworm -> trixie underneath the bond-rtl433-rf-sync
# add-on and silently broke it (see that add-on's 1.0.9 CHANGELOG entry).
# Nothing here comes from apt, so the blast radius is smaller, but the pin
# costs nothing and keeps a rebuild reproducible.
FROM python:3.12-slim-bookworm

WORKDIR /app

COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app/ /app/app/
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
