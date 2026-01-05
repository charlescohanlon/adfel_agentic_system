#!/bin/bash
set -e

echo "=== startup.sh begin ==="
echo "PORT=${PORT}"
echo "PWD=$(pwd)"
echo "LS=$(ls -la)"
python -V
which python

chainlit run app.py -h --host 0.0.0.0 --port $PORT
