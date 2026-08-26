#!/usr/bin/env bash

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="${STORY_MANAGER_RUNTIME_DIR:-$PROJECT_DIR/.run}"
LOG_DIR="$RUNTIME_DIR/logs"
PID_DIR="$RUNTIME_DIR/pids"
LAUNCHER_DIR="$RUNTIME_DIR/launchers"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3.5:9b}"
TRANSCRIPTION_MODEL="${WHISPER_MODEL:-large-v3}"
TRANSCRIPTION_LANGUAGE="${WHISPER_LANGUAGE:-en}"
TRANSCRIPTION_MODEL_CACHE="${WHISPER_MODEL_CACHE:-$RUNTIME_DIR/models/whisperx}"

mkdir -p "$LOG_DIR" "$PID_DIR" "$LAUNCHER_DIR"

info() {
    printf '%s\n' "$*"
}

error() {
    printf 'ERROR: %s\n' "$*" >&2
}

url_ready() {
    curl --silent --show-error --fail --max-time 3 "$1" >/dev/null 2>&1
}

port_in_use() {
    local port="$1"

    if command -v lsof >/dev/null 2>&1; then
        lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
        return
    fi

    if command -v nc >/dev/null 2>&1; then
        nc -z localhost "$port" >/dev/null 2>&1
        return
    fi

    return 1
}

database_ready() {
    command -v docker >/dev/null 2>&1 \
        && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'story-manager-db' \
        && docker exec story-manager-db pg_isready -U storyuser -d story_manager >/dev/null 2>&1
}

start_detached() {
    local service_slug="$1"
    local log_file
    local pid_file
    local launcher_file
    local session_name
    local argument
    shift

    log_file="$LOG_DIR/$service_slug.log"
    pid_file="$PID_DIR/$service_slug.pid"

    if command -v setsid >/dev/null 2>&1; then
        (
            cd "$PROJECT_DIR" || exit 1
            nohup setsid "$@" >"$log_file" 2>&1 < /dev/null &
            printf '%s\n' "$!" >"$pid_file"
        )
        return
    fi

    if command -v screen >/dev/null 2>&1; then
        launcher_file="$LAUNCHER_DIR/$service_slug.sh"
        session_name="story-manager-$service_slug-$$"

        {
            printf '#!/usr/bin/env bash\n'
            printf 'cd %q || exit 1\n' "$PROJECT_DIR"
            printf 'exec'
            for argument in "$@"; do
                printf ' %q' "$argument"
            done
            printf ' >> %q 2>&1\n' "$log_file"
        } >"$launcher_file"
        chmod 700 "$launcher_file"
        rm -f "$pid_file"

        screen -dmS "$session_name" "$launcher_file"
        return
    fi

    (
        cd "$PROJECT_DIR" || exit 1
        nohup "$@" >"$log_file" 2>&1 < /dev/null &
        printf '%s\n' "$!" >"$pid_file"
    )
}

show_failure_log() {
    local service_slug="$1"
    local log_file="$LOG_DIR/$service_slug.log"

    if [ -s "$log_file" ]; then
        error "Last output from $log_file:"
        tail -n 20 "$log_file" >&2
    fi
}

wait_for_url() {
    local service_name="$1"
    local service_slug="$2"
    local url="$3"
    local timeout_seconds="$4"
    local elapsed=0

    while ! url_ready "$url"; do
        if [ "$elapsed" -ge "$timeout_seconds" ]; then
            error "$service_name did not become ready at $url within ${timeout_seconds}s."
            show_failure_log "$service_slug"
            return 1
        fi

        sleep 1
        elapsed=$((elapsed + 1))
    done

    info "READY   $service_name ($url)"
}

ensure_http_service() {
    local service_name="$1"
    local service_slug="$2"
    local url="$3"
    local port="$4"
    local timeout_seconds="$5"
    shift 5

    if url_ready "$url"; then
        info "READY   $service_name ($url) — already running"
        return 0
    fi

    if port_in_use "$port"; then
        error "$service_name is not healthy, but port $port is already occupied. Nothing was started."
        return 1
    fi

    info "START   $service_name"
    start_detached "$service_slug" "$@"
    wait_for_url "$service_name" "$service_slug" "$url" "$timeout_seconds"
}

ensure_database() {
    if database_ready; then
        info "READY   PostgreSQL (localhost:5432) — already running"
        return 0
    fi

    if ! command -v docker >/dev/null 2>&1; then
        error "Docker is required to start PostgreSQL."
        return 1
    fi

    if ! docker info >/dev/null 2>&1; then
        error "Docker is installed but its daemon is not running."
        return 1
    fi

    info "START   PostgreSQL"
    if ! make -C "$PROJECT_DIR" ensure-db; then
        error "PostgreSQL failed to start."
        return 1
    fi

    if ! database_ready; then
        error "PostgreSQL started but did not pass its readiness check."
        return 1
    fi

    info "READY   PostgreSQL (localhost:5432)"
}

