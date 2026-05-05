#!/usr/bin/env bash
set -euo pipefail

cd terraform/lightsail
SERVER_IP="$(terraform output -raw public_ip)"

ssh ubuntu@"$SERVER_IP"