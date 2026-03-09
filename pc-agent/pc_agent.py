import asyncio
import json
import logging
import os
import platform

import psutil
from aiomqtt import Client
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("pc_agent")

# --- Configuration ---
MQTT_HOST = os.environ["MQTT_HOST"]
MQTT_USERNAME = os.environ["MQTT_USERNAME"]
MQTT_PASSWORD = os.environ["MQTT_PASSWORD"]

TOPIC_LINUX_SET = os.environ.get("TOPIC_LINUX_SET", "pc/linux/set")
TOPIC_LINUX_GET = os.environ.get("TOPIC_LINUX_GET", "pc/linux/get")
TOPIC_WINDOWS_SET = os.environ.get("TOPIC_WINDOWS_SET", "pc/windows/set")
TOPIC_WINDOWS_GET = os.environ.get("TOPIC_WINDOWS_GET", "pc/windows/get")
TOPIC_INFO = os.environ.get("TOPIC_INFO", "pc/info/get")
TOPIC_AVAILABILITY = os.environ.get("TOPIC_AVAILABILITY", "pc/info/availability")

PC_DATA_INTERVAL = int(os.environ.get("PC_DATA_INTERVAL", "5"))
RECONNECT_DELAY = int(os.environ.get("RECONNECT_DELAY", "1"))

PAYLOAD_ON = b"ON"
PAYLOAD_OFF = b"OFF"
STATE_ON = "ON"
STATE_OFF = "OFF"
STATE_ONLINE = "online"
STATE_OFFLINE = "offline"

OS_LINUX = "linux"
OS_WINDOWS = "windows"

# Map OS name → topics
TOPICS = {
    OS_LINUX: {"set": TOPIC_LINUX_SET, "get": TOPIC_LINUX_GET},
    OS_WINDOWS: {"set": TOPIC_WINDOWS_SET, "get": TOPIC_WINDOWS_GET},
}


async def publish_state(
    client: Client, current_os: str, other_os: str, online: bool
) -> None:
    """Publish current PC state to MQTT."""
    if online:
        await client.publish(TOPICS[current_os]["get"], STATE_ON)
        await client.publish(TOPICS[other_os]["get"], STATE_OFF)
        await client.publish(TOPIC_AVAILABILITY, STATE_ONLINE)
    else:
        await client.publish(TOPICS[current_os]["get"], STATE_OFF)
        await client.publish(TOPICS[other_os]["get"], STATE_OFF)
        await client.publish(TOPIC_INFO, json.dumps({"cpu": 0, "memory": 0}))
        await client.publish(TOPIC_AVAILABILITY, STATE_OFFLINE)


async def send_pc_data(client: Client) -> None:
    """Periodically publish CPU and memory usage."""
    while True:
        data = {
            "cpu": psutil.cpu_percent(),
            "memory": psutil.virtual_memory().percent,
        }
        await client.publish(TOPIC_INFO, json.dumps(data))
        await asyncio.sleep(PC_DATA_INTERVAL)


def shutdown(current_os: str) -> None:
    """Shut down the PC."""
    if current_os == OS_LINUX:
        os.system("sudo poweroff")
    else:
        os.system("shutdown /s /f /t 0")


def reboot(current_os: str) -> None:
    """Reboot the PC."""
    if current_os == OS_LINUX:
        os.system("sudo reboot")
    else:
        os.system("shutdown /r /f /t 0")


async def main() -> None:
    current_os = platform.system().lower()
    other_os = OS_LINUX if current_os == OS_WINDOWS else OS_WINDOWS
    pc_data_task: asyncio.Task | None = None

    while True:
        try:
            async with Client(
                MQTT_HOST, username=MQTT_USERNAME, password=MQTT_PASSWORD
            ) as client:
                await client.subscribe(TOPIC_LINUX_SET)
                await client.subscribe(TOPIC_WINDOWS_SET)
                log.info(
                    "Connected to %s, subscribed to %s and %s",
                    MQTT_HOST,
                    TOPIC_LINUX_SET,
                    TOPIC_WINDOWS_SET,
                )

                await publish_state(client, current_os, other_os, online=True)
                pc_data_task = asyncio.create_task(send_pc_data(client))

                async for message in client.messages:
                    topic = str(message.topic)
                    log.info("Received: %s = %s", topic, message.payload)

                    if current_os in topic:
                        if message.payload == PAYLOAD_OFF:
                            pc_data_task.cancel()
                            await publish_state(
                                client, current_os, other_os, online=False
                            )
                            shutdown(current_os)
                        else:
                            await publish_state(
                                client, current_os, other_os, online=True
                            )
                    else:
                        if message.payload == PAYLOAD_ON:
                            pc_data_task.cancel()
                            await publish_state(
                                client, current_os, other_os, online=False
                            )
                            reboot(current_os)
                        else:
                            await publish_state(
                                client, current_os, other_os, online=True
                            )

        except Exception as e:
            log.error("Connection error: %s – retrying in %ds", e, RECONNECT_DELAY)
            if pc_data_task is not None:
                pc_data_task.cancel()
            await asyncio.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore
    asyncio.run(main())