ensure_migrations() {
    if [ ! -x "$PROJECT_DIR/.venv/bin/alembic" ]; then
        error "Backend dependencies are missing. Run: make setup"
        return 1
    fi

    info "CHECK   Database migrations"
    if ! make -C "$PROJECT_DIR" migrate; then
        error "Database migrations failed."
        return 1
    fi

    info "READY   Database migrations"
}

ensure_ollama() {
    if url_ready "http://127.0.0.1:11434/api/tags"; then
        info "READY   Ollama (http://127.0.0.1:11434/api/tags) — already running"
        return 0
    fi

    if ! command -v ollama >/dev/null 2>&1; then
        error "Ollama is not installed. Install it with: brew install ollama"
        return 1
    fi

    ensure_http_service \
        "Ollama" \
        "ollama" \
        "http://127.0.0.1:11434/api/tags" \
        "11434" \
        "60" \
        ollama serve
}

check_ollama_model() {
    if ! url_ready "http://127.0.0.1:11434/api/tags"; then
        return 1
    fi

    if ollama list 2>/dev/null | awk -v model="$OLLAMA_MODEL" 'NR > 1 && $1 == model { found = 1 } END { exit !found }'; then
        info "READY   Ollama model ($OLLAMA_MODEL)"
        return 0
    fi

    error "Ollama is running, but $OLLAMA_MODEL is missing. Install it with: make pull-ollama-model"
    return 1
}

ensure_api() {
    if url_ready "http://127.0.0.1:8000/health"; then
        info "READY   API (http://127.0.0.1:8000/health) — already running"
        return 0
    fi

    if [ ! -x "$PROJECT_DIR/.venv/bin/uvicorn" ] || [ ! -x "$PROJECT_DIR/.venv/bin/alembic" ]; then
        error "Backend dependencies are missing. Run: make setup"
        return 1
    fi

    ensure_http_service \
        "API" \
        "api" \
        "http://127.0.0.1:8000/health" \
        "8000" \
        "180" \
        make run-api
}

ensure_ui() {
    if url_ready "http://localhost:5173/"; then
        info "READY   UI (http://localhost:5173/) — already running"
        return 0
    fi

    if [ ! -x "$PROJECT_DIR/frontend/node_modules/.bin/vite" ]; then
        error "Frontend dependencies are missing. Run: make setup"
        return 1
    fi

    ensure_http_service \
        "UI" \
        "ui" \
        "http://localhost:5173/" \
        "5173" \
        "120" \
        make run-ui
}

ensure_omnivoice() {
    local omnivoice_uvicorn="$PROJECT_DIR/services/omnivoice/.venv/bin/uvicorn"

    if url_ready "http://127.0.0.1:8001/health"; then
        info "READY   OmniVoice (http://127.0.0.1:8001/health) — already running"
        return 0
    fi

    if [ ! -x "$omnivoice_uvicorn" ]; then
        if ! command -v uv >/dev/null 2>&1; then
            error "uv is required to install OmniVoice."
            return 1
        fi

        info "SETUP   OmniVoice (first setup may take several minutes)"
        if ! make -C "$PROJECT_DIR" setup-omnivoice; then
            error "OmniVoice setup failed."
            return 1
        fi
    fi

    ensure_http_service \
        "OmniVoice" \
        "omnivoice" \
        "http://127.0.0.1:8001/health" \
        "8001" \
        "900" \
        env PYTORCH_ENABLE_MPS_FALLBACK=1 \
        "$omnivoice_uvicorn" \
        services.omnivoice.server:app \
        --host 127.0.0.1 \
        --port 8001
}

ensure_qwen3_tts() {
    local qwen_project="qwen3_tts"
    local qwen_module="services.qwen3_tts.server:app"
    local qwen_setup_target="setup-qwen3-tts"
    local qwen_uvicorn

    if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
        qwen_project="qwen3_tts_mlx"
        qwen_module="services.qwen3_tts_mlx.server:app"
        qwen_setup_target="setup-qwen3-tts-mlx"
    fi
    qwen_uvicorn="$PROJECT_DIR/services/$qwen_project/.venv/bin/uvicorn"

    if url_ready "http://127.0.0.1:8003/health"; then
        info "READY   Qwen3-TTS (http://127.0.0.1:8003/health) — already running"
        return 0
    fi

    if [ ! -x "$qwen_uvicorn" ]; then
        if ! command -v uv >/dev/null 2>&1; then
            error "uv is required to install Qwen3-TTS."
            return 1
        fi

        info "SETUP   Qwen3-TTS (first setup may take several minutes)"
        if ! make -C "$PROJECT_DIR" "$qwen_setup_target"; then
            error "Qwen3-TTS setup failed."
            return 1
        fi
    fi

    ensure_http_service \
        "Qwen3-TTS" \
        "qwen3-tts" \
        "http://127.0.0.1:8003/health" \
        "8003" \
        "900" \
        env PYTORCH_ENABLE_MPS_FALLBACK=1 \
        "$qwen_uvicorn" \
        "$qwen_module" \
        --host 127.0.0.1 \
        --port 8003
}

