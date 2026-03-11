# VPS Hardening

This guide assumes Ubuntu or Debian and is designed to avoid the most common
failure mode: locking yourself out of SSH.

Ubuntu’s current server security guidance recommends least privilege, using a
firewall with `ufw`, using OpenSSH for secure remote access, and enabling
automatic updates. See:

- [Ubuntu security suggestions](https://ubuntu.com/server/docs/explanation/security/security_suggestions/)
- [Ubuntu firewall guide](https://ubuntu.com/server/docs/how-to/security/firewalls/)
- [Ubuntu automatic updates](https://ubuntu.com/server/docs/how-to/software/automatic-updates/)
- [Ubuntu OpenSSH guide](https://ubuntu.com/server/docs/how-to/security/openssh-server/)
- [Fail2Ban](https://github.com/fail2ban/fail2ban)

## Safe order

1. Create a non-root admin user.
2. Add your SSH public key to that user.
3. Confirm you can log in as that user.
4. Only then disable SSH password authentication and root login.

## 1. Create a non-root admin user

If your VPS currently only has `root`, create an admin user first:

```bash
adduser deploy
usermod -aG sudo deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
cp -a /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys
```

Open a second terminal and verify login works:

```bash
ssh deploy@YOUR_SERVER_IP
sudo -v
```

Do not continue until that succeeds.

## 2. Run the hardening script

From the repo checkout on the VPS:

```bash
cd /root/kairos-src
bash scripts/harden_vps_ubuntu.sh deploy 22 /opt/kairos
```

Arguments:

- `deploy`: the non-root SSH admin user with a working key
- `22`: SSH port
- `/opt/kairos`: app directory, used to tighten `.env` permissions

If you want a non-default SSH port, replace `22` with your chosen port.

## 3. What the script changes

- installs and enables `ufw`
- sets default deny for inbound traffic
- allows only the SSH port
- installs and enables `fail2ban` for SSH
- enables unattended security updates
- disables SSH password login
- disables direct root SSH login

## 4. Verify before closing your current session

Open a second SSH session first:

```bash
ssh -p 22 deploy@YOUR_SERVER_IP
```

Then check:

```bash
ufw status verbose
fail2ban-client status sshd
systemctl status ssh --no-pager
```

## 5. Recommended ongoing practice

- keep only SSH open in the firewall unless you deliberately expose another service
- use one SSH key per admin
- remove unused users and old keys
- review `journalctl -u ssh -n 100 --no-pager` after SSH config changes
- review `journalctl -u kairos -n 100 --no-pager` after app deploys
- update the VPS regularly even with unattended upgrades enabled

## Notes for this bot

This Discord bot does not need Nginx, a reverse proxy, or public inbound app
ports. SSH is the only port you typically need open on the VPS.
