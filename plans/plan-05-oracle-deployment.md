# Plan 5: Oracle Cloud Deployment

**Objective**: Deploy the FastAPI backend on Oracle Cloud Always Free so the API is publicly accessible 24/7 at a real domain with HTTPS.
**Requires**: Plan 1 complete (the app must work with Bearer auth before going public).
**Touches**: No application code. Infrastructure only: VM provisioning, nginx, systemd, cron, certbot.

---

## Context

The FastAPI backend runs locally via `python3 dashboard/app.py` or
`uvicorn dashboard.app:app`. The goal is to move it to a permanently free Oracle Cloud
VM and front it with nginx + Let's Encrypt. The mobile app (Phase 6) will connect to
this public URL. All steps are performed manually on the VM — no Terraform, no Docker.

**Cost**: $0 forever. Oracle Cloud Always Free includes 1 AMD VM (1 OCPU, 1GB RAM) and
50GB Block Volume permanently, with no time expiry.

## What to build

### Step 1 — Oracle Cloud account

1. Go to cloud.oracle.com and create an account. A credit card is required for identity
   verification; you will not be charged on the Always Free tier.
2. Choose the **US East (Ashburn)** region (or your nearest Always Free region).
   Always Free resources are region-specific — pick one and stay in it.

### Step 2 — Provision the VM

In the Oracle Cloud console:
1. Compute > Instances > Create Instance
2. Name: `leccy-api`
3. Image: **Canonical Ubuntu 22.04** (select from platform images)
4. Shape: **VM.Standard.E2.1.Micro** — this is the Always Free AMD shape (1 OCPU, 1GB RAM)
5. Networking: Create a new VCN and subnet, or use defaults. Enable "Assign public IPv4".
6. SSH keys: paste your public key (from `~/.ssh/id_rsa.pub` or generate new ones).
7. Boot volume: 50GB is the default; keep it.
8. Click Create.

Note the VM's public IP once provisioned (takes ~2 minutes).

### Step 3 — Block Volume (optional but recommended)

Oracle Always Free includes a 200GB Block Volume allocation. Use 50GB for the database:
1. Storage > Block Volumes > Create Block Volume. Name: `leccy-data`. Size: 50GB.
2. Attach to the VM: Block Volume > Attached Instances > Attach. Use `/dev/oracleoci/oraclevdb`.
3. SSH into the VM and format + mount:
   ```bash
   sudo mkfs.ext4 /dev/sdb
   sudo mkdir -p /data
   sudo mount /dev/sdb /data
   echo '/dev/sdb /data ext4 defaults,_netdev 0 2' | sudo tee -a /etc/fstab
   sudo chown ubuntu:ubuntu /data
   ```

### Step 4 — Clone and configure the app

```bash
ssh ubuntu@<PUBLIC_IP>
sudo apt update && sudo apt install -y python3-pip git nginx certbot python3-certbot-nginx

git clone https://github.com/<your-username>/UKEngergy.git /app
cd /app
pip3 install -r requirements.txt --break-system-packages

# Create .env (NOT committed to git)
cat > /app/.env <<'EOF'
ENERGY_DB_PATH=/data/energy.duckdb
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@gmail.com
SMTP_PASS=your-app-password
EOF
chmod 600 /app/.env
```

Run the ingest once manually to populate the database:
```bash
cd /app
python3 ingest/fetch_all.py
~/.local/bin/dbt run --quiet
```

### Step 5 — systemd service

Create `/etc/systemd/system/energy.service`:

```ini
[Unit]
Description=Leccy Energy API
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/app
EnvironmentFile=/app/.env
ExecStart=/usr/local/bin/uvicorn dashboard.app:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable energy
sudo systemctl start energy
sudo systemctl status energy   # confirm "active (running)"
```

### Step 6 — nginx reverse proxy

Create `/etc/nginx/sites-available/leccy`:

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Authorization $http_authorization;
        proxy_pass_header Authorization;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/leccy /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

Verify HTTP works before adding HTTPS:
```bash
curl http://yourdomain.com/api/now
```

### Step 7 — HTTPS with Certbot

```bash
sudo certbot --nginx -d yourdomain.com
# Follow prompts; certbot auto-configures nginx and schedules renewal
```

Certbot will auto-renew via a systemd timer — no manual intervention needed.

### Step 8 — Cron for the data pipeline

```bash
crontab -e
```

Add:
```
*/30 * * * * cd /app && python3 ingest/fetch_all.py >> /data/pipeline.log 2>&1
*/30 * * * * cd /app && /home/ubuntu/.local/bin/dbt run --quiet >> /data/dbt.log 2>&1
```

