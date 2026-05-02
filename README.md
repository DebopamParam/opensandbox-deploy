```powershell
git clone https://github.com/DebopamParam/opensandbox-deploy.git
cd opensandbox-deploy
cp .env.example .env
bash scripts/setup-gcp.sh
bash scripts/start-server.sh gcp
```
