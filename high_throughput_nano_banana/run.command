#!/bin/bash
cd "$(dirname "$0")"
open http://localhost:5001 &
python3 server.py
