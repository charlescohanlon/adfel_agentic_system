#!/bin/bash
set -e

echo "=== startup.sh begin ==="
echo "PORT=${PORT}"
echo "PWD=$(pwd)"
echo "LS=$(ls -la)"
python -V
which python

# Force reinstall with correct versions before running
pip install --force-reinstall --no-cache-dir \
    opentelemetry-api==1.21.0 \
    opentelemetry-sdk==1.21.0 \
    opentelemetry-exporter-otlp-proto-grpc==1.21.0

chainlit run app.py -h --host 0.0.0.0 --port $PORT
