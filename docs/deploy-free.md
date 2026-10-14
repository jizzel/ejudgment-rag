# Free deployment for testing: Oracle Cloud Always Free, Cloudflare Tunnel

Two ways to put the research service in front of a few invited testers without paying for hosting:

- **A. Oracle Cloud Always Free:** a small Arm server that stays up when your laptop is off. Search works well. Answers need a choice, because the default local answer model doesn't fit in the free memory (see A.6).
- **B. Your own Mac plus Cloudflare Tunnel:** the stack you already run locally, reachable at a public HTTPS address. It keeps local answers on the Mac's GPU but is only up while the Mac is.

Both build on `docs/operations.md` (first run, accounts, backups). Read that first.

The rules stay the same wherever it runs:
- Accounts are invite-only.
- The deployment is **non-commercial** and every page credits GhaLII (CC BY-NC 4.0, see `AGENTS.md`).
- Testers' questions go to whichever answer provider you configure; OpenAI is a third party.

> Free-tier terms change. The figures below were checked on 2026-10-12 against Oracle's [Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) page and Cloudflare's [tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/create-remote-tunnel/) and [Quick Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/) docs. Check them again before you sign up.

## What the service needs

| | Need | Oracle Always Free gives |
|---|---|---|
| Memory | about 6 GB for the containers: Postgres 1 GB buffer cache, plus the embedding, reranker and answer-checking models on CPU | 12 GB (Ampere A1: 2 OCPUs and 12 GB in all) |
| Disk | images 1.9 GB, database 1.8 GB, models 0.93 GB, backups 0.5 GB each | 200 GB of boot and block volume |
| CPU | search 1–3 s on CPU (measured in Docker on an Apple M2 Pro) | 2 Arm cores; expect slower than that |
| Local answer model | `gemma4:latest` is 9.6 GB | not enough memory beside the stack |
| Architecture | linux/arm64 images: the stack already runs on them (Docker on Apple Silicon builds arm64) | Arm (aarch64) |

## Choosing how people reach it

| Access | Domain needed | Open ports | Answers stream | Notes |
|---|---|---|---|---|
| Cloudflare Tunnel, named | yes, on Cloudflare (free plan; the domain itself costs money) | none | yes | Recommended. Works for A and B. |
| Caddy with its own HTTPS | yes, any DNS | 80 and 443 | yes | The TLS checklist in `docs/operations.md`. |
| SSH port forward | no | 22 only | yes | Only for you; nobody else can reach it. |
| Cloudflare Quick Tunnel | no (random `trycloudflare.com` name) | none | **no** | Server-sent events aren't supported, so Ask can't show answers. The name also changes on every start and there's no uptime guarantee. Use it only for a quick search demo. |

## A. Oracle Cloud Always Free

### A.1 Account and server
1. Sign up at oracle.com/cloud/free. A card is needed for verification.
   - Your **home region** is fixed for good, and Always Free resources live only there. Pick one near your testers.
2. Create the server: **Compute → Instances → Create instance**.
   - **Image:** Canonical Ubuntu 24.04, the aarch64 build.
   - **Shape:** Ampere `VM.Standard.A1.Flex`, 2 OCPUs and 12 GB of memory.
   - **Networking:** a new virtual cloud network with a public subnet, and a public IPv4 address.
   - **SSH key:** upload your public key. There is no password login.
   - **Boot volume:** about 100 GB. The free allowance is 200 GB of boot and block storage in all.
3. If creation fails with **"Out of host capacity"**, there is no free Arm capacity in that availability domain at the moment. Try another availability domain or try later.
   - Upgrading the account to Pay As You Go usually finds capacity, and Always Free resources stay free after the upgrade.
   - After an upgrade, anything beyond the free limits is billed. Set a budget alert first (**Billing & Cost Management → Budgets**).
4. **Idle reclamation:** Oracle may reclaim an Always Free instance it considers idle. On A1, idle means that over 7 days, all three of these stay under 20%: CPU (95th percentile), network and memory.
   - The running stack keeps more than 20% of the 12 GB in use, so it shouldn't count as idle.
   - Keep the containers running, and keep backups off the machine anyway.

