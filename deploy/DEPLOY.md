# Leccy — Oracle Cloud Deployment Guide

Deploy the Leccy FastAPI backend on Oracle Cloud Always Free (no cost, no expiry).

**Requirements**: An Oracle Cloud account, a domain name, a GitHub account with the repo pushed.

---

## Step 1 — Oracle Cloud account

1. Go to [cloud.oracle.com](https://cloud.oracle.com) and click **Sign Up**.
2. A credit card is required for identity verification — you will NOT be charged on Always Free.
3. Choose **US East (Ashburn)** or your nearest region. Always Free resources are region-locked.

---

## Step 2 — Provision the VM

1. In the Oracle Console: **Compute > Instances > Create Instance**
2. Name: `leccy-api`
3. Image: **Canonical Ubuntu 22.04** (click "Change Image" > Platform Images)
4. Shape: **VM.Standard.E2.1.Micro** (Always Free AMD shape — 1 OCPU, 1 GB RAM)
5. Networking: accept defaults; tick **Assign a public IPv4 address**
6. SSH keys: paste the contents of `~/.ssh/id_rsa.pub` (generate with `ssh-keygen` if needed)
7. Boot volume: keep default 50 GB
8. Click **Create** and wait ~2 minutes

Note the **Public IP address** from the instance details page.

---

## Step 3 — Block Volume (recommended)

Stores the DuckDB file separately from the boot volume so it survives OS reinstalls.

1. **Storage > Block Volumes > Create Block Volume**
   - Name: `leccy-data`, Size: 50 GB, same Availability Domain as your VM
2. Click the new volume > **Attached Instances > Attach**
   - Attachment type: Paravirtualized, Device path: `/dev/oracleoci/oraclevdb`
3. SSH into the VM and mount:

```bash
ssh ubuntu@<PUBLIC_IP>
sudo mkfs.ext4 /dev/sdb
sudo mkdir -p /data
sudo mount /dev/sdb /data
echo '/dev/sdb /data ext4 defaults,_netdev 0 2' | sudo tee -a /etc/fstab
sudo chown ubuntu:ubuntu /data
```

---

## Step 4 — Clone and install the app

```bash
ssh ubuntu@<PUBLIC_IP>

# Install system packages
sudo apt update && sudo apt install -y python3-pip git nginx certbot python3-certbot-nginx rclone

# Clone the repo
git clone https://github.com/<your-username>/UKEngergy.git /app
cd /app

# Install Python dependencies
pip3 install -r requirements.txt --break-system-packages

# Create the .env file (never commit this file)
cat > /app/.env <<'EOF'
ENERGY_DB_PATH=/data/energy.duckdb
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@gmail.com
SMTP_PASS=your-app-password
EOF
chmod 600 /app/.env

# Run the data pipeline once to populate the database
cd /app
python3 ingest/fetch_all.py
~/.local/bin/dbt run --quiet

# Verify the database was created
ls -lh /data/energy.duckdb
```

---

## Step 5 — systemd service

```bash
# Copy the service file
sudo cp /app/deploy/energy.service /etc/systemd/system/energy.service

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable energy
sudo systemctl start energy

# Confirm running
sudo systemctl status energy
```

Expected output: `Active: active (running)`.

Test it works locally:
```bash
curl http://127.0.0.1:8000/api/now
```

---

## Step 6 — nginx reverse proxy

```bash
# Replace YOUR_DOMAIN_HERE with your actual domain before copying
sed 's/YOUR_DOMAIN_HERE/yourdomain.com/g' /app/deploy/nginx.conf \
  | sudo tee /etc/nginx/sites-available/leccy

sudo ln -s /etc/nginx/sites-available/leccy /etc/nginx/sites-enabled/

# Remove the default site to avoid conflicts
sudo rm -f /etc/nginx/sites-enabled/default

sudo nginx -t
sudo systemctl reload nginx
```

Test HTTP before adding HTTPS:
```bash
curl http://yourdomain.com/api/now
```

---

## Step 7 — HTTPS with Certbot

```bash
sudo certbot --nginx -d yourdomain.com
```

Follow the prompts. Certbot auto-configures nginx and schedules automatic renewal.

Verify HTTPS:
```bash
curl https://yourdomain.com/api/now
```

---

## Step 8 — Oracle network security list (CRITICAL — easy to forget)

Oracle has TWO firewall layers. Both must allow ports 80 and 443.

**Layer 1 — OS firewall:**
```bash
sudo ufw allow 22
sudo ufw allow 80
sudo ufw allow 443
sudo ufw deny 8000
sudo ufw enable
```

**Layer 2 — Oracle VCN Security List (in the console):**
1. **Networking > Virtual Cloud Networks > [your VCN] > Security Lists > Default Security List**
2. Click **Add Ingress Rules** and add:
   - Source CIDR: `0.0.0.0/0`, Protocol: TCP, Destination Port: `80`
   - Source CIDR: `0.0.0.0/0`, Protocol: TCP, Destination Port: `443`
3. Click **Add Ingress Rules** to save.

Do NOT add port 8000 — uvicorn should only be reachable from localhost.

---

## Step 9 — Cron for the data pipeline

```bash
crontab -e
```

Copy the contents of `/app/deploy/crontab.txt` into the crontab and save.

Verify the pipeline runs within 30 minutes:
```bash
tail -f /data/pipeline.log
```

---

## Step 10 — Uptime monitoring (free, takes 5 minutes)

Oracle Always Free VMs can be silently reclaimed if Oracle deems them "idle". Without monitoring you won't know until users complain.

1. Go to [uptimerobot.com](https://uptimerobot.com) — create a free account
2. **Add New Monitor**: Type = HTTP(S), URL = `https://yourdomain.com/api/now`, Interval = 5 minutes
3. Add an alert contact (email) — you get an email within 5 minutes of downtime
4. Save the public status page URL

---

## Step 11 — DuckDB backup to Backblaze B2

Protects against total data loss if the block volume is lost.

1. Create a free [Backblaze B2](https://www.backblaze.com/b2/cloud-storage.html) account (10 GB free)
2. Create a bucket named `leccy-backup` with private access
3. Generate an Application Key with read/write access to `leccy-backup`
4. Configure rclone on the VM:

```bash
rclone config
# Choose: n (new remote), name: b2, type: b2
# Enter your Account ID and Application Key when prompted
# Leave encryption off for now
```

5. Test the backup:
```bash
rclone copy /data/energy.duckdb b2:leccy-backup/energy-test.duckdb
rclone ls b2:leccy-backup
```

The weekly backup cron (Sunday 02:00) is already in `deploy/crontab.txt`.

---

## Step 12 — Domain name

Point your domain's A record to the VM's public IP address. TTL 300 seconds is fine for initial setup.

If you don't have a domain, [afraid.org](https://afraid.org) provides free subdomains. HTTPS via Certbot requires a real domain — it will not work with a raw IP address.

---

## Verification checklist

Run these from a phone on mobile data (not home WiFi):

```bash
curl https://yourdomain.com/api/now          # live JSON with price and carbon
curl https://yourdomain.com/api/alerts/health # {"last_run":...}
curl http://<PUBLIC_IP>:8000/api/now          # should time out (port 8000 blocked)
```

Also verify:
- `sudo systemctl status energy` shows `active (running)`
- `/data/pipeline.log` has entries every 30 minutes
- UptimeRobot dashboard shows your monitor as UP

---

## Updating the app

```bash
ssh ubuntu@<PUBLIC_IP>
cd /app
git pull
pip3 install -r requirements.txt --break-system-packages
sudo systemctl restart energy
sudo systemctl status energy
```
