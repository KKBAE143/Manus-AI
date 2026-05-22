# Deploying to Oracle Cloud Always Free

End-to-end runbook. Total time: ~45 minutes one-time, then ~1 minute per future
update.

---

## What you (the human) need to do

You'll do four things. I've broken them down precisely.

### 1. Create an Oracle Cloud account (10 min, one-time)

1. Go to https://signup.cloud.oracle.com/
2. Sign up. They'll ask for:
   - Email
   - Phone number (must verify)
   - **Credit card** (for identity verification only - they will not charge it
     for Always Free resources). Use any card you have.
   - Home address
3. Pick the region **closest to you** (e.g. Mumbai, Singapore, Frankfurt). You
   cannot easily change this later, so choose carefully.
4. After verification (usually instant; sometimes 12-24h), you'll land on the
   Oracle Cloud console.

### 2. Create the Always Free VM (10 min, one-time)

In the Oracle Cloud console:

1. Click **Menu (top-left) -> Compute -> Instances**.
2. Click **Create instance**.
3. Name it `manus-ai` (or anything).
4. Under **Image and shape**:
   - Click **Edit -> Change image** -> pick **Canonical Ubuntu 22.04**
     (this is in the "Always Free Eligible" list).
   - Click **Change shape** -> pick **Ampere -> VM.Standard.A1.Flex** ->
     set 4 OCPUs and 24 GB RAM (it's the entire free quota). If A1.Flex is
     "out of capacity" in your region (common), pick **VM.Standard.E2.1.Micro**
     (1 OCPU, 1 GB RAM) instead - still free, just slower.
5. Under **Networking**, leave defaults. The wizard creates a VCN with a
   public IP automatically.
6. Under **SSH keys**:
   - Pick **Generate a key pair for me**.
   - Click **Save private key** and **Save public key**. Keep the private
     key file safe (e.g. `~/.ssh/oracle.key`). You'll use it to SSH in.
7. Click **Create**.
8. Wait ~1 minute. When status is "RUNNING", note the **Public IP address**
   on the instance details page.

### 3. Open ports 80 and 443 in Oracle's firewall (5 min, one-time)

Oracle blocks everything by default at two layers - the cloud "Security List"
*and* the VM's iptables. You need both.

In the Oracle console:

1. From the instance page, click the **VCN name** (Virtual Cloud Network).
2. Click **Default Security List for vcn-...**.
3. Click **Add Ingress Rule** twice:
   - Rule 1: Source CIDR `0.0.0.0/0`, Destination Port `80`, IP Protocol TCP.
   - Rule 2: Source CIDR `0.0.0.0/0`, Destination Port `443`, IP Protocol TCP.
4. Save.

The VM-side iptables rules are added automatically by `setup-vm.sh` (see step 4).

### 4. Point a domain at the VM (10 min, one-time)

You need a domain name. Two options:

**Option A: You own a domain.** In your DNS provider:
- Create an `A` record: `exam` (or any subdomain) -> the VM public IP.
- Wait 1-5 minutes for DNS to propagate.

**Option B: Use a free DuckDNS subdomain.**
- Sign up at https://www.duckdns.org/ (Google login).
- Create a domain like `your-name-exam.duckdns.org` and point it at the VM IP.

Whatever your final URL is (e.g. `https://exam.example.com` or
`https://your-name-exam.duckdns.org`), write it down - you'll paste it in step 5.

### 5. SSH in and run two commands (3 min, one-time)

From your laptop (Windows: use PowerShell):

```powershell
ssh -i C:\path\to\oracle.key ubuntu@YOUR_VM_IP
```

If SSH refuses with "permission denied", make sure the key has tight perms:
```powershell
icacls C:\path\to\oracle.key /inheritance:r /grant:r "$env:USERNAME:R"
```

Once you're on the VM:

```bash
# Clone YOUR repo (replace with your actual GitHub URL)
git clone https://github.com/YOUR-USER/YOUR-REPO.git manus-ai
cd manus-ai

# Bootstrap Docker, firewall, etc. Run once.
chmod +x deploy/setup-vm.sh deploy/deploy.sh
./deploy/setup-vm.sh

# Log out and back in so the docker group takes effect
exit
```

Reconnect:
```powershell
ssh -i C:\path\to\oracle.key ubuntu@YOUR_VM_IP
cd manus-ai
```

Create the production .env:
```bash
cp .env.production.example .env
nano .env
```
Fill in:
```
DOMAIN=exam.example.com
CORS_ALLOW_ORIGINS=https://exam.example.com
GEMINI_API_KEY=        # leave blank if unused
```
Save (Ctrl+O, Enter, Ctrl+X).

Deploy:
```bash
./deploy/deploy.sh
```

The first build takes ~5 minutes (downloading Node, Python, building the
React bundle, installing PyMuPDF). Subsequent deploys are 30-60 seconds.

When you see `app | INFO: Application startup complete.` open
`https://exam.example.com` in your browser. Caddy will fetch a Let's Encrypt
certificate on first hit - HTTPS works automatically.

---

## Updating the app later

After the initial deploy, every code change is:

1. On your laptop: `git push`
2. SSH into the VM
3. `cd manus-ai && ./deploy/deploy.sh`

That's the whole loop. ~30 seconds.

---

## Troubleshooting

**Browser shows "site can't be reached"**
- DNS not pointing at the right IP. Run `nslookup exam.example.com` from
  your laptop and confirm it shows the VM's public IP.
- Oracle Security List is blocking ports. Re-check step 3.

**Browser shows certificate error**
- Wait 30 seconds and retry. Caddy issues the cert lazily on first request.
- Check Caddy logs: `docker compose logs -f caddy`. If it says "rate limit",
  wait 1 hour or use the staging environment.

**App container restarts in a loop**
- `docker compose logs -f app`
- Most common cause: bad `STORAGE_ROOT` permissions. Fix:
  `sudo chown -R $USER:$USER /var/lib/docker/volumes/manus-ai_storage/_data`

**Oracle wants to reclaim my VM**
- The keepalive container in docker-compose prevents this by hitting the
  health endpoint every 10 minutes and burning a tiny bit of CPU.
- If the email arrives anyway, check `docker compose ps` and confirm
  `keepalive` is Up.

**Out of memory during build (E2.1.Micro = 1 GB)**
- Add a 2 GB swapfile, one-time:
  ```bash
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  ```

---

## Costs

If you stay on Always Free shapes (A1.Flex up to 4 OCPU/24 GB total or two
E2.1.Micro), Oracle bills $0/month forever. They will reclaim the VM if it
sits idle (avg CPU under 10% for 7 days *and* low net + low disk). The
keepalive container in this stack prevents that.

If you accidentally provision a paid shape: delete it within the trial period
and you owe nothing. To be safe, set a $0 budget alert in Oracle's
"Cost Management" console.