### A.2 Prepare the machine
```bash
ssh ubuntu@<public-ip>

# Swap: a safety margin for builds and model loading.
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Docker Engine and Compose v2 from Docker's own repository (docs.docker.com/engine/install/ubuntu).
sudo apt-get update && sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker ubuntu && exit     # log in again so the group applies
```

**Firewall.** Oracle's Ubuntu images ship host `iptables` rules that allow SSH and reject other incoming traffic. The cloud network's security list also allows only port 22. With a tunnel or an SSH port forward, leave both as they are. Check the host rules with `sudo iptables -L INPUT -n --line-numbers`.

### A.3 Code, models and the corpus
The corpus export (`output/`) and the model weights aren't in Git. Copy them from the machine that has them, here your Mac.

1. **Code:**
   ```bash
   git clone <your repository URL> ~/ejudgment && cd ~/ejudgment
   ```
   For a private repository, authenticate with a read-only deploy key or `gh auth login`.
2. **Models** (about 930 MB). Copy your Hugging Face cache. The files are the same on every architecture, and `rsync -a` keeps the cache's symlinks:
   ```bash
   # on the Mac
   rsync -a ~/.cache/huggingface/ ubuntu@<public-ip>:.cache/huggingface/
   ```
   Or fetch them on the server through the only command that downloads weights, run once in the image (after A.5 has built it):
   ```bash
   mkdir -p ~/.cache/huggingface && sudo chown 10001 ~/.cache/huggingface
   docker run --rm -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 \
     -v ~/.cache/huggingface:/models/huggingface ejudgment-python:local \
     python -m ejudgment.worker.models fetch-models
   ```
3. **Corpus.** Restoring a backup is far quicker than rebuilding on 2 cores, where embedding alone would take many hours.
   ```bash
   # on the Mac, in the repository
   scripts/backup.sh
   scp backups/ejudgment-<timestamp>.dump backups/ejudgment-<timestamp>.dump.sha256 ubuntu@<public-ip>:ejudgment/backups/
   ```
   The dump holds account and audit tables as well as the corpus. Treat it as confidential, and delete test accounts you don't want on the server: `worker.users list`, then `disable`.

### A.4 Configure `.env`
```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"    # for AUTH_HASH_SECRET
```
- **Always:**
  - `POSTGRES_PASSWORD`: long and random.
  - `AUTH_HASH_SECRET`: long and random.
  - `HF_CACHE_DIR=/home/ubuntu/.cache/huggingface`.
- **With Cloudflare Tunnel:** `CLOUDFLARE_TUNNEL_TOKEN=<token>` and `TRUSTED_PROXIES=private_ranges` (see "Cloudflare Tunnel" below). Keep `SITE_ADDRESS=:80` and the default `127.0.0.1` binding, and leave `UI_INSECURE_COOKIES` unset.
- **With an SSH port forward only:** `UI_INSECURE_COOKIES=1`. The site is plain http on the server's loopback.
- **Answers:** see A.6.

### A.5 Start
Follow path **a** ("From a backup") in `docs/operations.md`, in this order:
```bash
docker compose up -d postgres
scripts/restore.sh backups/ejudgment-<timestamp>.dump ejudgment --into-empty
docker compose up -d --build                      # add --profile tunnel when using Cloudflare Tunnel
docker compose run --rm worker python -m ejudgment.worker.users create \
  --email you@example.org --name "Your Name" --role admin --generate
```
Building the images on 2 Arm cores takes a while; most of it is the Python dependencies. To skip the build, build on the Mac (its images are already arm64) and copy them across:
```bash
# on the Mac
docker compose build
docker save ejudgment-python:local ejudgment-ui:local | gzip | ssh ubuntu@<public-ip> 'gunzip | docker load'
```
Then start on the server without `--build`. The copy must match the code you check out on the server.

`docker compose ps` should show postgres, api, ui and caddy as healthy (and cloudflared running).

### A.6 Answers: pick one
The default model, `gemma4:latest` at 9.6 GB, doesn't fit beside the stack in 12 GB. Neither do the other models evaluated so far (mistral-nemo 7.1 GB, ministral-3 6.0 GB).

