# IoT-SIM

End-to-end test orchestration: **Robot Framework on AWS EC2** publishes simulator commands through **AWS IoT Core**; **Raspberry Pi** subscribers drive bench hardware (GPIO/RS232) against a **system under test (SUT)** you treat as a black box. Result JSON is stored in **Azure Blob Storage** (another system)—Robot **polls** the blob, **compares** actual JSON to expected values, and **records** pass/fail through normal Robot outputs (`report.html`, `log.html`, `output.xml`).

**Repository:** [https://github.com/shafkat1/IoT-SIM](https://github.com/shafkat1/IoT-SIM)

This repo does **not** implement SUT internals. It focuses on the **contract** between automation (Robot), AWS messaging (IoT Core), edge simulators (Pi), and cross-cloud result artifacts (Azure Blob). **Amazon S3** remains available as an optional result store if you ever want an all-AWS path.

---

## Architecture (AWS commands, Azure results)

**Primary design:** Robot runs on **AWS EC2**, publishes test steps to **AWS IoT Core**, Pis consume commands over MQTT, the **SUT** (outside this repo) eventually produces state that lands in **Azure Blob Storage** as JSON. Robot **polls** Blob on an interval you configure, **compares** JSON to expected values, and records outcomes via standard **Robot reports**.

```mermaid
flowchart TB
  subgraph corp [Corporate network]
    TC[Test scenarios and expected JSON]
  end

  subgraph aws [AWS Cloud]
    EC2[EC2 - Robot Framework]
    LIB[IotTestBridge library]
    IOT[AWS IoT Core - MQTT commands]
    CW[CloudWatch optional]
    EC2 --> LIB
    LIB -->|boto3 iot-data Publish| IOT
    IOT -.->|metrics logs| CW
  end

  subgraph azure [Microsoft Azure - results system]
    AIH[Azure IoT Hub optional]
    BLOB[(Azure Blob Storage JSON results)]
    AIH -->|message routing export Function etc.| BLOB
  end

  subgraph edge [Physical test installation]
    RPi[Raspberry Pi simulator]
    SUT[SUT - black box]
    RPi -->|GPIO / RS232| SUT
    SUT -.->|telemetry per your stack| AIH
    SUT -.->|or other path to same blobs| BLOB
  end

  IOT -->|MQTT subscribe command topic| RPi
  LIB -->|HTTPS poll e.g. every 2-5 min| BLOB
  TC --> EC2
  EC2 -->|PASS FAIL log report output| TC
```

### Sequence (one step)

```mermaid
sequenceDiagram
  autonumber
  participant RF as Robot on EC2
  participant Lib as IotTestBridge
  participant IoT as AWS IoT Core
  participant Pi as Raspberry Pi
  participant SUT as SUT
  participant AzHub as Azure IoT Hub
  participant Blob as Azure Blob Storage

  RF->>Lib: Publish Iot Step Aws
  Lib->>IoT: MQTT publish JSON envelope
  IoT->>Pi: Deliver command to simulator
  Pi->>SUT: Hardware stimulus GPIO RS232
  Note over SUT,Blob: SUT stack writes results outside this repo optional path via IoT Hub
  SUT->>AzHub: Device telemetry when used
  AzHub->>Blob: Routing writes e.g. device_scenario.json
  loop Poll until blob exists or timeout
    RF->>Blob: Wait For Result Blob HTTPS
  end
  RF->>Lib: Compare Json To Expected
  Lib-->>RF: PASS or AssertionError FAIL
  Note right of RF: Robot report.html log.html output.xml
```

### Optional all-AWS results

If results are written to **Amazon S3** instead of Blob, use **`Wait For Result S3`** in the library; the command path can stay on **AWS IoT Core** unchanged.

---

## Components

| Layer | Responsibility |
|--------|----------------|
| **Robot Framework (EC2)** | Runs scenarios; publishes steps to **AWS IoT Core**; polls **Azure Blob** for result JSON; asserts actual vs expected (DeepDiff). |
| **`IotTestBridge.py`** | Keywords: AWS IoT publish (`iot-data`), **Azure Blob** wait/read (and optional **S3**), JSON compare; optional generic MQTT. |
| **AWS IoT Core** | MQTT for commands; EC2 uses IAM `iot:Publish`; Pis use X.509 policies (`Connect`, `Subscribe`, `Receive`). |
| **Azure Blob Storage** | Canonical store for result files (e.g. `{device_id}_{scenario_id}.json`) populated by **your** Azure-side system (e.g. IoT Hub routing, Function, etc.). |
| **`simulator_subscriber.py` (Pi)** | Subscribes to command topics; you map `values` to GPIO/serial. Supports **plain MQTT** or **IoT Core mutual TLS** (port 8883). |

---

## MQTT message envelope (commands)

Published JSON (Robot → AWS IoT → Pi):

| Field | Meaning |
|--------|---------|
| `run_id` | UUID for correlation (optional in downstream blob naming if you extend the pipeline). |
| `device_id` | Logical device under test. |
| `scenario_id` | Test scenario identifier. |
| `step_id` | Single step within the scenario. |
| `values` | Arbitrary JSON object interpreted by your simulator (sensor setpoints, digital IO, etc.). |

---

## Environment variables

| Variable | Used by | Purpose |
|----------|---------|---------|
| `AWS_IOT_DATA_ENDPOINT` | Robot / `Publish Iot Step Aws` | IoT **Data** ATS hostname (e.g. `xxxxx-ats.iot.us-east-1.amazonaws.com`). |
| `AWS_REGION` / `AWS_DEFAULT_REGION` | boto3 | Region (optional if set on EC2 instance profile or `~/.aws/config`). |
| `AZURE_STORAGE_CONNECTION_STRING` | Example suite / Blob client | Storage account connection string (or use `AZURE_STORAGE_ACCOUNT_URL` + `DefaultAzureCredential` in your suite). |
| `AZURE_RESULT_CONTAINER` | Example suite | Blob container name (default `results` in the example). |
| `MQTT_*` / `AWS_IOT_*` | Pi subscriber | See `tools/simulator_subscriber.py` and `--help`. |

---

## Credentials (hybrid)

**On EC2**

- **AWS:** Instance profile with `iot:Publish` on command topics.
- **Azure:** Prefer **workload identity federation** or a **managed identity** pattern your org uses for cross-cloud access; alternatively a **service principal** via `DefaultAzureCredential` env vars, or (dev only) `AZURE_STORAGE_CONNECTION_STRING`. The example suite uses a connection string for simplicity—harden for production.

---

## Polling behaviour

`Wait For Result Blob` (and `Wait For Result S3`) poll until the object exists or `timeout_seconds` elapses. Default `poll_seconds=120` (two minutes); set `poll_seconds=300` for a five-minute cadence.

Robot **test results** are the framework’s normal **PASS/FAIL** per keyword/test plus **`report.html`**, **`log.html`**, **`output.xml`**. Add a custom listener or post-step if you need to push summaries elsewhere (Jira, S3, etc.).

---

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

Run the example suite (AWS IoT + Azure Blob):

```bash
set PYTHONPATH=robot\libraries
set AWS_IOT_DATA_ENDPOINT=your-account-ats.iot.region.amazonaws.com
set AWS_REGION=us-east-1
set AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;...
set AZURE_RESULT_CONTAINER=results
robot robot\suites\example_iot_flow.robot
```

**Raspberry Pi (AWS IoT Core TLS)**

```bash
pip install paho-mqtt
python tools/simulator_subscriber.py \
  --iot-endpoint xxxxx-ats.iot.us-east-1.amazonaws.com \
  --root-ca AmazonRootCA1.pem \
  --cert device.pem.crt \
  --key private.pem.key \
  --topic "lynx/simulator/#"
```

---

## Repository layout

```
robot/
  libraries/IotTestBridge.py   # Robot keywords
  suites/example_iot_flow.robot
tools/
  simulator_subscriber.py      # Pi-side MQTT subscriber
requirements.txt
```
