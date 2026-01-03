#!/bin/bash
set -e

echo "PORT is: ${PORT}"
echo "Python: $(python -V)"
echo "Which python: $(which python)"
python -c "import chainlit; print('chainlit version ok')"

exec python -u -m chainlit run app.py -h --host 0.0.0.0 --port ${PORT:-8000}
