@echo off
cd /d C:\Users\XYXS\trading\Vibe-Trading\agent
set PYTHONPATH=C:\Users\XYXS\trading\Vibe-Trading\agent
python -m cli serve --host 127.0.0.1 --port 8899
