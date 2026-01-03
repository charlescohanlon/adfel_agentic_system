#!/bin/bash
set -e

echo "=== startup.sh begin ==="
echo "PORT=${PORT}"
echo "PWD=$(pwd)"
echo "LS=$(ls -la)"
python -V
which python

# Prove chainlit is importable (dependency install + venv wiring)
echo "Checking chainlit import..."
chainlit -v
echo "Done checking chainlit import."

# Start the server (unbuffered so logs show up immediately)
exec python -u -m chainlit run app.py -h --host 0.0.0.0 --port ${PORT:-8000}
