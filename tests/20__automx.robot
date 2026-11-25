*** Settings ***
Documentation     automx with the stack of 10__stack: the looked-up login, display name and
...               alias, a domain's own settings, the DNS records through dnshelper and the
...               routes that wait for them (DESIGN.md 5.3, 5.6).
...
...               On the update leg automx is first installed from NethForge's stable release
...               and configured there, then updated to the image under test, and everything
...               after the update checks that the configuration came through it.
Resource          automx.resource

*** Test Cases ***
Install automx
    IF    '${SCENARIO}' == 'update'
        ${id} =    Install module    automx
    ELSE
        ${id} =    Install module    ${IMAGE_URL}
    END
    Set Global Variable    ${AUTOMX_ID}    ${id}

Configure automx on the mail module
    Run action    module/${AUTOMX_ID}/configure-module    {"http2https":false,"display_names":true}
    ${config} =    Run action    module/${AUTOMX_ID}/get-configuration    {}
    Should Be Equal    ${config}[mail_hostname]    ${MAIL_HOST}
    Should Not Be Equal    ${config}[mail_server]    ${None}
    Should Be True    ${config}[dnshelper_present]
    Set Suite Variable    ${MAIL_SERVER}    ${config}[mail_server]

Enable the mail domain
    ${out} =    Run action    module/${AUTOMX_ID}/set-domains    {"domains":{"${MAIL_DOMAIN}":{"enabled":true}}}
    Should Be Equal    ${out}[route_failures]    ${{ [] }}
    # dnshelper manages the zone, but automx has no access rule yet, so its
    # DNS cannot be ok and the domain's routes wait for it
    Should Be Equal    ${out}[waiting_for_dns]    ${{ [$MAIL_DOMAIN] }}

Give the domain its own settings
    Run action    module/${AUTOMX_ID}/set-domain-settings
    ...    {"domain":"${MAIL_DOMAIN}","overrides":{"display_names":false}}

Update automx to the image under test
    Skip If    '${SCENARIO}' != 'update'    scenario is ${SCENARIO}, nothing to update
    Run action    update-module    {"module_url":"${IMAGE_URL}","instances":["${AUTOMX_ID}"],"force":true}
    ${image} =    Execute Command    redis-cli HGET module/${AUTOMX_ID}/environment IMAGE_URL
    Should Be Equal    ${image}    ${IMAGE_URL}

Check that the settings are kept
    ${config} =    Run action    module/${AUTOMX_ID}/get-configuration    {}
    Should Be Equal    ${config}[http2https]    ${False}
    Should Be Equal    ${config}[display_names]    ${True}
    Should Be Equal    ${config}[mail_server]    ${MAIL_SERVER}
    ${entry} =    Domain entry    ${AUTOMX_ID}
    Should Be True    ${entry}[enabled]
    Should Be Equal    ${entry}[overrides]    ${{ {'display_names': False} }}
    Should Be Equal    ${entry}[route_status]    waiting_for_dns

Check that automx is running
    ${status} =    Run action    module/${AUTOMX_ID}/get-status    null
    ${service} =    Evaluate    next(s for s in $status['services'] if s['name'] == 'automx')
    Should Be True    ${service}[active] and not ${service}[failed]

Check the looked-up login and the domain's own display-name setting
    ${body} =    Autoconfig    ${AUTOMX_ID}    ${TEST_LOGIN}@${MAIL_DOMAIN}
    Should Contain    ${body}    <username>${TEST_LOGIN}</username>
    # display names are on by default but off for this domain
    Should Not Contain    ${body}    ${TEST_DISPLAY_NAME}
    ${conf} =    Execute Command    runagent -m ${AUTOMX_ID} cat automx.conf
    Should Contain    ${conf}    [${MAIL_DOMAIN}]

Check that the alias resolves to its owner
    # the alias map is refreshed a few seconds after automx starts
    Wait Until Keyword Succeeds    2 min    5 s
    ...    Autoconfig login should be    ${AUTOMX_ID}    ${TEST_ALIAS}@${MAIL_DOMAIN}    ${TEST_LOGIN}

Check that the domain's own display-name setting can be removed
    Run action    module/${AUTOMX_ID}/set-domain-settings    {"domain":"${MAIL_DOMAIN}","overrides":{}}
    ${body} =    Autoconfig    ${AUTOMX_ID}    ${TEST_LOGIN}@${MAIL_DOMAIN}
    Should Contain    ${body}    <displayName>${TEST_DISPLAY_NAME}</displayName>

