import asyncio
import logging
import os
import threading

import tftpy
from aiomqtt import Client
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("grub_boot_selector")

HOMEASSISTANT_HOST = os.environ["HOMEASSISTANT_HOST"]
MQTT_USERNAME = os.environ["MQTT_USERNAME"]
MQTT_PASSWORD = os.environ["MQTT_PASSWORD"]
TFTP_DIR = os.environ.get("TFTP_DIR", "/tftp")
GRUB_LINUX_ENTRY = os.environ.get("GRUB_LINUX_ENTRY", "0")
GRUB_WINDOWS_ENTRY = os.environ.get("GRUB_WINDOWS_ENTRY", "2")
GRUB_TIMEOUT = os.environ.get("GRUB_TIMEOUT", "3")

current_boot_target = "linux"


def write_grub_conf(target_os: str) -> None:
    """Write the GRUB config file that will be served via TFTP."""
    global current_boot_target
    entry = GRUB_LINUX_ENTRY if target_os == "linux" else GRUB_WINDOWS_ENTRY
    grub_conf_path = os.path.join(TFTP_DIR, "grub_conf")

    content = f'set default="{entry}"\nset timeout={GRUB_TIMEOUT}\n'

    os.makedirs(TFTP_DIR, exist_ok=True)
    with open(grub_conf_path, "w") as f:
        f.write(content)

    current_boot_target = target_os
    log.info("GRUB config updated: boot target = %s (entry %s)", target_os, entry)


def start_tftp_server() -> None:
    """Start the TFTP server in a background thread."""
    os.makedirs(TFTP_DIR, exist_ok=True)
    server = tftpy.TftpServer(TFTP_DIR)
    log.info("Starting TFTP server on 0.0.0.0:69, serving %s", TFTP_DIR)
    server.listen("0.0.0.0", 69)


async def main() -> None:
    # Write default grub config
    write_grub_conf("linux")

    # Start TFTP server in background thread
    tftp_thread = threading.Thread(target=start_tftp_server, daemon=True)
    tftp_thread.start()

    log.info("Connecting to MQTT at %s ...", HOMEASSISTANT_HOST)

    while True:
        try:
            async with Client(
                HOMEASSISTANT_HOST,
                username=MQTT_USERNAME,
                password=MQTT_PASSWORD,
            ) as client:
                await client.subscribe("pc/linux/set")
                await client.subscribe("pc/windows/set")
                log.info(
                    "MQTT connected, subscribed to pc/linux/set and pc/windows/set"
                )

                async for message in client.messages:
                    payload = message.payload.decode().strip().upper()  # type: ignore
                    topic = str(message.topic)
                    log.info("Received MQTT message: %s = %s", topic, payload)

                    if payload == "ON":
                        if "linux" in topic:
                            write_grub_conf("linux")
                        elif "windows" in topic:
                            write_grub_conf("windows")

        except Exception as e:
            log.error("MQTT connection error: %s – retrying in 5s", e)
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
