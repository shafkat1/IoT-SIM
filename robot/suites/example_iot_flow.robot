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
    ${b}=    Get Environment Variable    S3_RESULTS_BUCKET    default=${EMPTY}
    Set Suite Variable    ${IOT_EP}    ${ep}
    Set Suite Variable    ${AWS_REG}    ${reg}
    Set Suite Variable    ${S3_BUCKET}    ${b}

*** Test Cases ***
Publish Step Over Aws Iot And Wait For S3 Json
    Should Not Be Empty    ${IOT_EP}    msg=Set AWS_IOT_DATA_ENDPOINT (IoT data ATS hostname)
    Should Not Be Empty    ${S3_BUCKET}    msg=Set S3_RESULTS_BUCKET
    Configure Aws Iot Publisher    ${IOT_EP}    region=${AWS_REG}
    Configure Aws S3    region=${AWS_REG}
    ${run}=    Publish Iot Step Aws    ${IOT_TOPIC}    ${DEVICE_ID}    ${SCENARIO_ID}
    ...    step-1    {"temp_c": 22.5, "pressure_kpa": 101.3}
    ${key}=    Set Variable    ${DEVICE_ID}_${SCENARIO_ID}.json
    ${json}=    Wait For Result S3    ${S3_BUCKET}    ${key}
    ...    poll_seconds=120    timeout_seconds=7200
    Compare Json To Expected    ${json}
    ...    {"device": "${DEVICE_ID}", "status": "ok"}
