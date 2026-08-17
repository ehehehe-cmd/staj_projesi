#!/usr/bin/env bash
# Sıcak Haddeleme HRL sistemini TEK komutla ayağa kaldırır/durdurur —
# TASARIM.md §9 eki (2026-08-17): önceden 3 ayrı terminalde elle
# başlatılan (uvicorn, live_engine --watch, ng serve) yığını tek script'e
# indirger. PostgreSQL/Adminer (infra/docker-compose.yml) ayrıca yönetilir
# (bilerek `down` ile durdurulmaz — DB verisi kalıcı olmalı).
#
# Kullanım:
#   ./dev.sh up       # backend + live_engine + frontend'i arka planda başlatır
#   ./dev.sh down     # üçünü de durdurur (postgres/adminer'a DOKUNMAZ)
#   ./dev.sh status   # hangisi ayakta, hangisi değil
#   ./dev.sh logs [backend|live_engine|frontend]   # canlı log takibi (varsayılan: hepsi)

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT_DIR/.run"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

mkdir -p "$RUN_DIR"

SERVICES=(backend live_engine frontend)

pidfile() { echo "$RUN_DIR/$1.pid"; }
logfile() { echo "$RUN_DIR/$1.log"; }

is_running() {
  local pid_file
  pid_file="$(pidfile "$1")"
  [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

start_service() {
  local name="$1"; shift
  if is_running "$name"; then
    echo "[$name] zaten çalışıyor (PID $(cat "$(pidfile "$name")"))"
    return
  fi
  ( "$@" > "$(logfile "$name")" 2>&1 & echo $! > "$(pidfile "$name")" )
  sleep 0.3
  if is_running "$name"; then
    echo "[$name] başlatıldı (PID $(cat "$(pidfile "$name")"), log: $(logfile "$name"))"
  else
    echo "[$name] BAŞLATILAMADI — log: $(logfile "$name")" >&2
  fi
}

stop_service() {
  local name="$1"
  if ! is_running "$name"; then
    echo "[$name] zaten çalışmıyor"
    rm -f "$(pidfile "$name")"
    return
  fi
  local pid
  pid="$(cat "$(pidfile "$name")")"
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.2
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "[$name] SIGTERM'e yanıt vermedi, SIGKILL gönderiliyor"
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$(pidfile "$name")"
  echo "[$name] durduruldu"
}

# Bilinen portlar — `down` sonrası bir wrapper (npm vb.) sinyali iletmeyip
# arkada yetim bir süreç bırakmışsa fark edilsin diye (bkz. frontend/npm
# vakası, 2026-08-17).
port_for_service() {
  case "$1" in
    backend) echo 8000 ;;
    frontend) echo 4200 ;;
    *) echo "" ;;
  esac
}

warn_if_port_busy() {
  local name="$1" port
  port="$(port_for_service "$name")"
  [[ -z "$port" ]] && return
  local listener
  listener="$(ss -ltnp 2>/dev/null | awk -v p=":$port\$" '$4 ~ p')"
  if [[ -n "$listener" ]]; then
    echo "[$name] UYARI: durduruldu ama port $port hâlâ meşgul (yetim bir alt süreç kalmış olabilir):"
    echo "  $listener"
  fi
}

cmd_up() {
  echo "== PostgreSQL + Adminer (docker compose) =="
  (cd "$ROOT_DIR/infra" && docker compose up -d)

  echo "== Backend (uvicorn) =="
  start_service backend bash -c "cd '$BACKEND_DIR' && source .venv/bin/activate && exec uvicorn app.main:app --host 127.0.0.1 --port 8000"

  echo "== Live engine (--watch) =="
  start_service live_engine bash -c "cd '$BACKEND_DIR' && source .venv/bin/activate && exec python -m app.simulation.live_engine --watch"

  echo "== Frontend (ng serve) =="
  # `npm start` KULLANILMIYOR: npm, SIGTERM'i alttaki `ng serve` çocuk sürecine
  # iletmiyor — `down` npm'i öldürse bile `ng serve` yetim kalıp port 4200'de
  # çalışmaya devam ediyordu (gözlemlendi, 2026-08-17). `ng` binary'sini
  # doğrudan `exec` ile çalıştırmak, izlediğimiz PID'in GERÇEK dev server
  # süreci olmasını garantiler.
  start_service frontend bash -c "cd '$FRONTEND_DIR' && exec node_modules/.bin/ng serve"

  echo
  echo "Hazır olunca: http://localhost:4200  (backend: http://127.0.0.1:8000/docs)"
  echo "Durum için:   ./dev.sh status"
  echo "Log için:     ./dev.sh logs [backend|live_engine|frontend]"
}

cmd_down() {
  for name in "${SERVICES[@]}"; do
    stop_service "$name"
    warn_if_port_busy "$name"
  done
  echo "(postgres/adminer durdurulmadı — istersen: cd infra && docker compose down)"
}

cmd_status() {
  for name in "${SERVICES[@]}"; do
    if is_running "$name"; then
      echo "[$name] ÇALIŞIYOR (PID $(cat "$(pidfile "$name")"))"
    else
      echo "[$name] durmuş"
    fi
  done
  echo
  (cd "$ROOT_DIR/infra" && docker compose ps)
}

cmd_logs() {
  local target="${1:-}"
  if [[ -z "$target" ]]; then
    tail -f "$RUN_DIR"/*.log
  else
    tail -f "$(logfile "$target")"
  fi
}

case "${1:-}" in
  up) cmd_up ;;
  down) cmd_down ;;
  status) cmd_status ;;
  logs) shift; cmd_logs "${1:-}" ;;
  *)
    echo "Kullanım: $0 {up|down|status|logs [backend|live_engine|frontend]}" >&2
    exit 1
    ;;
esac
