#!/bin/sh
set -eu

cd /app
exec python3 -m app.main
