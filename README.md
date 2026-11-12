# Certbot DNS-01 with mijn.host

Use Let's Encrypt and the `certbot-dns-multi` plugin to issue certificates through the mijn.host DNS API. The same renewal timer can manage public websites, internal websites, and services such as Postfix and Dovecot. DNS-01 only needs a public challenge TXT record. An internal service can keep its A and AAAA records in local DNS.

These examples assume Ubuntu, root access for Certbot, and mijn.host as the authoritative DNS provider for the requested domain. They use the Certbot snap and the plugin snap.

## Install the plugin

Follow the [Certbot installation instructions](https://certbot.eff.org/instructions) for your platform. When replacing a distribution installation, back up `/etc/letsencrypt` and check for an existing timer or cron job so only one installation schedules renewals.

```sh
sudo snap install certbot --classic
sudo snap set certbot trust-plugin-with-root=ok
sudo snap install certbot-dns-multi
sudo snap connect certbot:plugin certbot-dns-multi
sudo /snap/bin/certbot plugins
```

The plugin runs with Certbot's privileges. Review the [plugin source and installation instructions](https://github.com/alexzorin/certbot-dns-multi) before connecting it.

## Set up the API token

In the mijn.host control panel, create a personal access token with **Bekijken** and **Wijzigen** under **Mijn domeinnamen**. Certbot needs to read the zone and add and remove challenge records. The API reports a missing write permission as `domains:write`. DNS template permissions are for editing templates. Record the token's expiry date so you can rotate it before it expires.

Run the following for an initial installation, from the repository checkout:

```sh
sudo install -d -o root -g root -m 700 /etc/letsencrypt/credentials
sudo install -o root -g root -m 600 examples/mijnhost.ini /etc/letsencrypt/credentials/mijnhost.ini
sudoedit /etc/letsencrypt/credentials/mijnhost.key
sudo chown root:root /etc/letsencrypt/credentials/mijnhost.key
sudo chmod 600 /etc/letsencrypt/credentials/mijnhost.key
```

Put only the token on one line in `mijnhost.key`. Keep this file out of version control. Use `dig example.net NS` to check the public delegation. A registrar transfer can leave the previous authoritative nameservers in place.

## Issue or migrate a certificate

For first issuance, replace the example name:

```sh
sudo /snap/bin/certbot certonly -a dns-multi \
  --dns-multi-credentials /etc/letsencrypt/credentials/mijnhost.ini \
  --cert-name app.example.net -d app.example.net
```

For an existing DNS-01 certificate, find its exact name with `sudo /snap/bin/certbot certificates` and run:

```sh
sudo /snap/bin/certbot reconfigure --cert-name app.example.net \
  -a dns-multi --dns-multi-credentials /etc/letsencrypt/credentials/mijnhost.ini
```

`reconfigure` tests the change against Let's Encrypt staging and saves the settings after success. If CAA restricts issuance to a production account, staging can be rejected even when the TXT record is correct. Confirm the production account is allowed, then plan a production issuance for that lineage or a separately authorized staging CAA change. Use `certbot certonly` with the existing certificate name and its full set of DNS names if performing a production issuance.

Keep credentials per certificate while using multiple providers. If all DNS-01 certificates on the host use mijn.host, you can save the following default in `/etc/letsencrypt/cli.ini`:

```ini
dns-multi-credentials = /etc/letsencrypt/credentials/mijnhost.ini
```

## Deploy to services

**Nginx** can use Certbot's installer with a matching enabled vhost:

```sh
sudo /snap/bin/certbot -a dns-multi -i nginx -d app.example.net
```

This command assumes the credential default above. For a manually configured vhost, set `ssl_certificate` to `/etc/letsencrypt/live/app.example.net/fullchain.pem` and `ssl_certificate_key` to `/etc/letsencrypt/live/app.example.net/privkey.pem`. Check and reload Nginx for the initial deployment. Install the example [Nginx deployment hook](hooks/20-nginx) so successful renewals reload Nginx when its configuration uses the renewed certificate.

**Postfix and Dovecot** can point their certificate settings to `fullchain.pem` and their separate key settings to `privkey.pem`. For Postfix configurations using separate files, the settings are `smtpd_tls_cert_file` and `smtpd_tls_key_file`. For Dovecot 2.4, use `ssl_server_cert_file` and `ssl_server_key_file`. The full chain has the server certificate first, followed by its intermediates. [Dovecot TLS documentation](https://doc.dovecot.org/2.4.0/core/config/ssl.html#chained-ssl-certificates)

Edit `CERT_NAME` and `TLS_HOSTNAME` in the [mail deployment hook](hooks/30-mail.example) to match your mail certificate. Install it only on a host running both services. It checks the chain, hostname and private key before reloading them.

Install the hooks you use as root-owned executables under `/etc/letsencrypt/renewal-hooks/deploy/`:

```sh
sudo install -o root -g root -m 750 hooks/20-nginx /etc/letsencrypt/renewal-hooks/deploy/20-nginx
# After editing the mail example for your installation:
sudo install -o root -g root -m 750 hooks/30-mail.example /etc/letsencrypt/renewal-hooks/deploy/30-mail
```

For containers or appliances, use a hook scoped to the relevant `RENEWED_LINEAGE`. Deploy the chain and key through the service's supported mechanism, then verify what the service actually serves.

## Verify and troubleshoot

```sh
sudo /snap/bin/certbot renew --cert-name app.example.net --dry-run
systemctl list-timers --all | grep certbot
openssl s_client -connect app.example.net:443 -servername app.example.net \
  -verify_hostname app.example.net -verify_return_error </dev/null
```

A dry run verifies issuance against staging. Deploy hooks run after successful live renewals. Test the appropriate service separately after initial deployment. For mail, check IMAPS on 993 and use `openssl s_client -starttls smtp` for SMTP or submission on 25 or 587.

- **403 missing `domains:write`** means the token cannot create live DNS records. Check **Mijn domeinnamen → Wijzigen** for the token actually installed on the server.
- **Wildcard CNAME interference** can occur when wildcard DNS synthesizes an alias for a challenge name. For zones where the plugin should write TXT records directly, add `LEGO_DISABLE_CNAME_SUPPORT = true` to the provider credentials file. Keep CNAME following enabled if you intentionally delegate challenge names. [Lego options](https://go-acme.github.io/lego/advanced/options/)
- **Apex plus wildcard issuance** can require two TXT values at the same name. The tested plugin version replaced the first value with the second. If you only serve a few names, request them explicitly, such as `example.net` and `www.example.net`. If wildcard coverage is required, test that your provider integration preserves both challenge values before depending on unattended renewal.
- **Old DNS answers** can linger after a provider move. Verify the registry delegation and check each authoritative nameserver. Allow time for cached answers to expire.

[Certbot user guide](https://eff-certbot.readthedocs.io/en/stable/using.html) · [mijn.host provider options](https://go-acme.github.io/lego/dns/mijnhost/) · [mijn.host DNS API](https://mijn.host/api/doc/api-4585320)
