#!/bin/bash
# FinAPI Gateway 启动入口
# 用法: bash /workspace/finapi/start.sh
# 功能: 启动FinAPI + 启动cron保活 + 写入PID

WORKDIR="/workspace/finapi"
LOG="/tmp/finapi.log"

cd "$WORKDIR"

# 1. 杀残留进程
pkill -f "python3 main.py" 2>/dev/null
pkill -f "uvicorn main:app" 2>/dev/null
sleep 1

# 2. 启动FinAPI
nohup python3 main.py > "$LOG" 2>&1 &
FINAPI_PID=$!
echo "$FINAPI_PID" > /tmp/finapi.pid
echo "[$(date '+%Y-%m-%d %H:%M:%S')] FinAPI started, PID=$FINAPI_PID"

# 3. 等待启动
sleep 3

# 4. 验证
response=$(curl -s -m 5 "http://localhost:8000/health" 2>/dev/null)
if echo "$response" | grep -q '"status":"ok"'; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] FinAPI health check PASSED"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: FinAPI health check FAILED"
    echo "Check logs: tail -50 $LOG"
fi

# 5. 启动cron保活
service cron status > /dev/null 2>&1 || service cron start 2>/dev/null
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cron watchdog active (every 2 min)"