(Run ingest and dbt as separate cron lines so a dbt failure doesn't prevent ingest.)

### Step 9 — Oracle network security list (CRITICAL)

Oracle has TWO firewall layers: the VM's OS firewall AND Oracle's VCN Security List.
Both must allow ports 80 and 443:

**OS firewall (iptables/ufw):**
```bash
sudo ufw allow 80
sudo ufw allow 443
sudo ufw allow 22
sudo ufw enable
```

**Oracle VCN Security List** (in the console):
1. Networking > Virtual Cloud Networks > [your VCN] > Security Lists > Default Security List
2. Add Ingress Rules:
   - Source: `0.0.0.0/0`, Protocol: TCP, Port: 80
   - Source: `0.0.0.0/0`, Protocol: TCP, Port: 443
3. Save changes.

### Step 10 — Domain name

Point your domain's A record to the VM's public IP. If you don't have a domain,
use [afraid.org](https://afraid.org) for a free subdomain, or use the public IP
directly (skip certbot — HTTPS won't work without a domain).

### Step 11 — Block direct access to port 8000

Port 8000 (uvicorn) should only be reachable from localhost. Add to Oracle Security
List: do NOT add an ingress rule for port 8000. Confirm the OS firewall also blocks it:

```bash
sudo ufw deny 8000
```

Verify from outside: `curl http://<PUBLIC_IP>:8000/api/now` should time out.

### Step 12 — Uptime monitoring (free)

Oracle VMs on the Always Free tier can be silently reclaimed if Oracle decides the
instance is "idle". Set up a free external monitor so you know immediately if the
API goes down:

1. Go to [uptimerobot.com](https://uptimerobot.com) — create a free account
2. Add a new monitor: HTTP(S), URL `https://yourdomain.com/api/now`, every 5 minutes
3. Add an alert contact (email) — you'll get an email within 5 minutes of downtime
4. Copy the monitor's public status page URL and save it

This is the only way to know the Oracle VM has been reclaimed before your users notice.

### Step 12b — DuckDB file backup

Oracle Always Free VMs can be silently reclaimed for perceived "inactivity." If the VM is
reclaimed and reprovisioned, the block volume is detached but the data survives — however
there is a window of risk. Add a weekly off-VM backup using `rclone` to a free Backblaze B2
bucket (10GB free tier, well within the database size):

```bash
# Install rclone (once)
sudo apt install -y rclone

# Configure B2 bucket (rclone config — follow interactive prompts)
# Name the remote "b2" and bucket "leccy-backup"

# Add to crontab (runs every Sunday at 02:00, before the retention cron)
0 2 * * 0 rclone copy /data/energy.duckdb b2:leccy-backup/energy-$(date +\%Y\%m\%d).duckdb >> /data/backup.log 2>&1
```

Alternatively, use Oracle Object Storage (also Always Free, 10GB):
```bash
oci os object put --bucket-name leccy-backup --file /data/energy.duckdb \
  --name energy-$(date +%Y%m%d).duckdb
```

Keep 4 weekly snapshots — delete older ones in the same cron job:
```bash
0 2 * * 0 rclone copy /data/energy.duckdb b2:leccy-backup/energy-$(date +\%Y\%m\%d).duckdb \
  && rclone delete --min-age 35d b2:leccy-backup >> /data/backup.log 2>&1
```

**This is the only protection against total data loss.** Without it, a reclaimed VM means
all user accounts, savings history, and alert configurations are gone permanently.

### Step 13 — Bronze table data retention cron

DuckDB bronze tables accumulate every 30 minutes indefinitely. Add a weekly cleanup
to prevent disk exhaustion on the 50GB block volume:

```bash
crontab -e
```

Add (runs every Sunday at 03:00):
```
0 3 * * 0 cd /app && python3 -c "
import duckdb, os
con = duckdb.connect(os.getenv('ENERGY_DB_PATH', './energy.duckdb'), read_only=False)
tables = ['main_bronze.raw_prices', 'main_bronze.raw_carbon', 'main_bronze.raw_generation',
          'main_bronze.raw_weather', 'main_bronze.raw_carbon_national']
for t in tables:
    con.execute(f\"DELETE FROM {t} WHERE fetched_at < now() - INTERVAL 90 DAYS\")
con.close()
print('Retention cleanup done')
" >> /data/cleanup.log 2>&1
```

Also add cleanup for the app schema (login attempts accumulate):
```
0 3 * * 0 cd /app && python3 -c "
import duckdb, os
con = duckdb.connect(os.getenv('ENERGY_DB_PATH', './energy.duckdb'), read_only=False)
con.execute(\"DELETE FROM app.login_attempts WHERE attempted_at < now() - INTERVAL 7 DAYS\")
con.execute(\"DELETE FROM app.user_sessions WHERE expires_at < now()\")
con.execute(\"DELETE FROM app.password_resets WHERE expires_at < now()\")
con.execute(\"DELETE FROM app.alert_checker_log WHERE run_at < now() - INTERVAL 30 DAYS\")
con.close()
" >> /data/cleanup.log 2>&1
```

## Verification

From a phone on mobile data (not home WiFi):
```
curl https://yourdomain.com/api/now
```

Should return live JSON with current price and carbon intensity.

---
Done when: `curl https://yourdomain.com/api/now` from a phone on mobile data returns valid JSON, `systemctl status energy` shows "active (running)", and the cron pipeline fires every 30 minutes (check `/data/pipeline.log`).