ensure_transcription() {
    local transcription_uvicorn="$PROJECT_DIR/services/transcription/.venv/bin/uvicorn"

    if url_ready "http://127.0.0.1:8002/health"; then
        info "READY   WhisperX (http://127.0.0.1:8002/health) — already running"
        return 0
    fi

    if [ ! -x "$transcription_uvicorn" ]; then
        if ! command -v uv >/dev/null 2>&1; then
            error "uv is required to install WhisperX."
            return 1
        fi

        info "SETUP   WhisperX (first setup may take several minutes)"
        if ! make -C "$PROJECT_DIR" setup-transcription; then
            error "WhisperX setup failed."
            return 1
        fi
    fi

    mkdir -p "$TRANSCRIPTION_MODEL_CACHE"
    ensure_http_service \
        "WhisperX" \
        "transcription" \
        "http://127.0.0.1:8002/health" \
        "8002" \
        "1800" \
        env \
        WHISPER_MODEL="$TRANSCRIPTION_MODEL" \
        WHISPER_LANGUAGE="$TRANSCRIPTION_LANGUAGE" \
        WHISPER_MODEL_CACHE="$TRANSCRIPTION_MODEL_CACHE" \
        "$transcription_uvicorn" \
        services.transcription.server:app \
        --host 127.0.0.1 \
        --port 8002
}

print_status() {
    local missing=0

    if database_ready; then
        info "READY   PostgreSQL (localhost:5432)"
    else
        info "MISSING PostgreSQL (localhost:5432)"
        missing=$((missing + 1))
    fi

    if url_ready "http://127.0.0.1:11434/api/tags"; then
        info "READY   Ollama (http://127.0.0.1:11434)"
    else
        info "MISSING Ollama (http://127.0.0.1:11434)"
        missing=$((missing + 1))
    fi

    if url_ready "http://127.0.0.1:8000/health"; then
        info "READY   API (http://localhost:8000)"
    else
        info "MISSING API (http://localhost:8000)"
        missing=$((missing + 1))
    fi

    if url_ready "http://localhost:5173/"; then
        info "READY   UI (http://localhost:5173)"
    else
        info "MISSING UI (http://localhost:5173)"
        missing=$((missing + 1))
    fi

    if url_ready "http://127.0.0.1:8001/health"; then
        info "READY   OmniVoice (http://127.0.0.1:8001)"
    else
        info "MISSING OmniVoice (http://127.0.0.1:8001)"
        missing=$((missing + 1))
    fi

    if url_ready "http://127.0.0.1:8003/health"; then
        info "READY   Qwen3-TTS (http://127.0.0.1:8003)"
    else
        info "MISSING Qwen3-TTS (http://127.0.0.1:8003)"
        missing=$((missing + 1))
    fi

    if url_ready "http://127.0.0.1:8002/health"; then
        info "READY   WhisperX (http://127.0.0.1:8002)"
    else
        info "MISSING WhisperX (http://127.0.0.1:8002)"
        missing=$((missing + 1))
    fi

    [ "$missing" -eq 0 ]
}

usage() {
    printf 'Usage: %s [start|status]\n' "$0"
}

if ! command -v curl >/dev/null 2>&1; then
    error "curl is required for service health checks."
    exit 127
fi

case "${1:-start}" in
    start)
        failures=0

        ensure_database || failures=$((failures + 1))
        ensure_ollama || failures=$((failures + 1))

        if database_ready; then
            if ensure_migrations; then
                ensure_api || failures=$((failures + 1))
            else
                error "Skipping API startup because database migrations failed."
                failures=$((failures + 1))
            fi
        else
            error "Skipping API startup because PostgreSQL is unavailable."
            failures=$((failures + 1))
        fi

        ensure_ui || failures=$((failures + 1))
        ensure_omnivoice || failures=$((failures + 1))
        ensure_qwen3_tts || failures=$((failures + 1))
        ensure_transcription || failures=$((failures + 1))
        check_ollama_model || failures=$((failures + 1))

        printf '\n'
        if [ "$failures" -eq 0 ]; then
            info "All Story Manager services are ready."
            info "Logs for services started by this script: $LOG_DIR"
            exit 0
        fi

        error "$failures startup check(s) failed. Healthy services were left running."
        exit 1
        ;;
    status)
        print_status
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
