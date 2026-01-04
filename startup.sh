#!/bin/bash
set -e

echo "=== startup.sh begin ==="
echo "PORT=${PORT}"
echo "PWD=$(pwd)"
echo "LS=$(ls -la)"
python -V
which python

pip install --upgrade --force-reinstall opentelemetry-sdk opentelemetry-api opentelemetry-exporter-otlp-proto-grpc
chainlit run app.py -h --host 0.0.0.0 --port ${PORT:-8000}
