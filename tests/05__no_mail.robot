*** Settings ***
Documentation     automx alone, before 10__stack installs a mail module: every action must
...               degrade cleanly or refuse with a validation error (DESIGN.md 6.3).
Resource          automx.resource

*** Variables ***
# Any resolvable-looking name: the schema demands a dot, nothing resolves it.
${TEST_HOST}    automx.ns8-ci.test

*** Test Cases ***
Check if automx is installed correctly
    ${id} =    Install module    ${IMAGE_URL}
    Set Suite Variable    ${module_id}    ${id}

Check if automx can be configured
    Run action    module/${module_id}/configure-module
    ...    {"service_host":"${TEST_HOST}","http2https":false,"display_names":false}

Check if automx configuration reads back
    ${config} =    Run action    module/${module_id}/get-configuration    {}
    Should Be Equal    ${config}[service_host]    ${TEST_HOST}
    Should Be Equal    ${config}[http2https]    ${False}
    Should Be Equal    ${config}[display_names]    ${False}
    Should Be Equal As Integers    ${config}[enabled_domain_count]    0
    # No mail module yet; get-configuration must still degrade cleanly.
    Should Be Equal    ${config}[mail_hostname]    ${None}
    Should Be Equal    ${config}[dav_module]    ${None}
    Should Be Equal    ${config}[groupware]    ${{ [] }}
    Should Be Equal    ${config}[mail_server]    ${None}
    Should Be Equal    ${config}[mail_servers]    ${{ [] }}

Check if configure-module rejects an unknown mail server
    Action should fail    module/${module_id}/configure-module
    ...    {"mail_server":"11111111-2222-3333-4444-555555555555"}

Check if configure-module rejects an unavailable groupware module
    Action should fail    module/${module_id}/configure-module    {"dav_module":"sogo1"}

Check if get-domains tolerates a missing mail module
    ${result} =    Run action    module/${module_id}/get-domains    {}
    Should Be Equal    ${result}[domains]    ${{ [] }}

Check if set-domains rejects a domain the mail module doesn't have
    Action should fail    module/${module_id}/set-domains    {"domains":{"example.test":{"enabled":true}}}

Check if set-domain-settings rejects a domain the mail module doesn't have
    Action should fail    module/${module_id}/set-domain-settings
    ...    {"domain":"example.test","overrides":{"display_names":false}}

Check if set-domain-settings rejects an unknown setting
    # Only the four per-domain settings can be overridden (DESIGN.md 12).
    Action should fail    module/${module_id}/set-domain-settings
    ...    {"domain":"example.test","overrides":{"service_host":"x.example.test"}}

Check if automx service is healthy
    # core's own get-status takes null, not {}
    Run action    module/${module_id}/get-status    null

Check if automx is removed correctly
    ${rc} =    Execute Command    remove-module --no-preserve ${module_id}
    ...    return_rc=True  return_stdout=False
    Should Be Equal As Integers    ${rc}  0