Check that DNS waits for an access rule
    ${statuses}    ${dns} =    DNS statuses    ${AUTOMX_ID}
    Should Be True    ${dns}[managed]
    Should Be Equal    ${dns}[zone]    ${MAIL_DOMAIN}
    ${values} =    Evaluate    sorted(set($statuses.values()))
    Should Be Equal    ${values}    ${{ ['not_permitted'] }}

Check that the records are missing once automx has a rule
    # The rule DESIGN.md 5.3.6 asks the administrator to add, plus type A to
    # delete the conflicting record seeded below.
    Run action    module/${DNSHELPER_ID}/set-policy
    ...    {"rules":[{"caller":"module/${AUTOMX_ID}","zones":["${MAIL_DOMAIN}"],"access":"write","names":["autoconfig","autodiscover","_autodiscover._tcp"],"types":["CNAME","SRV","A"]}]}
    ${statuses}    ${dns} =    DNS statuses    ${AUTOMX_ID}
    ${values} =    Evaluate    sorted(set($statuses.values()))
    Should Be Equal    ${values}    ${{ ['missing'] }}

Check that a record of another type is a conflict
    # as dnshelper's administrator, who is not restricted by the policy
    Run action    module/${DNSHELPER_ID}/append-records
    ...    {"zone":"${MAIL_DOMAIN}","records":[{"name":"autoconfig","type":"A","data":"192.0.2.10"}]}
    ${statuses}    ${dns} =    DNS statuses    ${AUTOMX_ID}
    Should Be Equal    ${statuses}[autoconfig.${MAIL_DOMAIN}]    conflict
    Should Be Equal    ${statuses}[autodiscover.${MAIL_DOMAIN}]    missing

Check that a dry run changes nothing
    ${out} =    Run action    module/${AUTOMX_ID}/apply-dns
    ...    {"domain":"${MAIL_DOMAIN}","action":"overwrite","dry_run":true}
    Should Be True    ${out}[dry_run]
    ${removed} =    Evaluate    [r['type'] for r in $out['changes']['remove']]
    Should Contain    ${removed}    A
    ${added} =    Evaluate    sorted(r['type'] for r in $out['changes']['add'])
    Should Be Equal    ${added}    ${{ ['CNAME', 'CNAME', 'SRV'] }}
    ${statuses}    ${dns} =    DNS statuses    ${AUTOMX_ID}
    Should Be Equal    ${statuses}[autoconfig.${MAIL_DOMAIN}]    conflict

Check that overwriting creates the records and the routes
    Run action    module/${AUTOMX_ID}/apply-dns
    ...    {"domain":"${MAIL_DOMAIN}","action":"overwrite","dry_run":false}
    # check-dns creates the routes of a domain whose DNS has become ready (DESIGN.md 5.6)
    ${statuses}    ${dns} =    DNS statuses    ${AUTOMX_ID}
    ${values} =    Evaluate    sorted(set($statuses.values()))
    Should Be Equal    ${values}    ${{ ['ok'] }}
    ${entry} =    Domain entry    ${AUTOMX_ID}
    Should Be Equal    ${entry}[route_status]    configured
    ${exists} =    Traefik route exists    ${AUTOMX_ID}-autoconfig-${MAIL_DOMAIN}-0
    Should Be True    ${exists}
    ${exists} =    Traefik route exists    ${AUTOMX_ID}-autodiscover-${MAIL_DOMAIN}-0
    Should Be True    ${exists}

Take screenshots of the pages
    [Tags]    ui
    Import Library    Browser
    New Browser    chromium    headless=True
    New Context    ignoreHTTPSErrors=True
    Login to cluster-admin
    Open page    ${AUTOMX_ID}    status    Status    1._Status
    Open page    ${AUTOMX_ID}    domains    Domains    2._Domains
    Open page    ${AUTOMX_ID}    settings    Settings    3._Settings
    Open page    ${AUTOMX_ID}    about    About    4._About
    Close Browser

Check that disabling removes the routes and the records
    Run action    module/${AUTOMX_ID}/set-domains
    ...    {"domains":{"${MAIL_DOMAIN}":{"enabled":false,"remove_dns":true}}}
    ${exists} =    Traefik route exists    ${AUTOMX_ID}-autoconfig-${MAIL_DOMAIN}-0
    Should Not Be True    ${exists}
    ${statuses}    ${dns} =    DNS statuses    ${AUTOMX_ID}
    ${values} =    Evaluate    sorted(set($statuses.values()))
    Should Be Equal    ${values}    ${{ ['missing'] }}

Remove automx
    # 30__integration installs its own instance, and refuses to run beside another
    ${rc} =    Execute Command    remove-module --no-preserve ${AUTOMX_ID}
    ...    return_rc=True  return_stdout=False
    Should Be Equal As Integers    ${rc}    0
