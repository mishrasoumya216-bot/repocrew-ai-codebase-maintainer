# Deploying RepoCrew to AWS EC2 (free tier)

This reuses the repo's existing `Dockerfile` + `docker-compose.yml` as-is —
the instance just runs `docker compose up --build -d`. No code changes are
required for a basic demo-mode deployment.

## Before you start

AWS changed its free-tier terms on 2025-07-15:
- **Accounts created before that date** keep the legacy free tier: 750 hours/
  month of `t2.micro` (or `t3.micro` in some regions) for 12 months from
  account creation, at $0.
- **Accounts created after that date** instead get a one-time $100–200
  credit pool (AWS's own FAQ and Terms pages disagree on whether it expires
  in 6 or 12 months — check which applies to you).

Either way, check **Billing → Free Tier** in the AWS Console after launching
to confirm you're inside your allowance. A single `t3.micro` running this
app costs well under $10/month even outside the free tier.

## Step-by-step (AWS Console)

1. **Sign in** to the [AWS Console](https://console.aws.amazon.com/) and open
   the **EC2** service. Pick a region near you (top-right region switcher).

2. **Launch Instance** → give it a name, e.g. `repocrew-demo`.

3. **Application and OS Images (AMI)**: choose **Ubuntu Server 24.04 LTS**
   (marked "Free tier eligible").

4. **Instance type**: choose `t2.micro` or `t3.micro` — the console marks
   whichever is free-tier eligible in your account/region.

5. **Key pair**: click "Create new key pair", name it (e.g. `repocrew-key`),
   leave defaults (RSA, `.pem`), and download it. Only needed if you want to
   SSH in to check logs — the app itself doesn't need it.

6. **Network settings** → click "Edit":
   - Create a new security group.
   - Rule 1 (pre-filled): SSH, port 22, source **"My IP"** (not Anywhere).
   - Click "Add security group rule": Type **Custom TCP**, port **8000**,
     source **Anywhere (0.0.0.0/0)** — this is the app's port.

7. **Configure storage**: leave the default (8 GiB gp3 is enough; free tier
   covers up to 30 GiB).

8. **Advanced details** (expand at the bottom) → scroll to **User data** →
   paste the full contents of [`user-data.sh`](./user-data.sh) from this
   folder into the box.

9. Click **Launch instance**.

10. Wait 2–4 minutes for the instance to boot and `user-data.sh` to finish
    (installs Docker, clones the repo, builds and starts the containers).
    Open the instance in the EC2 console and copy its **Public IPv4 address**.

11. Visit `http://<PUBLIC_IP>:8000` — you should see the RepoCrew dashboard.

### If it's not up yet

SSH in and watch the bootstrap log:

```bash
chmod 400 repocrew-key.pem
ssh -i repocrew-key.pem ubuntu@<PUBLIC_IP>
sudo tail -f /var/log/cloud-init-output.log
# once that finishes:
cd /opt/repocrew && sudo docker compose ps
sudo docker compose logs -f
```

## Optional: a stable IP

The public IP above changes if the instance stops/restarts. For a fixed
address: EC2 console → **Elastic IPs** → Allocate → Associate with your
instance. An Elastic IP is free only while attached to a *running* instance —
release it if you stop the instance for a while, or it starts billing hourly.

## Optional: live mode / real GitHub PRs

By default the instance runs `RC_MODE=demo` (zero keys, zero external
network access). To enable real Claude agents or real GitHub PRs instead of
PR previews, SSH in and edit the environment block in
`/opt/repocrew/docker-compose.yml` (uncomment and fill in `ANTHROPIC_API_KEY`,
and/or `GITHUB_TOKEN` + `RC_GITHUB_REPO`), then:

```bash
cd /opt/repocrew
sudo docker compose up -d --build
```

Never commit real keys into the repo — `docker-compose.yml` on the instance
is a local edit, not something you push back to GitHub.

## Tear down (avoid any charges)

EC2 console → select the instance → **Instance state → Terminate instance**.
If you allocated an Elastic IP, release it separately (Elastic IPs →
select → Release). If you created a security group just for this, you can
delete it too once the instance is terminated.

## What's isolated here, and what isn't

- `docker-compose.yml` mounts the host's Docker socket into the backend
  container, and the `Dockerfile` installs the Docker CLI needed to use it.
  This means the Tester's sandboxed pytest runs are genuinely isolated
  (`--network none`, 256MB, 0.5 CPU, read-only root) on this deployment path,
  not the unisolated local-subprocess fallback.
- The SQLite database is written to `/app/data/repocrew.db` inside the
  container, which is backed by the named `repocrew-data` Docker volume —
  it survives `docker compose up --build -d` rebuilds and instance reboots,
  but not `docker compose down -v` (which deletes volumes) or instance
  termination.