1. **Search only.** Configure nothing. Search and passages work; Ask shows "The answer model is not available".
2. **OpenAI** (opt-in, paid, and questions leave the server):
   - **Settings:** `LLM_PROVIDER=openai`, `OPENAI_ENABLED=true` and `OPENAI_API_KEY` in `.env`, with the model priced in `config/models.yaml`.
   - **Cost:** the pilot cost about $0.0003 per answer.
   - **Daily cap:** the app's soft stop counts one UTC day of `/v1/chat` calls. By default that is 20 calls or $1.00 a day across all users (`OPENAI_MAX_CALLS_PER_RUN`, `OPENAI_TEST_BUDGET_USD`); after that, Ask says the budget is used up. Raise the limits deliberately, and set a project budget in the OpenAI dashboard as well.
   - **Testers:** tell them their questions go to OpenAI (`AGENTS.md`, rule 5).
3. **A smaller local model** on the server's CPU:
   - **Performance:** expect answers to take minutes on 2 cores.
   - **Quality:** a model nobody has evaluated may abstain more or keep fewer verified claims. Run `docker compose run --rm worker python -m ejudgment.worker.evaluate_answers --model <model>` and compare with the runs in `AGENTS.md` before you rely on it.
   - **Setup:** install Ollama with the script from ollama.com, then `ollama pull <model>` and set `OLLAMA_CHAT_MODEL=<model>`.
   - **Network:** the containers reach Ollama at `host.docker.internal` (the Docker bridge). By default Ollama listens on 127.0.0.1 only, and Oracle's reject rules also drop bridge traffic. Open it to the containers only:
     ```bash
     sudo systemctl edit ollama          # add:  [Service]  Environment="OLLAMA_HOST=0.0.0.0:11434"
     sudo systemctl restart ollama
     sudo iptables -I INPUT -s 172.16.0.0/12 -p tcp --dport 11434 -j ACCEPT   # Docker networks only
     sudo apt-get install -y iptables-persistent && sudo netfilter-persistent save
     ```
     Never open 11434 in the security list: Ollama has no authentication.

### A.7 Keep it running
- Add the cron jobs from `docs/operations.md` (backups, retention, monthly restore drill), with paths under `/home/ubuntu/ejudgment`.
- Copy backups off the server, encrypted. A backup on the same disk doesn't survive that disk.
- Ubuntu installs security updates automatically (unattended-upgrades). Reboot now and then: `docker compose` services restart on their own (`restart: unless-stopped`).
- To update: `git pull`, `scripts/backup.sh`, then `docker compose up -d --build`.

### A.8 Without a tunnel
- **SSH port forward**, just for you:
  - Run `ssh -N -L 8080:127.0.0.1:8080 ubuntu@<public-ip>` and open `http://127.0.0.1:8080`.
  - Needs `UI_INSECURE_COOKIES=1`.
- **Caddy's own HTTPS:**
  - Follow the TLS checklist in `docs/operations.md`.
  - Open 80 and 443 in two places:
    - the subnet's security list (**Networking → Virtual cloud networks**, your network, then the subnet's security list: ingress rules for TCP 80 and 443 from `0.0.0.0/0`)
    - the host: `sudo iptables -I INPUT -p tcp -m multiport --dports 80,443 -j ACCEPT && sudo netfilter-persistent save`
  - Leave `TRUSTED_PROXIES` unset.

## B. Your Mac plus Cloudflare Tunnel
1. Run the stack as in `docs/operations.md`, with Ollama on the Mac. Answers keep using its GPU.
2. Set up a named tunnel (below) with `CLOUDFLARE_TUNNEL_TOKEN` and `TRUSTED_PROXIES=private_ranges` in `.env`, then run `docker compose --profile tunnel up -d`.
3. Remove `UI_INSECURE_COOKIES` from `.env`. Session cookies are then `Secure`, so sign in through the tunnel's `https://` address, also yourself. Signing in at `http://127.0.0.1:8080` won't stick.
4. Keep the Mac awake while testers use it: run `caffeinate -s`, or change the sleep settings for power-adapter use.

## Cloudflare Tunnel (named, for A or B)
cloudflared opens an outbound connection to Cloudflare. Cloudflare serves HTTPS on your hostname and passes requests through the tunnel to Caddy. No port is opened on the machine.

