*** Settings ***
Documentation     Shared by the suites in tests/. The suites run in file-name order:
...               05__no_mail (automx alone), 10__stack (directory, mail, dnshelper),
...               20__automx (the real flow, with the update on the update leg) and
...               30__integration (tests/integration/test_node.py, on the node).
Library           SSHLibrary

*** Variables ***
# -v SCENARIO:install|update, from the shared test-module.sh
${SCENARIO}       install
${ADMIN_USER}     admin
${ADMIN_PASSWORD}    Nethesis,1234
# Everything below exists only on the throwaway CI node. No name resolves
# publicly (.test), and every password and key is fake.
${USER_DOMAIN}    dir.automx.test
${MAIL_DOMAIN}    ci.automx.test
${MAIL_HOST}      mail.ci.automx.test
${LDAP_ADMIN_PASSWORD}    Ci-Ldap-Admin-2026!
${TEST_LOGIN}     fred
${TEST_DISPLAY_NAME}    Fred Flintstone
${TEST_PASSWORD}    Ci-User-Pass-2026!
${TEST_ALIAS}     fred.flintstone
# PowerDNS on the node's loopback as dnshelper's DNS provider, as dnshelper's
# own CI runs it. Its port 53 is never published: only its API is used.
${PDNS_IMAGE}     docker.io/powerdns/pdns-auth-49:4.9.17
${PDNS_API}       http://127.0.0.1:18081
${PDNS_KEY}       ci-not-a-real-key

*** Keywords ***
Run action
    [Documentation]    api-cli run <path>, where path is a cluster action or
    ...    module/<id>/<action>. Fails on a non-zero exit; returns the parsed output.
    [Arguments]    ${path}    ${data}=null
    ${output}  ${rc} =    Execute Command    api-cli run ${path} --data '${data}'
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}    0    ${path} failed: ${output}
    ${parsed} =    Evaluate    json.loads(r'''${output}''' or 'null')    modules=json
    RETURN    ${parsed}

Action should fail
    [Arguments]    ${path}    ${data}=null
    ${rc} =    Execute Command    api-cli run ${path} --data '${data}'
    ...    return_rc=True  return_stdout=False
    Should Not Be Equal As Integers    ${rc}    0    ${path} should have been refused

Install module
    [Documentation]    add-module, by image URL or by name (the repositories' stable release).
    [Arguments]    ${image}
    ${output}  ${rc} =    Execute Command    add-module ${image} 1
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}    0    add-module ${image} failed: ${output}
    ${result} =    Evaluate    ast.literal_eval($output.strip().splitlines()[-1])    modules=ast
    RETURN    ${result}[module_id]

Domain entry
    [Documentation]    get-domains' entry for the CI mail domain.
    [Arguments]    ${module_id}
    ${out} =    Run action    module/${module_id}/get-domains    {}
    # The name as a literal: a $variable inside a generator is out of its scope
    ${entry} =    Evaluate    next(d for d in $out['domains'] if d['domain'] == '${MAIL_DOMAIN}')
    RETURN    ${entry}

DNS statuses
    [Documentation]    check-dns for the CI mail domain: {host: status}, and the dns object.
    [Arguments]    ${module_id}
    ${out} =    Run action    module/${module_id}/check-dns    {"domain":"${MAIL_DOMAIN}"}
    ${dns} =    Set Variable    ${out}[results][0][dns]
    ${statuses} =    Evaluate    {r['host']: r['status'] for r in $dns['records']}
    RETURN    ${statuses}    ${dns}

Autoconfig
    [Documentation]    Autoconfig for an address, straight from the container's loopback port.
    [Arguments]    ${module_id}    ${address}
    ${body} =    Execute Command
    ...    curl -fsS "http://127.0.0.1:$(redis-cli HGET module/${module_id}/environment TCP_PORT)/mail/config-v1.1.xml?emailaddress=${address}"
    RETURN    ${body}

Autoconfig login should be
    [Arguments]    ${module_id}    ${address}    ${login}
    ${body} =    Autoconfig    ${module_id}    ${address}
    Should Contain    ${body}    <username>${login}</username>

Traefik route exists
    [Arguments]    ${instance}
    ${traefik} =    Execute Command    redis-cli GET node/1/default_instance/traefik
    ${route} =    Run action    module/${traefik}/get-route    {"instance":"${instance}"}
    # get-route answers {} for a route that does not exist
    ${exists} =    Evaluate    bool($route)
    RETURN    ${exists}

Login to cluster-admin
    New Page    https://${NODE_ADDR}/cluster-admin/
    Fill Text    text="Username"    ${ADMIN_USER}
    Click    button >> text="Continue"
    Fill Text    text="Password"    ${ADMIN_PASSWORD}
    Click    button >> text="Log in"
    Wait For Elements State    css=#main-content    visible    timeout=10s

Open page
    [Arguments]    ${module_id}    ${page}    ${heading}    ${shot}
    Go To    https://${NODE_ADDR}/cluster-admin/#/apps/${module_id}?page=${page}
    Wait For Elements State    iframe >>> h2 >> text="${heading}"    visible    timeout=30s
    Sleep    5s
    Take Screenshot    filename=${OUTPUT DIR}/browser/screenshot/${shot}.png
