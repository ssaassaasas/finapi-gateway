#!/bin/bash
# FinAPI Gateway 健康检查与自动重启脚本
# 每2分钟由cron调用，检测服务是否存活，挂了就自动拉起

PORT=8000
LOG="/tmp/finapi.log"
PID_FILE="/tmp/finapi.pid"
MAX_RESTART=5
RESTART_COUNT_FILE="/tmp/finapi_restart_count"
WORKDIR="/workspace/finapi"

# 检查端口是否在监听
check_health() {
    response=$(curl -s -m 5 "http://localhost:${PORT}/health" 2>/dev/null)
    if echo "$response" | grep -q '"status":"ok"'; then
        return 0
    fi
    return 1
}

# 获取今日重启次数
get_restart_count() {
    local count_file="$RESTART_COUNT_FILE"
    local today=$(date +%Y-%m-%d)
    
    if [ -f "$count_file" ]; then
        local file_date=$(head -1 "$count_file" 2>/dev/null)
        if [ "$file_date" = "$today" ]; then
            tail -1 "$count_file" 2>/dev/null
            return
        fi
    fi
    echo "0"
}

# 记录重启次数
increment_restart_count() {
    local today=$(date +%Y-%m-%d)
    local count=$(get_restart_count)
    count=$((count + 1))
    printf "%s\n%d" "$today" "$count" > "$RESTART_COUNT_FILE"
}

# 杀死残留进程
kill_stale() {
    pkill -f "uvicorn main:app" 2>/dev/null
    pkill -f "python.*main.py.*8000" 2>/dev/null
    sleep 1
}

# 启动服务
start_service() {
    cd "$WORKDIR"
    nohup python3 main.py > "$LOG" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] FinAPI started, PID=$pid" >> /tmp/finapi_watchdog.log
}

# 主逻辑
if check_health; then
    # 服务正常，清零连续失败计数
    exit 0
fi

# 服务挂了，检查重启次数
count=$(get_restart_count)
if [ "$count" -ge "$MAX_RESTART" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] CRITICAL: 已达今日最大重启次数($MAX_RESTART)，停止重启" >> /tmp/finapi_watchdog.log
    exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Service down, restarting... (restart #$((count+1)) today)" >> /tmp/finapi_watchdog.log

kill_stale
start_service

# 等待启动
sleep 3

# 验证是否成功
if check_health; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restart successful" >> /tmp/finapi_watchdog.log
    increment_restart_count
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restart FAILED" >> /tmp/finapi_watchdog.log
fi
