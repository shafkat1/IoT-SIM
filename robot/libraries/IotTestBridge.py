"""Robot Framework library: MQTT (optional) + AWS IoT Core publish + S3 poll/compare."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Dict, Optional

import paho.mqtt.client as mqtt

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore[misc, assignment]
    ClientError = Exception  # type: ignore[misc, assignment]


class IotTestBridge:
    """Keywords for simulator commands (MQTT or AWS IoT) and S3-backed result JSON."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(self) -> None:
        self._mqtt_client: Optional[mqtt.Client] = None
        self._mqtt_lock = threading.Lock()
        self._iot_data = None
        self._s3 = None
        self._s3_region: Optional[str] = None

    # --- Optional: generic MQTT (e.g. private broker on VPC) ---

    def connect_mqtt(
        self,
        host: str,
        port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
        tls: bool = False,
    ) -> None:
        """Open a persistent MQTT connection (TLS optional)."""
        with self._mqtt_lock:
            if self._mqtt_client:
                self._mqtt_client.loop_stop()
                self._mqtt_client.disconnect()
                self._mqtt_client = None
            client_id = f"robot-ec2-{uuid.uuid4().hex[:8]}"
            self._mqtt_client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=client_id,
            )
            if username is not None:
                self._mqtt_client.username_pw_set(username, password or "")
            if tls:
                self._mqtt_client.tls_set()
            self._mqtt_client.connect(host, port, keepalive=60)
            self._mqtt_client.loop_start()

    def disconnect_mqtt(self) -> None:
        with self._mqtt_lock:
            if self._mqtt_client:
                self._mqtt_client.loop_stop()
                self._mqtt_client.disconnect()
                self._mqtt_client = None

    def publish_iot_step(
        self,
        topic: str,
        device_id: str,
        scenario_id: str,
        step_id: str,
        payload: Any,
        qos: int = 1,
        retain: bool = False,
    ) -> str:
        """
        Publish one test step over the **generic MQTT** connection.
        ``payload`` may be a dict/list or a JSON string.
        Returns ``run_id`` (UUID) embedded in the message body.
        """
        if self._mqtt_client is None:
            raise RuntimeError("Call Connect Mqtt first.")
        body, data = self._build_step_envelope(device_id, scenario_id, step_id, payload)
        info = self._mqtt_client.publish(topic, data, qos=qos, retain=retain)
        info.wait_for_publish(timeout=30)
        return body["run_id"]

    # --- AWS IoT Core (recommended from EC2 with instance role / env creds) ---

    def configure_aws_iot_publisher(
        self,
        data_endpoint: str,
        region: Optional[str] = None,
    ) -> None:
        """
        Use AWS IoT Data plane to publish MQTT messages to topics devices subscribe to.

        ``data_endpoint`` is the account IoT data ATS hostname, e.g.
        ``a1b2c3d4e5f6g7-ats.iot.us-east-1.amazonaws.com`` (no ``https://``).
        IAM on EC2 needs ``iot:Publish`` on the target topic ARN(s).
        """
        if boto3 is None:
            raise RuntimeError("Install boto3 to use AWS IoT publishing.")
        region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        if not region:
            region = boto3.session.Session().region_name
        if not region:
            raise RuntimeError("Pass region= or set AWS_REGION / AWS_DEFAULT_REGION.")
        ep = data_endpoint.strip()
        if not ep.startswith("https://"):
            ep = f"https://{ep}"
        self._iot_data = boto3.client("iot-data", endpoint_url=ep, region_name=region)

    def publish_iot_step_aws(
        self,
        topic: str,
        device_id: str,
        scenario_id: str,
        step_id: str,
        payload: Any,
        qos: int = 1,
    ) -> str:
        """
        Publish one test step via **AWS IoT Core** (no local MQTT socket).
        Same JSON envelope as ``Publish Iot Step``.
        """
        if self._iot_data is None:
            ep = os.environ.get("AWS_IOT_DATA_ENDPOINT")
            if not ep:
                raise RuntimeError(
                    "Call Configure Aws Iot Publisher first or set AWS_IOT_DATA_ENDPOINT."
                )
            self.configure_aws_iot_publisher(ep)
        body, data = self._build_step_envelope(device_id, scenario_id, step_id, payload)
        self._iot_data.publish(topic=topic, qos=qos, payload=data.decode("utf-8"))
        return body["run_id"]

    # --- Amazon S3 (result JSON written by IoT Rules, Lambda, or your pipeline) ---

    def configure_aws_s3(self, region: Optional[str] = None) -> None:
        """Create an S3 client using the default credential chain (EC2 instance role, env, profile)."""
        if boto3 is None:
            raise RuntimeError("Install boto3 to use S3.")
        self._s3_region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        if not self._s3_region:
            self._s3_region = boto3.session.Session().region_name
        kwargs: Dict[str, Any] = {}
        if self._s3_region:
            kwargs["region_name"] = self._s3_region
        self._s3 = boto3.client("s3", **kwargs)

    def wait_for_result_s3(
        self,
        bucket: str,
        key: str,
        poll_seconds: float = 120.0,
        timeout_seconds: float = 3600.0,
    ) -> str:
        """
        Poll until ``s3://bucket/key`` exists, then return object body as UTF-8 text.
        Typical key: ``{device_id}_{scenario_id}.json`` (match your IoT Rule prefix).
        """
        if self._s3 is None:
            self.configure_aws_s3()
        deadline = time.monotonic() + timeout_seconds
        last_err: Optional[Exception] = None
        while time.monotonic() < deadline:
            try:
                resp = self._s3.get_object(Bucket=bucket, Key=key)
                return resp["Body"].read().decode("utf-8")
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in ("404", "NoSuchKey", "NotFound"):
                    last_err = exc
                    time.sleep(poll_seconds)
                    continue
                raise
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(poll_seconds)
        msg = f"S3 object not found in time: s3://{bucket}/{key}"
        if last_err:
            msg += f" (last error: {last_err})"
        raise AssertionError(msg)

    # --- Assertions ---

    def compare_json_to_expected(
        self,
        actual_json: str,
        expected: Any,
        ignore_order: bool = False,
    ) -> None:
        """
        Compare parsed JSON to expected structure.
        ``expected`` may be dict/list or JSON string. Uses DeepDiff for rich diffs.
        """
        from deepdiff import DeepDiff

        actual = json.loads(actual_json)
        exp = expected if not isinstance(expected, str) else json.loads(expected)
        diff = DeepDiff(
            exp,
            actual,
            ignore_order=ignore_order,
            report_repetition=True,
        )
        if diff:
            raise AssertionError(f"JSON mismatch:\n{diff.pretty()}")

    # --- Internals ---

    @staticmethod
    def _build_step_envelope(
        device_id: str,
        scenario_id: str,
        step_id: str,
        payload: Any,
    ) -> tuple[Dict[str, Any], bytes]:
        run_id = str(uuid.uuid4())
        body: Dict[str, Any] = {
            "run_id": run_id,
            "device_id": device_id,
            "scenario_id": scenario_id,
            "step_id": step_id,
            "values": payload if not isinstance(payload, str) else json.loads(payload),
        }
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        return body, data
