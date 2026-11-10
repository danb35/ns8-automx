# automx user guide

This guide is for the person who administers an NS8 node. It explains what automx does,
what it needs before it can do anything, how to enable a domain and publish the DNS
records clients need to find it, how to let [dnshelper](https://github.com/danb35/ns8-dnshelper)
manage those records for you (optional), and how to share a download link with your
users. Developers who want to know how it's built, or how it uses dnshelper and the mail
module, should read the [main README](../README.md) instead.

For what data goes where, including what anyone on the internet can look up, see
[Data and privacy](../TERMS.md).

- [What automx does](#what-automx-does)
- [Before you start](#before-you-start)
- [Enabling a domain](#enabling-a-domain)
- [Publishing the DNS records](#publishing-the-dns-records)
- [Optional: managing DNS through dnshelper](#optional-managing-dns-through-dnshelper)
- [Settings](#settings)
- [Sharing a download link with your users](#sharing-a-download-link-with-your-users)
- [Checking on things: the Status page](#checking-on-things-the-status-page)
- [Backup and restore](#backup-and-restore)
- [When something goes wrong](#when-something-goes-wrong)

## What automx does

When someone sets up a new email account, most mail clients ask for nothing but an email
address and a password. Thunderbird, Outlook and Apple Mail all then try to *discover*
the rest — the mail server's host name, its ports, whether to use SSL — by asking a
handful of well-known DNS names and web addresses derived from the domain in the address.
automx answers those requests for your NS8 mail domains, so your users never have to be
told a server name, a port number or an encryption setting by hand.

It also looks up the address in your accounts directory (OpenLDAP or Samba AD, whichever
your mail domain's user domain uses) so the client is told the person's real login name
and display name, not just the address they typed. A user's own address
(`dan@example.com`) works for this out of the box, and so does a mail alias that delivers
to one person (see **Resolve mail aliases** under [Settings](#settings)). An alias shared by
several people has no single login, so a client asking about it gets a generic answer and
the person enters their own username.

The pages of the application, in the side menu:

| Page | What it is for |
|---|---|
| **Status** | How many domains are enabled, which mail server and user domain are in use, whether dnshelper is present, service health, backup status and a shortcut to the logs |
| **Domains** | Turn autoconfiguration on or off per mail domain, see its DNS and route status, publish DNS records, get a profile download link |
| **Settings** | The mail server, the service host name, whether HTTP redirects to HTTPS, display names, alias resolution, profile signing, and the calendar, contacts and ActiveSync providers |
| **About** | Version and links |

Nothing here requires you to touch DNS or the mail server directly: automx reads your
mail domains from the mail module and only ever *adds* the three DNS records each
enabled domain needs.

## Before you start

You need a **mail module instance already configured**, with at least one mail domain
and an accounts provider (OpenLDAP or Samba AD) bound to it as its user domain. automx
has nothing to offer until the mail module has both.

You do **not** need dnshelper. Without it, automx tells you exactly which DNS records to
create and lets you check whether they've shown up; with it, automx can create and fix
them for you, after you review and confirm each change. See
[Publishing the DNS records](#publishing-the-dns-records) for both paths.

## Enabling a domain

Open **Domains**. It lists every mail domain the mail module knows about. New domains
start **disabled** — nothing is published for a domain until you turn it on.

![The Domains page](images/domains.png)

Turning a domain on:

1. Reads the mail domain's user domain and looks up your directory's connection details.
2. Renders and validates automx's own configuration, and starts (or reloads) its
   service.
3. If the CNAME records for `autoconfig.<domain>` and `autodiscover.<domain>` are already
   published and point at this node, creates their Traefik routes right away, with a
   Let's Encrypt certificate.

If those two records aren't in place yet — the usual case the first time you enable a
domain — automx deliberately does **not** create the route
yet, and the Domains page shows the domain as **waiting for DNS** instead. This is by
design, not a glitch to wait out: a route created before its DNS is ready gets exactly one
shot at a certificate from Let's Encrypt, and a route stuck like that can stay
uncertified for a long time (Let's Encrypt's own rate limits) even after the DNS is fixed
soon after. So automx holds off instead.

Nothing extra to do once DNS is in place, though — publish the records (see the next
section) and automx creates the route and certificate automatically the next time it
checks. Opening the domain's DNS status dialog, pressing **Check again** there, or
confirming **Create missing records** (with dnshelper) all trigger that check on their
own, so publishing the records is the last step, not a separate "now go create the route"
one. The check that creates the route can take up to a minute or so.

A domain that later disappears from the mail module (its mail domain was removed) is
marked **Orphaned**: automx keeps remembering whether it was enabled, but there's nothing
left to serve, so its toggle is greyed out until an administrator deals with it on the
mail module's side.

Disabling a domain removes its route immediately. Its DNS records are left in place —
clients that already cached them would otherwise start failing — unless you explicitly
ask to remove them too, from the same dialog you use to publish them (see below).

## Publishing the DNS records

Each enabled domain needs three DNS records to work everywhere:

| Name | Type | Points at |
|---|---|---|
| `autoconfig.<domain>` | CNAME | This node's own name (or the service host you set in Settings) |
| `autodiscover.<domain>` | CNAME | The same |
| `_autodiscover._tcp.<domain>` | SRV | The same, on port 443 |

Open the row's overflow menu (⋮) and choose **DNS status**. What you see there depends
on whether dnshelper is installed and covers the domain's zone. Either way, the dialog
lists the three records with each one's current status — *OK*, *Missing*, *Conflict*.

![The DNS status dialog, listing the three records and their status](images/dns-status.png)

**Without dnshelper**, or if dnshelper doesn't manage this particular zone, you get an
info banner saying so, and the Domains page shows a **Manual** tag beside the domain's DNS
status. Create the listed records — name, type, value — in your own DNS provider's control
panel, then use **Check again** in the same dialog. automx asks the DNS servers that host
your zone directly, so a new record normally shows as *OK* right away. If it can't reach
those servers (some networks block outgoing DNS), it asks this node's usual DNS resolver
instead, and a new record can show as *Missing* for a while, sometimes half an hour,
until the resolver's cached answer expires.

**With dnshelper covering the zone**, the dialog also offers buttons to fix them:

- **Create missing records** appends whatever is missing.
- **Overwrite conflicting records** replaces a record that already exists with a
  different value, or — if something of a *different* type is in the way (an A record
  where a CNAME is needed) — removes it first and then adds the CNAME.

Either button first shows you a preview of exactly what will change (nothing is done
until you confirm), then you press **Confirm** to apply it for real.

If dnshelper manages the zone but has no access rule letting this module change it yet,
the dialog says so directly and shows the exact rule to add — see the next section.

Disabling a domain offers to remove its DNS records too, using the same dnshelper
connection, matching the exact name, type and value automx created — so anything else at
that name is left untouched.

## Optional: managing DNS through dnshelper

This step is entirely optional. Without it, automx still works — you just create the DNS
records yourself, once, following the copyable list on the Domains page. With
[dnshelper](https://github.com/danb35/ns8-dnshelper) installed and given access, automx
can create, check and fix those same records for you from its own Domains page, with a
preview before every change.

**1. Install dnshelper**, if it isn't already (it's in the NethForge repository, which every
cluster has but leaves disabled; enable `nethforge` under **Settings → Software repositories**),
and add a zone covering your mail domain(s) on its own Zones page. See dnshelper's own
[user guide](https://github.com/danb35/ns8-dnshelper/blob/master/docs/USER-GUIDE.md) for
that part — it needs an API credential from whichever service hosts your DNS.

**2. Grant automx access.** dnshelper starts every module, including this one, with **no
access at all** — a rule has to be added before automx can change (or even read) a
single record, on purpose, so a bug or a misconfigured module can only ever touch what
you explicitly allowed. Until you do, automx's own DNS status dialog says so directly and
shows the exact rule to add, with the real zone name already filled in:

![DNS status showing the missing access rule, with the suggested rule to add](images/dns-status-not-permitted.jpg)

Open dnshelper's **Access** page and add a rule with these values (or use `set-policy`
with the same fields):

| Field | Value |
|---|---|
| **Module** | `module/automx1` (or whatever your automx instance is actually called — check the Status page if you're not sure) |
| **Zones** | The zone(s) covering your mail domains, or **All zones** |
| **Access** | *Read and change* |
| **Record names** | `autoconfig`, `autoconfig.*`, `autodiscover`, `autodiscover.*`, `_autodiscover._tcp`, `_autodiscover._tcp.*` |
| **Record types** | `CNAME, SRV` |

That covers creating the three records, and replacing one whose value is wrong. If you
also want automx able to **overwrite a record of a different type** that's sitting where
a CNAME needs to go (for example, deleting a stray A record at `autoconfig.<domain>`
before adding the CNAME), the rule additionally needs to allow that conflicting type at
the same names — add it (`A`, in that example) or set **Record types** to `*`.

![The rule for automx on dnshelper's Access page, once added](images/dnshelper-access.png)

**3. That's it** — no further step is needed on automx's side. Its Domains page rechecks
dnshelper's coverage and your access rule live, every time you open the DNS status
dialog: if you add the zone or the rule *after* a domain was already enabled here, automx
notices on its own next check, with nothing to toggle or re-save.

If you ever remove dnshelper, or the access rule, automx falls back to showing the
records to create by hand again — the records it already created are left alone
either way, since removing dnshelper's access doesn't touch anything already published.

## Settings

Open **Settings**.

![The Settings page](images/settings.png)

- **Mail server** — the mail server whose domains this automx instance configures clients
  for. Until you choose one, automx uses the nearest mail server that no other automx
  instance uses, and keeps it once you enable a domain. A mail server another automx already
  uses is shown as unavailable. If every mail server is taken, the field reads **Choose a
  mail server**, the Domains page is empty and nothing is served until one is free. If you
  change it, domains only the previous mail server has stop being served and show as
  orphaned on the Domains page, and any calendar or ActiveSync provider the new one doesn't
  offer is reset to None. DNS records are left as they are.
- **Service host (FQDN)** — the name the CNAME and SRV records point at, and the host
  Outlook's Autodiscover route is published on. Leave it blank to use this node's own
  name, which is right for almost everyone; only set it if you want autoconfiguration to
  point somewhere other than this specific node (for example, a load balancer in front of
  several nodes).
- **Redirect HTTP to HTTPS** — on by default. Thunderbird and most current clients try
  HTTPS first anyway; leave this on unless you have a specific reason to serve plain
  HTTP.
- **Sign Apple profiles** — off by default. Signs the profiles users download with this
  server's own certificate for the service host: the one Let's Encrypt issues, or one you
  uploaded in the certificate settings, which takes precedence. iPhones and Macs then show
  the profiles as verified instead of unsigned. Below the switch, Settings says whether
  profiles are actually being signed and, if not, why (for example, no certificate yet, or
  an uploaded certificate with an ECDSA key, which can't be used for signing). Turning it
  on places that certificate's private key inside the automx container.

Under **Defaults for all domains**, the next settings apply to every enabled domain, unless
a domain has its own value (see [Settings for one domain](#settings-for-one-domain)):

- **Include display names** — on by default. automx looks up the display name for
  whichever address a client asks about and includes it in the response, which is
  normal, expected client behavior. Since these endpoints answer *any* request without a
  password, by protocol design, this is also a small amount of address-to-name
  disclosure to anyone who asks. Turn it off if you'd rather trade that away for clients
  showing the raw email address instead of a name.
- **Resolve mail aliases** — on by default for new installations; an instance updated from
  0.1.x keeps it off until you turn it on, so updating doesn't change what it hands out.
  When someone sets up an alias address that
  delivers to one user (for example `dan.brown@` for user `dan`), the client is given that
  user's login, so they don't have to type it. An alias shared by several users can't be
  resolved; its users still type their own login. Like display names, this tells anyone
  who asks which login is behind an alias; turn it off if you'd rather not. New or changed
  aliases are picked up within 15 minutes.

### Calendars, contacts and ActiveSync

![The calendar, contacts and ActiveSync settings](images/settings-groupware.png)

If Nextcloud, SOGo or WebTop is installed, automx can also hand out its calendar and
contacts (CalDAV/CardDAV) or ActiveSync settings, so clients set those up along with
mail. Pick the app under **CalDAV/CardDAV provider** or **ActiveSync provider** and save.

- Apple devices get calendar and contacts accounts in the downloaded profile. Each
  account asks for the password once, because the profile contains no passwords.
- Thunderbird is told about the calendar and address book; Outlook and phones that use
  ActiveSync are pointed at the ActiveSync server. On an iPhone, adding the address as a
  **Microsoft Exchange** account (on iOS 26, **Settings → Apps → Mail → Mail Accounts**)
  finds the ActiveSync server by itself and asks for the password once; the downloaded
  profile, which has no ActiveSync account, asks once per account instead.
- Users log in with the same user name as for mail.

An app is only offered when it is set up with a host name and uses the same user domain
as the mail server. ActiveSync also requires the app (SOGo or WebTop; Nextcloud has none)
to use this mail server, and SOGo only offers what is switched on in its own settings.
Nextcloud must run on the same node as automx.

### Settings for one domain

On the **Domains** page, a domain's overflow menu offers **Domain settings**. There you can
give that domain its own value for any of the four defaults: **Include display names**,
**Resolve mail aliases**, **CalDAV/CardDAV provider** and **ActiveSync provider**. For
example, one domain can hand out SOGo calendars and display names while another hands out
neither.

Each setting starts at **Default**, which follows the Settings page and changes when you
change it there; the choice in brackets shows what that is now. For the providers,
**None** turns the service off for this domain even when the default has one. A domain
with its own settings shows a **Custom settings** tag in the table. Setting everything
back to **Default** removes its own settings.

A domain keeps its own settings while disabled, and when it is enabled again. If a chosen
app later stops providing the service (it is removed, or switched to another mail server),
that domain gets no calendar or ActiveSync settings, and its dialog shows the app as no
longer available; mail settings keep working.

## Sharing a download link with your users

automx's own endpoints don't need a password — that's how autoconfiguration protocols
work, a client only ever supplies the address it's setting up — so there's no separate
sign-in page inside this module for your users. Instead, once a domain is enabled, its
row's overflow menu offers **Get profile link**, giving you two things to hand to your
users however you already reach them (an intranet page, a wiki, a welcome email):

- **A direct link** (`https://autoconfig.<domain>/mobileconfig`) to automx's own small
  download page: a user types their address, downloads their mail profile. Nothing to
  build; just share the link.
- **An embeddable HTML form**, a self-contained snippet with no external JavaScript or
  CSS, for pasting into a page you control if you'd rather users didn't have to leave it.

Both are a thin wrapper around the same already-public, unauthenticated URL — they add
no authentication of their own, just convenience.

![The profile link dialog, with the direct link and the embeddable form](images/profile-link.png)

## Checking on things: the Status page

**Status** shows how many domains are enabled with a shortcut to manage them, the mail
server and user domain currently in use, whether dnshelper is present, the automx
service's own health, your backup status, and a card that opens this module's system
logs.

![The Status page](images/status.png)

If a domain looks wrong, start here: the service cards show whether the automx
service is actually running, which is the first thing to check if enabling a domain
succeeded but a client still can't find it.

## Backup and restore

automx's backup includes each domain's enabled/disabled flag, the module's settings and the
mail server it uses. It does **not** include the
rendered configuration file that's actually served — that file contains your directory's
bind password, and it's regenerated automatically from your mail module and accounts
provider every time the service starts, so there's nothing useful to preserve there
between backups.

After a restore, automx re-creates its Traefik routes and re-renders its configuration
on its own; you don't need to re-enable domains or re-check anything. If dnshelper
managed the zone before, you'll need to re-add the access rule for the *restored*
module's own id if it changed — the DNS status dialog will tell you exactly what's
missing, the same as it would for a domain enabled for the first time.

## When something goes wrong

| What you see | What it means and what to do |
|---|---|
| A domain stays **Waiting for DNS** | Its `autoconfig`/`autodiscover` CNAME records aren't published and pointing at this node yet (an A record at those names doesn't count), so automx has deliberately held off creating its route rather than let it fail its one shot at a certificate. Publish the records (see [Publishing the DNS records](#publishing-the-dns-records)) — the route and certificate are created automatically the next time automx checks, which opening the DNS status dialog or pressing **Check again** both do |
| **DNS is not managed by dnshelper for this domain** | Either dnshelper isn't installed, or it's installed but the zone covering this domain isn't one of its zones. Create the records shown with your DNS provider, or add the zone on dnshelper's own Zones page |
| **dnshelper has no access rule for this zone** | dnshelper knows the zone, but this automx instance hasn't been given a rule for it yet. Add the rule shown in the dialog — see [Optional: managing DNS through dnshelper](#optional-managing-dns-through-dnshelper) |
| A DNS record shows **Conflict** | Something else already exists at that name with a different value (or a different record type). Use **Overwrite conflicting records** if dnshelper manages the zone, after reviewing the preview, or fix it at your DNS provider directly otherwise |
| A client shows the person's raw email address instead of their name | Either **Include display names** is off in Settings, or the address the client asked about is a mail *alias* that automx can't resolve: one shared by several people, one added in the last 15 minutes, or any alias while **Resolve mail aliases** is off. The client then falls back to a generic answer and the person enters their own username |
| Settings says **Mail server not found** | The mail server this automx is bound to is no longer on the cluster, so nothing is being served. Choose another one in Settings and save. |
| Outlook sets itself up with settings that don't match what automx hands out | Outlook asks the bare mail domain (`https://<domain>/autodiscover/autodiscover.xml`) before `autodiscover.<domain>`. If WebTop or a website answers on the bare domain, Outlook takes that answer. Serve nothing at that path on the bare domain, or have it match the mail server's settings; automx can't change it |
| Settings says **Choose a mail server** and the Domains page is empty | Every mail server on the cluster is already used by another automx instance. Free one up, by changing or removing that other instance, then choose it here and save. |
| A domain is greyed out and marked **Orphaned** | The mail domain it was for no longer exists on the mail module. Nothing is being served for it; remove it from the mail module for good if it's not coming back |
| The service on the Status page shows as not running | Check the service logs from the Status page's Logs card. A validation failure in the rendered configuration (for example, the accounts provider being briefly unreachable) leaves the *previous* working configuration in place rather than taking the service down, so this usually means something more fundamental — the mail module or the accounts provider being absent entirely |

If something still doesn't work, the Status page's Logs card shows what automx itself
logged. Please report bugs at <https://github.com/danb35/ns8-automx/issues>; do not
include passwords or bind credentials.
