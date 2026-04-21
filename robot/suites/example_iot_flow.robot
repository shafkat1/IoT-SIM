*** Settings ***
Library    ../libraries/IotTestBridge.py
Suite Setup       Load Env Defaults

*** Variables ***
${IOT_TOPIC}       lynx/simulator/commands
${DEVICE_ID}       test-device-01
${SCENARIO_ID}     scenario-001

*** Keywords ***
Load Env Defaults
    ${ep}=    Get Environment Variable    AWS_IOT_DATA_ENDPOINT    default=${EMPTY}
    ${reg}=    Get Environment Variable    AWS_REGION    default=${EMPTY}
    ${cs}=    Get Environment Variable    AZURE_STORAGE_CONNECTION_STRING    default=${EMPTY}
    ${cont}=    Get Environment Variable    AZURE_RESULT_CONTAINER    default=results
    Set Suite Variable    ${IOT_EP}    ${ep}
    Set Suite Variable    ${AWS_REG}    ${reg}
    Set Suite Variable    ${AZURE_CS}    ${cs}
    Set Suite Variable    ${AZURE_CONTAINER}    ${cont}

*** Test Cases ***
Publish Step Over Aws Iot And Wait For Azure Blob Json
    [Documentation]    Commands on AWS IoT Core; SUT pipeline writes results to Azure Blob (separate system).
    Should Not Be Empty    ${IOT_EP}    msg=Set AWS_IOT_DATA_ENDPOINT (IoT data ATS hostname)
    Should Not Be Empty    ${AZURE_CS}    msg=Set AZURE_STORAGE_CONNECTION_STRING
    Configure Aws Iot Publisher    ${IOT_EP}    region=${AWS_REG}
    ${run}=    Publish Iot Step Aws    ${IOT_TOPIC}    ${DEVICE_ID}    ${SCENARIO_ID}
    ...    step-1    {"temp_c": 22.5, "pressure_kpa": 101.3}
    Connect Blob From Connection String    ${AZURE_CS}
    ${blob}=    Set Variable    ${DEVICE_ID}_${SCENARIO_ID}.json
    ${json}=    Wait For Result Blob    ${AZURE_CONTAINER}    ${blob}
    ...    poll_seconds=120    timeout_seconds=7200
    Compare Json To Expected    ${json}
    ...    {"device": "${DEVICE_ID}", "status": "ok"}
