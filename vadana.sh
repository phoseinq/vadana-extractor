#!/usr/bin/env bash
# vadana — management CLI for the Vadana bot service
SERVICE=vadana-bot
DIR=/opt/vadana-extractor
ENVF="$DIR/bot/.env"
PY="$DIR/venv/bin/python"

run() {
  case "$1" in
    update)
      cd "$DIR" && git pull --ff-only \
        && "$DIR/venv/bin/pip" install -q -r requirements.txt -r bot/requirements.txt \
        && systemctl restart "$SERVICE" && echo "✓ updated + restarted" ;;
    status)  systemctl status "$SERVICE" --no-pager ;;
    logs)    journalctl -u "$SERVICE" -f ;;
    start)   systemctl start "$SERVICE"   && echo "✓ started" ;;
    stop)    systemctl stop "$SERVICE"    && echo "✓ stopped" ;;
    restart) systemctl restart "$SERVICE" && echo "✓ restarted" ;;
    env)     "${EDITOR:-nano}" "$ENVF" && systemctl restart "$SERVICE" && echo "✓ saved + restarted" ;;
    uninstall)
      read -rp "Remove the systemd service? [y/N] " a
      [ "$a" = y ] || { echo "cancelled"; return; }
      systemctl disable --now "$SERVICE" 2>/dev/null
      rm -f "/etc/systemd/system/$SERVICE.service"; systemctl daemon-reload
      read -rp "Also delete cache/, logs/, bot_work/ (file_id store, quotas, scratch)? [y/N] " b
      [ "$b" = y ] && rm -rf "$DIR/cache" "$DIR/logs" "$DIR/bot_work" && echo "✓ data removed"
      echo "✓ uninstalled" ;;
    *) return 1 ;;
  esac
}

menu() {
  while true; do
    st=$(systemctl is-active "$SERVICE" 2>/dev/null)
    printf '\n  \033[1;36mVadana bot\033[0m — %s\n' "$st"
    echo "  1) status    2) logs      3) restart"
    echo "  4) start     5) stop      6) update"
    echo "  7) edit env  8) uninstall 0) exit"
    read -rp "  > " n
    case "$n" in
      1) run status ;; 2) run logs ;; 3) run restart ;;
      4) run start ;; 5) run stop ;; 6) run update ;;
      7) run env ;; 8) run uninstall ;; 0|q|"") exit 0 ;;
    esac
  done
}

[ -z "$1" ] && menu || run "$@" || { echo "unknown command: $1"; exit 1; }