1. **Domain.** Add your domain to Cloudflare (the free plan is enough) and switch its nameservers to Cloudflare's. A domain is required before an application can be published through a tunnel.
2. **Tunnel.** In the Cloudflare dashboard go to **Networking → Tunnels**, select **Create a tunnel** and name it.
   - Copy the **token** from the install command it shows: the long value after `--token`. Don't run that command; the Compose service runs cloudflared instead.
   - The token grants the tunnel. Keep it in `.env` only, which is gitignored.
3. **Route.** Open the tunnel. On **Routes**, choose **Add route → Published application** and fill in:
   - a subdomain and your domain, e.g. `research.example.org`
   - **Service URL** `http://caddy:80`. cloudflared runs inside the Compose network, so it reaches Caddy by service name.
4. **`.env`:**
   ```bash
   CLOUDFLARE_TUNNEL_TOKEN=<token>
   TRUSTED_PROXIES=private_ranges
   # SITE_ADDRESS stays :80, HTTP_BIND stays 127.0.0.1, UI_INSECURE_COOKIES unset
   ```
   - **Why `TRUSTED_PROXIES`:** TLS ends at Cloudflare, so cloudflared reaches Caddy over plain http.
   - **Without it:** Caddy would tell the UI the request came in as `http`, and the Ask page's same-origin check would refuse every question with "This request did not come from this site".
   - **What it does:** trusting the private address ranges makes Caddy keep cloudflared's `X-Forwarded-Proto: https`.
   - **Never set it while Caddy is published to the internet** (`HTTP_BIND=0.0.0.0`).
5. **Start:** `docker compose --profile tunnel up -d`. Check `docker compose logs cloudflared` for registered tunnel connections.
6. **Check** at `https://research.example.org/login`:
   - Sign in and run a search.
   - Ask a question: the stages (searching, drafting, checking) should appear as they happen, not all at once at the end.
   - Cancel during drafting should leave a `cancelled` row in `llm_usage_ledger`.
7. **Optional extra gate.** Cloudflare Access (Zero Trust, free for small teams) can require an email one-time code before anyone reaches the sign-in page.
8. **Cloudflare settings for this site:**
   - **HSTS on.** Under **SSL/TLS → Edge Certificates**, turn on **Always Use HTTPS** and **HSTS**. Caddy adds HSTS only when it handles HTTPS itself, which it doesn't behind the tunnel.
   - **Web Analytics (optional).** Caddy's Content-Security-Policy allows Cloudflare's beacon: its script from `static.cloudflareinsights.com`, its reports to `cloudflareinsights.com`. It uses no cookies and counts page views and load times. Page URLs carry the search text (`/?q=…`), but Cloudflare already sees every request as the proxy, so the beacon exposes nothing new. Turn it off for this hostname if you'd rather not have it.

**Limits to know:**
- Cloudflare ends a proxied request that sends nothing for about 100 seconds (error 524). The answer stream sends events while it works, but a very slow model can stay silent through the whole drafting stage. If testers see "The connection was interrupted", answers are taking too long for the proxy.
- **Dropped connections.** A short network drop on the host ends every connection to Cloudflare at once (`no recent network activity` in the cloudflared log). A stream in progress then breaks, and the API records that answer as cancelled; cloudflared reconnects within seconds. Seen once on a Mac over Wi-Fi (2026-10-14). If it keeps happening, the UDP-based QUIC transport is the suspect: add `--protocol http2` to the cloudflared command in `docker-compose.yml` to use TCP instead.
- `scripts/check_proxy_stream.sh` checks Caddy's side, including `TRUSTED_PROXIES=private_ranges scripts/check_proxy_stream.sh` for this setting. It cannot check Cloudflare's own network.

## Quick Tunnel (search demo only)
```bash
brew install cloudflared                                 # or run the cloudflare/cloudflared image
cloudflared tunnel --url http://localhost:8080           # prints a https://<random>.trycloudflare.com address
```
This needs `TRUSTED_PROXIES=private_ranges` and no `UI_INSECURE_COOKIES`, as with a named tunnel.

Limits:
- Server-sent events aren't supported, so Ask can't stream answers.
- At most 200 requests in flight.
- The address changes on every start, and there's no uptime guarantee.

Stop it when the demo ends: anyone with the address can reach the sign-in page.
