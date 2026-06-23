#!/bin/bash
export PYTHONPATH=$PYTHONPATH:.
gunicorn --worker-class gthread --threads 4 -w 1 --bind 0.0.0.0:$PORT wsgi:app --timeout 120
