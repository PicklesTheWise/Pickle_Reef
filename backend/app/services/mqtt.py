import asyncio
import logging

import paho.mqtt.client as mqtt

from ..core.config import settings

logger = logging.getLogger(__name__)


async def mqtt_bootstrap() -> None:
    """Establish a background MQTT connection for module coordination."""

    loop = asyncio.get_event_loop()

    def on_connect(client: mqtt.Client, userdata, flags, rc):  # type: ignore[no-untyped-def]
        if rc == 0:
            logger.info("Connected to MQTT broker")
            client.subscribe(f"{settings.mqtt_topic_prefix}/#")
        else:
            logger.error("MQTT connection failed with rc=%s", rc)

    def on_message(client: mqtt.Client, userdata, msg):  # type: ignore[no-untyped-def]
        logger.debug("MQTT message: %s %s", msg.topic, msg.payload)

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    def run_client():
        try:
            client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=60)
            client.loop_forever()
        except OSError as exc:  # DNS failures, refused connections, etc.
            logger.warning("MQTT bridge disabled: %s", exc)

    try:
        await loop.run_in_executor(None, run_client)
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("MQTT bootstrap stopped early: %s", exc)
