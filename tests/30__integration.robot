*** Settings ***
Documentation     tests/integration/test_node.py against the stack of 10__stack, run on the node
...               itself (NS8_NODE=local): the test container has no ssh client. It installs its
...               own automx from the image under test, so 20__automx must have removed its own.
...               Its dnshelper has no rule for that instance, so this pass covers the
...               not_permitted path and the routes waiting for DNS; 20__automx covers the rest.
Resource          automx.resource

*** Variables ***
${WORKDIR}    /root/automx-ci

*** Test Cases ***
Run the integration suite on the node
    Execute Command    mkdir -p ${WORKDIR}
    Put File    ${CURDIR}/integration/test_node.py    ${WORKDIR}/test_node.py    mode=0644
    ${output}  ${rc} =    Execute Command
    ...    cd ${WORKDIR} && NS8_NODE=local AUTOMX_IMAGE='${IMAGE_URL}' MAIL_MODULE_ID=${MAIL_ID} MAIL_DOMAIN=${MAIL_DOMAIN} TEST_USER_LOGIN=${TEST_LOGIN} TEST_USER_MAIL=${TEST_LOGIN}@${MAIL_DOMAIN} TEST_ALIAS_MAIL=${TEST_ALIAS}@${MAIL_DOMAIN} TEST_ALIAS_LOGIN=${TEST_LOGIN} DNSHELPER_MODULE_ID=${DNSHELPER_ID} python3 -m unittest -v test_node 2>&1
    ...    return_rc=True    timeout=45 minutes
    Log    ${output}
    Should Be Equal As Integers    ${rc}    0    ${output}
    # a skipped test passes unittest, but here every precondition is met
    Should Not Contain    ${output}    skipped
