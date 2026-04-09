#!/usr/bin/env bash
# Run this ON the GCP VM (Ubuntu 22.04+ / Debian 12+).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Installing Docker..."
if ! command -v docker &>/dev/null; then
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl gnupg
  sudo install -m 0755 -d /etc/apt/keyrings

  # Detect distro: debian or ubuntu
  . /etc/os-release
  DISTRO="${ID}"  # "debian" or "ubuntu"
  CODENAME="${VERSION_CODENAME}"
  echo "    Detected OS: ${DISTRO} ${CODENAME}"

  curl -fsSL "https://download.docker.com/linux/${DISTRO}/gpg" \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/${DISTRO} ${CODENAME} stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin
  sudo usermod -aG docker "$USER"
  echo "    Docker installed. You may need to log out/in for group membership."
else
  echo "    Docker already installed: $(docker --version)"
fi

echo "==> Installing gVisor (runsc)..."
if ! command -v runsc &>/dev/null; then
  curl -fsSL https://gvisor.dev/archive.key | sudo gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
  echo "deb [signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" | \
    sudo tee /etc/apt/sources.list.d/gvisor.list
  sudo apt-get update && sudo apt-get install -y runsc
else
  echo "    runsc already installed: $(runsc --version)"
fi

echo "==> Registering runsc with Docker..."
sudo runsc install
sudo systemctl restart docker

echo "==> Verifying gVisor runtime..."
if docker info 2>/dev/null | grep -q runsc; then
  echo "    runsc runtime registered OK"
else
  echo "    WARNING: runsc not showing in docker info. Check /etc/docker/daemon.json"
fi

echo "==> Installing uv + opensandbox-server..."
if ! command -v uv &>/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
# Only install the server component globally; the client SDKs are not needed here.
uv pip install --system opensandbox-server

echo "==> Building custom sandbox base image..."
docker build -t opensandbox-base:latest -f images/Dockerfile.base .

echo "==> Updating .env.example to use the custom image..."
sed -i.bak 's|SANDBOX_IMAGE=.*|SANDBOX_IMAGE=opensandbox-base:latest|' env.example
rm -f env.example.bak

echo "==> Pulling execd + egress images..."
docker pull opensandbox/execd:v1.0.6
docker pull opensandbox/egress:v1.0.1

echo ""
echo "Done. Next steps:"
echo "  1. Log out & back in if you just added yourself to the docker group"
echo "  2. Edit .env (set SANDBOX_API_KEY)"
echo "  3. Run: ./scripts/start-server.sh gcp"