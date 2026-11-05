*** Settings ***
Library    SSHLibrary

*** Variables ***
# Any resolvable-looking name: the schema demands a dot, nothing resolves it.
${TEST_HOST}    automx.ns8-ci.test
${ADMIN_USER}    admin
${ADMIN_PASSWORD}    Nethesis,1234

*** Keywords ***
Login to cluster-admin
    New Page    https://${NODE_ADDR}/cluster-admin/
    Fill Text    text="Username"    ${ADMIN_USER}
    Click    button >> text="Continue"
    Fill Text    text="Password"    ${ADMIN_PASSWORD}
    Click    button >> text="Log in"
    Wait For Elements State    css=#main-content    visible    timeout=10s

Open page
    [Arguments]    ${page}    ${heading}    ${shot}
    Go To    https://${NODE_ADDR}/cluster-admin/#/apps/${module_id}?page=${page}
    Wait For Elements State    iframe >>> h2 >> text="${heading}"    visible    timeout=30s
    Sleep    5s
    Take Screenshot    filename=${OUTPUT DIR}/browser/screenshot/${shot}.png

*** Test Cases ***
Check if automx is installed correctly
    ${output}  ${rc} =    Execute Command    add-module ${IMAGE_URL} 1
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}  0
    &{output} =    Evaluate    ${output}
    Set Suite Variable    ${module_id}    ${output.module_id}

Check if automx can be configured
    ${rc} =    Execute Command
    ...    api-cli run module/${module_id}/configure-module --data '{"service_host":"${TEST_HOST}","http2https":false,"display_names":false}'
    ...    return_rc=True  return_stdout=False
    Should Be Equal As Integers    ${rc}  0

Check if automx configuration reads back
    ${output}  ${rc} =    Execute Command    api-cli run module/${module_id}/get-configuration --data '{}'
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}  0
    ${config} =    Evaluate    json.loads('''${output}''')    modules=json
    Should Be Equal    ${config}[service_host]    ${TEST_HOST}
    Should Be Equal    ${config}[http2https]    ${False}
    Should Be Equal    ${config}[display_names]    ${False}
    Should Be Equal As Integers    ${config}[enabled_domain_count]    0
    # No mail module on this throwaway CI node (DESIGN.md 9.1); get-configuration
    # must still degrade cleanly rather than fail the task.
    Should Be Equal    ${config}[mail_hostname]    ${None}
    Should Be Equal    ${config}[dav_module]    ${None}
    Should Be Equal    ${config}[groupware]    ${{ [] }}

Check if configure-module rejects an unavailable groupware module
    ${rc} =    Execute Command
    ...    api-cli run module/${module_id}/configure-module --data '{"dav_module":"sogo1"}'
    ...    return_rc=True  return_stdout=False
    Should Not Be Equal As Integers    ${rc}  0

Check if get-domains tolerates a missing mail module
    ${output}  ${rc} =    Execute Command    api-cli run module/${module_id}/get-domains --data '{}'
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}  0
    ${result} =    Evaluate    json.loads('''${output}''')    modules=json
    Should Be Equal    ${result}[domains]    ${{ [] }}

Check if set-domains rejects a domain the mail module doesn't have
    # No mail module is installed on this node, so any domain name is
    # unknown -- confirms the action fails a specific, user-fixable
    # validation rather than crashing (DESIGN.md 6.3).
    ${output}  ${rc} =    Execute Command
    ...    api-cli run module/${module_id}/set-domains --data '{"domains":{"example.test":{"enabled":true}}}'
    ...    return_rc=True
    Should Not Be Equal As Integers    ${rc}  0

Check if automx service is healthy
    # get-status is core's own inherited action; unlike our own actions it
    # was never given the "accept {} too" treatment (DESIGN.md 6.1), so its
    # validate-input.json is strictly "type": "null" -- {} fails core's own
    # schema validation (exit 10, validation-failed) before any of our code
    # runs. Confirmed via the CI VM journal, 2026-09-23.
    ${output}  ${rc} =    Execute Command    api-cli run module/${module_id}/get-status --data 'null'
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}  0

Take screenshots of the pages
    # No mail module on this node, so they show the empty states.
    [Tags]    ui
    Import Library    Browser
    New Browser    chromium    headless=True
    New Context    ignoreHTTPSErrors=True
    Login to cluster-admin
    Open page    status    Status    1._Status
    Open page    domains    Domains    2._Domains
    Open page    settings    Settings    3._Settings
    Open page    about    About    4._About
    Close Browser

Check if automx is removed correctly
    ${rc} =    Execute Command    remove-module --no-preserve ${module_id}
    ...    return_rc=True  return_stdout=False
    Should Be Equal As Integers    ${rc}  0
