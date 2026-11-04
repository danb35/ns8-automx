# Data and privacy

automx has no telemetry, and nothing is sent to its author. It runs on your own node. You, as the
administrator, decide whether what it publishes suits your legal and privacy obligations.

## What anyone on the internet can learn

Email client autoconfiguration works before the user has logged in, so these endpoints need no
password, by the design of the protocols. Anyone who can reach `autoconfig.<domain>` or
`autodiscover.<domain>` for an enabled domain can give any address in that domain and receive:

| Data | Depends on |
|---|---|
| The mail server's name, ports and encryption | Always included |
| The login name for that address (a bare username, when the address belongs to a user) | Always looked up. An address that matches no user gets the address itself back, so a response can show whether an address is a real account |
| The user's display name | **Include display names**, on by default |
| The login name behind a mail alias | **Resolve mail aliases**, on by default for new installations |
| The CalDAV, CardDAV and ActiveSync server addresses | Only if you choose a module for them in Settings |

Login names and display names can be personal data. Turn the two settings off if you would rather
not publish them; clients then show the bare address, and users of an alias type their login by
hand. automx has no rate limiting of its own.

Passwords are never handed out. A password sent to the profile download form is refused.

## What goes where

| Data | Where it goes | When |
|---|---|---|
| The address a client asks about, and the client's IP address | This node. automx uses the address for the lookup and does not store it; its own log has only the method, path and status of each request. The node's Traefik access log can record the IP address and the requested URL, which includes the address when a client puts it there, as Autoconfig does. Logs go to NS8's log server and to any syslog server or Cloud Log Manager you forward them to | Every request |
| The address asked about or, for an alias, its owner's login | The accounts provider of your cluster (OpenLDAP or Samba AD), over the node's internal LDAP proxy | Every request |
| The names `autoconfig.<domain>` and `autodiscover.<domain>` | Let's Encrypt, to issue their certificates. Certificate Transparency logs then list them publicly | When a domain's routes are created, and on renewal |
| Domain names, and the node's IP address | The DNS servers responsible for each domain, and the node's own resolvers | Each time DNS status is checked |
| DNS records | The DNS host you chose, through [dnshelper](https://github.com/danb35/ns8-dnshelper) | Only if dnshelper is installed, manages the zone and you confirm a change. See [dnshelper's own page](https://github.com/danb35/ns8-dnshelper/blob/master/TERMS.md) |
| Which domains are enabled, and the settings | Your backup destination, encrypted by NS8 | If you have configured backups |

How Let's Encrypt, DNS servers and DNS hosts handle this data is governed by their own terms.

## What is kept on the node

These files are in the module's state directory, and none of them is backed up:

- `ldap-lookup.json`: the password automx uses to read your directory, mode 0600. It is not stored
  in Redis. It is written again each time automx starts.
- `aliases/aliases.json`: which alias belongs to which login, refreshed every 15 minutes. It is
  empty when **Resolve mail aliases** is off.
- `signing/key.pem`: only if you turn on **Sign Apple profiles**. It is a copy of the private key of
  the service host's TLS certificate, mode 0600, and it is available inside the automx container. It
  is removed when you turn signing off.

## What it is allowed to do on your cluster

automx asks for more access than it uses, because the mail module and Traefik offer no narrower role:

- `mail@any:mailadm` also allows revealing the mail master credentials and changing relay and BCC
  rules. automx only calls `get-configuration`, `list-domains` and `list-addresses`.
- `traefik@node:certadm` also allows setting and deleting certificates. automx only calls
  `get-certificate`.

The code is public, so you can check this.

## Removing data

Removing the module deletes its state directory, including the files above, and its Traefik routes.
DNS records stay at your DNS host, except that disabling a domain through the UI can remove them if
dnshelper manages the zone and you ask it to. Older backups and logs keep what they already hold.

## License

automx is free software under the [GNU General Public License v3](LICENSE) or later. It packages
[croessner/automx](https://github.com/croessner/automx), also GPL-3.0-or-later.
