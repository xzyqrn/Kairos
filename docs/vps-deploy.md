# VPS Deployment

This guide assumes a fresh Ubuntu or Debian VPS and deploys Kairos as a
`systemd` service.

## What this sets up

- Python 3 + `venv`
- App directory at `/opt/kairos`
- Dedicated Linux user `kairos`
- Virtual environment at `/opt/kairos/.venv`
- `systemd` service named `kairos`

## 1. Connect to the VPS

```bash
ssh root@YOUR_SERVER_IP
```

## 2. Clone the repo on the VPS

```bash
apt-get update
apt-get install -y git
git clone YOUR_REPO_URL /root/kairos-src
cd /root/kairos-src
```

If the repo is private, use SSH or a GitHub token-enabled clone URL.

## 3. Run the bootstrap script

```bash
bash scripts/bootstrap_vps_ubuntu.sh /opt/kairos kairos kairos
```

That script will:

- install OS packages
- sync the repo into `/opt/kairos`
- create a Python virtual environment
- install Python dependencies
- install `/etc/systemd/system/kairos.service`

## 4. Configure the bot

Edit the environment file:

```bash
nano /opt/kairos/.env
```

Required:

- `DISCORD_TOKEN`

Optional:

- `BIBLE_API_KEY`
- `BIBLE_ID`
- `DAILY_VERSE_CHANNEL`

AI provider API keys are configured later inside Discord with `/ai_setup`.

## 5. Start the bot

```bash
systemctl start kairos
systemctl status kairos --no-pager
```

If the service starts successfully, enable it on boot:

```bash
systemctl enable kairos
```

## 6. View logs

```bash
journalctl -u kairos -f
```

App logs are also written under:

```bash
/opt/kairos/logs
```

## 7. Update the bot later

Pull the latest code into your source checkout, then rerun the bootstrap script:

```bash
cd /root/kairos-src
git pull
bash scripts/bootstrap_vps_ubuntu.sh /opt/kairos kairos kairos
systemctl restart kairos
```

## Common checks

If the bot does not come online:

- verify `DISCORD_TOKEN` in `/opt/kairos/.env`
- check `journalctl -u kairos -n 100 --no-pager`
- verify the bot has `MESSAGE CONTENT INTENT` enabled in the Discord Developer Portal
- verify the bot was invited with `bot` and `applications.commands` scopes

## Hardening

After the bot is running, harden the VPS using:

```bash
cd /root/kairos-src
bash scripts/harden_vps_ubuntu.sh deploy 22 /opt/kairos
```

Read the full checklist in [docs/vps-hardening.md](./vps-hardening.md).
