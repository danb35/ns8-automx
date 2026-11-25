*** Settings ***
Documentation     What automx works with on a real node: an OpenLDAP user domain with a user,
...               a mail module on it with an alias, and dnshelper managing the mail domain's
...               zone on a local PowerDNS. Nothing here leaves the node, apart from pulling
...               images and reading the NethForge repository.
Resource          automx.resource

*** Test Cases ***
Enable the NethForge repository
    # automx and dnshelper are published there. The update leg installs automx's
    # stable release from it, the one users upgrade from.
    Run action    alter-repository    {"name":"nethforge","status":true}

Install OpenLDAP with a user
    ${id} =    Install module    openldap
    Set Global Variable    ${LDAP_ID}    ${id}
    Run action    module/${id}/configure-module
    ...    {"provision":"new-domain","domain":"${USER_DOMAIN}","admuser":"admin","admpass":"${LDAP_ADMIN_PASSWORD}"}
    # A display name of two words: OpenLDAP's cn holds only the first (DESIGN.md 3.3)
    Run action    module/${id}/add-user
    ...    {"user":"${TEST_LOGIN}","display_name":"${TEST_DISPLAY_NAME}","password":"${TEST_PASSWORD}","mail":"${TEST_LOGIN}@${MAIL_DOMAIN}"}

Install mail on the user domain, with an alias
    ${id} =    Install module    mail
    Set Global Variable    ${MAIL_ID}    ${id}
    Run action    module/${id}/configure-module
    ...    {"user_domain":"${USER_DOMAIN}","hostname":"${MAIL_HOST}","mail_domain":"${MAIL_DOMAIN}"}
    Run action    module/${id}/add-address
    ...    {"atype":"domain","local":"${TEST_ALIAS}","domain":"${MAIL_DOMAIN}","destinations":[{"dtype":"user","name":"${TEST_LOGIN}"}]}
    ${domains} =    Run action    module/${id}/list-domains
    ${names} =    Evaluate    [d['domain'] for d in $domains]
    Should Contain    ${names}    ${MAIL_DOMAIN}

Start PowerDNS with the mail domain's zone
    # Runs as a non-root user and binds port 53 inside the container: podman
    # needs the sysctl for that.
    ${rc} =    Execute Command
    ...    podman run -d --name automx-ci-pdns --sysctl net.ipv4.ip_unprivileged_port_start=53 -p 127.0.0.1:18081:8081 -e PDNS_AUTH_API_KEY=${PDNS_KEY} ${PDNS_IMAGE}
    ...    return_rc=True  return_stdout=False
    Should Be Equal As Integers    ${rc}    0
    ${rc} =    Execute Command
    ...    for i in $(seq 90); do curl -fsS -o /dev/null -H 'X-API-Key: ${PDNS_KEY}' ${PDNS_API}/api/v1/servers/localhost \&\& exit 0; sleep 1; done; exit 1
    ...    return_rc=True  return_stdout=False
    Should Be Equal As Integers    ${rc}    0    PowerDNS did not start
    ${rc} =    Execute Command
    ...    curl -fsS -o /dev/null -H 'X-API-Key: ${PDNS_KEY}' -X POST -d '{"name":"${MAIL_DOMAIN}.","kind":"Native","nameservers":["ns1.${MAIL_DOMAIN}."],"soa_edit_api":"DEFAULT"}' ${PDNS_API}/api/v1/servers/localhost/zones
    ...    return_rc=True  return_stdout=False
    Should Be Equal As Integers    ${rc}    0

Install dnshelper managing the zone
    ${id} =    Install module    dnshelper
    Set Global Variable    ${DNSHELPER_ID}    ${id}
    Run action    module/${id}/configure-module    {}
    ${credential} =    Run action    module/${id}/add-credential
    ...    {"name":"PowerDNS (CI)","provider":"powerdns","fields":{"api_url":"${PDNS_API}","api_key":"${PDNS_KEY}"}}
    Run action    module/${id}/add-zone    {"zone":"${MAIL_DOMAIN}","credential":"${credential}[id]"}
    # No access rule yet: 20__automx adds the one automx needs, once it knows
    # automx's module id.
    Run action    module/${id}/set-policy    {"rules":[]}
