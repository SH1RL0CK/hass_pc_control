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

# --- Configuration ---
MQTT_HOST = os.environ["MQTT_HOST"]
MQTT_USERNAME = os.environ["MQTT_USERNAME"]
MQTT_PASSWORD = os.environ["MQTT_PASSWORD"]

TOPIC_LINUX_SET = os.environ.get("TOPIC_LINUX_SET", "pc/linux/set")
TOPIC_WINDOWS_SET = os.environ.get("TOPIC_WINDOWS_SET", "pc/windows/set")

TFTP_DIR = os.environ.get("TFTP_DIR", "/tftp")
TFTP_HOST = os.environ.get("TFTP_HOST", "0.0.0.0")
TFTP_PORT = int(os.environ.get("TFTP_PORT", "69"))
GRUB_CONF_FILENAME = "grub_conf"

GRUB_LINUX_ENTRY = os.environ.get("GRUB_LINUX_ENTRY", "0")
GRUB_WINDOWS_ENTRY = os.environ.get("GRUB_WINDOWS_ENTRY", "2")
GRUB_TIMEOUT = os.environ.get("GRUB_TIMEOUT", "3")
GRUB_DEFAULT_BOOT = os.environ.get("GRUB_DEFAULT_BOOT", "linux")

RECONNECT_DELAY = int(os.environ.get("RECONNECT_DELAY", "5"))

PAYLOAD_ON = "ON"

OS_LINUX = "linux"
OS_WINDOWS = "windows"

# Map OS name → GRUB entry index
GRUB_ENTRIES = {
    OS_LINUX: GRUB_LINUX_ENTRY,
    OS_WINDOWS: GRUB_WINDOWS_ENTRY,
}

# Map topic → OS name
TOPIC_TO_OS = {
    TOPIC_LINUX_SET: OS_LINUX,
    TOPIC_WINDOWS_SET: OS_WINDOWS,
}

current_boot_target = GRUB_DEFAULT_BOOT


def write_grub_conf(target_os: str) -> None:
    """Write the GRUB config file that will be served via TFTP."""
    global current_boot_target
    entry = GRUB_ENTRIES[target_os]
    grub_conf_path = os.path.join(TFTP_DIR, GRUB_CONF_FILENAME)

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
    log.info(
        "Starting TFTP server on %s:%d, serving %s", TFTP_HOST, TFTP_PORT, TFTP_DIR
    )
    server.listen(TFTP_HOST, TFTP_PORT)


async def main() -> None:
    write_grub_conf(GRUB_DEFAULT_BOOT)

    tftp_thread = threading.Thread(target=start_tftp_server, daemon=True)
    tftp_thread.start()

    log.info("Connecting to MQTT at %s ...", MQTT_HOST)

    while True:
        try:
            async with Client(
                MQTT_HOST, username=MQTT_USERNAME, password=MQTT_PASSWORD
            ) as client:
                await client.subscribe(TOPIC_LINUX_SET)
                await client.subscribe(TOPIC_WINDOWS_SET)
                log.info(
                    "MQTT connected, subscribed to %s and %s",
                    TOPIC_LINUX_SET,
                    TOPIC_WINDOWS_SET,
                )

                async for message in client.messages:
                    payload = message.payload.decode().strip().upper()  # type: ignore
                    topic = str(message.topic)
                    log.info("Received: %s = %s", topic, payload)

                    if payload == PAYLOAD_ON:
                        target_os = TOPIC_TO_OS.get(topic)
                        if target_os:
                            write_grub_conf(target_os)
                        else:
                            log.warning("Unknown topic: %s", topic)

        except Exception as e:
            log.error("MQTT connection error: %s – retrying in %ds", e, RECONNECT_DELAY)
            await asyncio.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    asyncio.run(main())
