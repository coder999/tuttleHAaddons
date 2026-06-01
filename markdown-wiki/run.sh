#!/bin/sh
set -eu

exec gunicorn -b 0.0.0.0:8099 app:app
