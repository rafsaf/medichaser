#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PUBLIC_IP="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')"

cat > "${SCRIPT_DIR}/terraform.auto.tfvars" <<EOF
ssh_cidrs = ["${PUBLIC_IP}/32"]
EOF

cd "$SCRIPT_DIR"
terraform init -upgrade
terraform apply -auto-approve

SERVER_IP="$(terraform output -raw public_ip)"

ssh-keygen -R "$SERVER_IP" >/dev/null 2>&1 || true

echo "Waiting for SSH..."

for i in $(seq 1 60); do
  if ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 ubuntu@"$SERVER_IP" "echo ok" >/dev/null 2>&1; then
    echo "SSH ready"
    break
  fi
  sleep 5
done

echo "Uploading .env..."
scp ../../.env ubuntu@"$SERVER_IP":/home/ubuntu/.env || true

echo "Setting up server (all-in-one)..."

ssh ubuntu@"$SERVER_IP" <<'EOF'
set -eux

export DEBIAN_FRONTEND=noninteractive
export PATH="$HOME/.local/bin:$PATH"

# --- system ---
sudo apt-get update
sudo apt-get install -y git python3.11

# --- pip ---
python3.11 -m ensurepip --upgrade || true
python3.11 -m pip install --upgrade pip

# --- repo ---
rm -rf /home/ubuntu/medichaser
git clone https://github.com/rafsaf/medichaser.git /home/ubuntu/medichaser

cd /home/ubuntu/medichaser

# --- env ---
if [ -f /home/ubuntu/.env ]; then
  cp /home/ubuntu/.env /home/ubuntu/medichaser/.env
fi

# --- deps ---
python3.11 -m pip install --user \
  argcomplete \
  fake-useragent \
  filelock \
  lxml \
  notifiers \
  python-dotenv \
  requests \
  rich \
  tenacity \
  xmpppy

EOF

CMD="python3.11 /home/ubuntu/medichaser/medichaser.py find-appointment -i 15 -n pushover -t \"Medicover\" -r 202 -s 3"

echo "$CMD" | pbcopy || true

echo
echo "========================================"
echo "🚀 READY — opening SSH..."
echo "========================================"
echo
echo "✅ Command copied to clipboard"
echo
echo "$CMD"
echo

exec ssh -o StrictHostKeyChecking=accept-new ubuntu@"$SERVER_IP"