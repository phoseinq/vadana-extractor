#!/usr/bin/env bash
# Installer for the Vadana bot (run as root on the server abroad).
set -e
DIR=/opt/vadana-extractor

echo "==> system packages"
apt-get update -y
apt-get install -y python3 python3-venv python3-pip ffmpeg git

# fetch the code if it isn't here yet, so `curl ... | bash` works as a one-liner
if [ ! -f "$DIR/requirements.txt" ]; then
  git clone https://github.com/phoseinq/vadana-extractor.git "$DIR"
fi
cd "$DIR"

echo "==> virtualenv + dependencies"
python3 -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -U pip
"$DIR/venv/bin/pip" install -r "$DIR/requirements.txt" -r "$DIR/bot/requirements.txt"

echo "==> config"
[ -f "$DIR/bot/.env" ] || cp "$DIR/bot/.env.example" "$DIR/bot/.env"

echo "==> 'vadana' management command"
install -m 755 "$DIR/vadana.sh" /usr/local/bin/vadana

echo "==> systemd service"
cp "$DIR/bot/systemd/vadana-bot.service" /etc/systemd/system/
systemctl daemon-reload

cat <<'DONE'

✓ Installed.  Next:
    vadana env                       # fill in BOT_TOKEN, IRAN_PROXY, ADMINS, ...
    systemctl enable --now vadana-bot
    vadana                           # management menu
DONE
