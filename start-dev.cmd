@echo off
cd /d D:\code\turtle-soup
set NODE_OPTIONS=--max-old-space-size=4096
set NEXT_TELEMETRY_DISABLED=1
node node_modules\next\dist\bin\next dev -p 3000