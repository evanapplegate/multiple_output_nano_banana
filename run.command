#!/bin/bash
cd "$(dirname "$0")"
open http://localhost:5000 &
python server.py
