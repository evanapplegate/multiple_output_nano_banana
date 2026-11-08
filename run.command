#!/bin/bash
cd "$(dirname "$0")"
open http://localhost:5050 &
python3 server.py
