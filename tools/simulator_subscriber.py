#!/usr/bin/env python3
"""
Raspberry Pi side: subscribe to MQTT, print/act on IoT simulator commands.

Modes:
  * Plain broker: --host / --port (optional --tls, user/password).
  * AWS IoT Core: --iot-endpoint + device X.509 (mutual TLS on port 8883).
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys

import paho.mqtt.client as mqtt


def on_message(_client: mqtt.Client, _userdata: object, msg: mqtt.MQTTMessage) -> None:
    try:
        data = json.loads(msg.payload.decode("utf-8"))
    except json.JSONDecodeError:
        print(f"[sim] non-json on {msg.topic}: {msg.payload!r}", file=sys.stderr)
        return
    print(f"[sim] topic={msg.topic} body={json.dumps(data, indent=2)}")
    # Map data.get("values") to GPIO/serial for the SUT harness.


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="MQTT simulator subscriber for test bench")
    p.add_argument("--topic", default=os.environ.get("MQTT_TOPIC", "lynx/simulator/#"))

    aws = p.add_argument_group("AWS IoT Core (mutual TLS)")
    aws.add_argument(
        "--iot-endpoint",
        default=os.environ.get("AWS_IOT_ENDPOINT"),
        help="ATS hostname, e.g. xxxxx-ats.iot.us-east-1.amazonaws.com",
    )
    aws.add_argument("--root-ca", default=os.environ.get("AWS_IOT_ROOT_CA"))
    aws.add_argument("--cert", default=os.environ.get("AWS_IOT_DEVICE_CERT"))
    aws.add_argument("--key", default=os.environ.get("AWS_IOT_DEVICE_KEY"))
    aws.add_argument("--client-id", default=os.environ.get("AWS_IOT_CLIENT_ID", "sim-rpi"))

    plain = p.add_argument_group("Plain MQTT broker")
    plain.add_argument("--host", default=os.environ.get("MQTT_HOST", "127.0.0.1"))
    plain.add_argument("--port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    plain.add_argument("--user", default=os.environ.get("MQTT_USER"))
    plain.add_argument("--password", default=os.environ.get("MQTT_PASSWORD"))
    plain.add_argument("--tls", action="store_true")

    return p.parse_args()


def main() -> int:
    args = _parse_args()
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=args.client_id,
    )
    client.on_message = on_message

    if args.iot_endpoint and args.root_ca and args.cert and args.key:
        host = args.iot_endpoint.replace("https://", "").strip("/")
        client.tls_set(
            ca_certs=args.root_ca,
            certfile=args.cert,
            keyfile=args.key,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
        client.tls_insecure_set(False)
        client.connect(host, 8883, keepalive=60)
        print(f"[sim] AWS IoT Core {host}:8883 subscribe {args.topic}", flush=True)
    else:
        if args.user:
            client.username_pw_set(args.user, args.password or "")
        if args.tls:
            client.tls_set()
        client.connect(args.host, args.port, keepalive=60)
        print(f"[sim] connected to {args.host}:{args.port}, subscribed {args.topic}", flush=True)

    client.subscribe(args.topic, qos=1)
    client.loop_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
