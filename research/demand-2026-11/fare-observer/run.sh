#!/bin/sh
set -eu
umask 077
cd "$(dirname "$0")"
exec /usr/bin/python3 -B observe.py "$@"
