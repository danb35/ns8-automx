*** Settings ***
Library    SSHLibrary

*** Variables ***
# Any resolvable-looking name: the schema demands a dot, nothing resolves it.
${TEST_HOST}    automx.ns8-ci.test

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

Check if automx is removed correctly
    ${rc} =    Execute Command    remove-module --no-preserve ${module_id}
    ...    return_rc=True  return_stdout=False
    Should Be Equal As Integers    ${rc}  0
