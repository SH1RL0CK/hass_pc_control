import asyncio
import json
import logging
import os
import platform
import subprocess

import psutil
from aiomqtt import Client
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("pc_agent")

HOMEASSISTANT_HOST = os.environ["HOMEASSISTANT_HOST"]
MQTT_USERNAME = os.environ["MQTT_USERNAME"]
MQTT_PASSWORD = os.environ["MQTT_PASSWORD"]


async def send_on_state(client: Client, current_os: str, not_current_os: str):
    await client.publish(f"pc/{current_os}/get", "ON")
    await client.publish(f"pc/{not_current_os}/get", "OFF")
    await client.publish("pc/info/availability", "online")


async def send_off_state(client: Client, current_os: str, not_current_os: str):
    await client.publish(f"pc/{current_os}/get", "OFF")
    await client.publish(f"pc/{not_current_os}/get", "OFF")
    await client.publish("pc/info/get", json.dumps({"cpu": 0, "memory": 0}))
    await client.publish("pc/info/availability", "offline")


async def send_pc_data(client: Client):
    while True:
        pc_data = {
            "cpu": psutil.cpu_percent(),
            "memory": psutil.virtual_memory().percent,
        }
        await client.publish("pc/info/get", json.dumps(pc_data))
        await asyncio.sleep(5)


async def main():
    current_os = platform.system().lower()
    not_current_os = "linux" if current_os == "windows" else "windows"
    send_pc_data_task = None

    while True:
        try:
            async with Client(
                HOMEASSISTANT_HOST,
                username=MQTT_USERNAME,
                password=MQTT_PASSWORD,
            ) as client:
                await client.subscribe("pc/linux/set")
                await client.subscribe("pc/windows/set")

                await send_on_state(client, current_os, not_current_os)
                send_pc_data_task = asyncio.create_task(send_pc_data(client))

                async for message in client.messages:
                    log.info("Received: %s = %s", message.topic, message.payload)
                    topic = str(message.topic)

                    if current_os in topic:
                        # Command targets current OS
                        if message.payload == b"OFF":
                            send_pc_data_task.cancel()
                            await send_off_state(client, current_os, not_current_os)
                            if current_os == "linux":
                                os.system("sudo poweroff")
                            else:
                                os.system("shutdown /s /f /t 0")
                        else:
                            await send_on_state(client, current_os, not_current_os)
                    else:
                        # Command targets the other OS → reboot into it
                        if message.payload == b"ON":
                            send_pc_data_task.cancel()
                            await send_off_state(client, current_os, not_current_os)
                            if current_os == "linux":
                                os.system("sudo reboot")
                            else:
                                os.system("shutdown /r /f /t 0")
                        else:
                            await send_on_state(client, current_os, not_current_os)
        except Exception as e:
            log.error("Connection error: %s – retrying in 1s", e)
            if send_pc_data_task is not None:
                send_pc_data_task.cancel()
            await asyncio.sleep(1)


if __name__ == "__main__":
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore
    asyncio.run(main())
