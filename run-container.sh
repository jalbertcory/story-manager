#!/bin/bash
set -e

uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --app-dir backend &
BACKEND_PID=$!

npm --prefix frontend run dev -- --host 0.0.0.0 &
FRONTEND_PID=$!

trap "kill $BACKEND_PID $FRONTEND_PID" EXIT

wait -n $BACKEND_PID $FRONTEND_PID

