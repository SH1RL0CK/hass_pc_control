import asyncio
import json
import os
import platform
import subprocess

import psutil
from aiomqtt import Client
from dotenv import load_dotenv

load_dotenv()

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


async def send_audio_output(client: Client, current_os: str):
    pulse = None
    if current_os == "linux":
        pulse = pulsectl.Pulse()  # type: ignore
    while True:
        try:
            if current_os == "linux":
                current_audio_output = pulse.server_info().default_sink_name.replace("_", " ")  # type: ignore
                if "HyperX Cloud Alpha Wireless" in current_audio_output:
                    await client.publish("pc/audio_output/get", "ON")
                elif "AB13X USB Audio" in current_audio_output:
                    await client.publish("pc/audio_output/get", "OFF")
            else:
                result = subprocess.run(
                    ["powershell", "-Command", "Get-AudioDevice", "-Playback"],
                    stdout=subprocess.PIPE,
                )
                result = result.stdout.splitlines()
                print(result)
                for line in result:
                    if b"Name" in line:
                        if b"Kopf" in line:
                            await client.publish("pc/audio_output/get", "ON")
                            print("Kopfhörer")
                        elif b"Lautsprecher" in line:
                            await client.publish("pc/audio_output/get", "OFF")
                            print("Lautsprecher")

        except Exception as e:
            print(e)
        await asyncio.sleep(5)


async def main():
    current_os = platform.system().lower()
    not_current_os = "linux" if current_os == "windows" else "windows"
    send_pc_data_task = None
    # send_audio_output_task = None

    while True:
        try:
            async with Client(
                HOMEASSISTANT_HOST,
                username=MQTT_USERNAME,
                password=MQTT_PASSWORD,
            ) as client:
                await client.subscribe("pc/linux/set")
                await client.subscribe("pc/windows/set")
                await client.subscribe("pc/audio_output/set")

                await send_on_state(client, current_os, not_current_os)
                send_pc_data_task = asyncio.create_task(send_pc_data(client))
                # send_audio_output_task = asyncio.create_task(
                #     send_audio_output(client, current_os)
                # )
                # pulse = None
                # if current_os == "linux":
                #     pulse = pulsectl.Pulse()  # type: ignore

                async for message in client.messages:
                    print(message)
                    topic = str(message.topic)
                    # if "audio_output" in topic:
                    #     if message.payload == b"ON":
                    #         if current_os == "linux" and pulse is not None:
                    #             for sink in pulse.sink_list():
                    #                 if (
                    #                     "HyperX Cloud Alpha Wireless"
                    #                     in sink.description
                    #                 ):
                    #                     pulse.sink_default_set(sink)
                    #                     break
                    #         else:
                    #             os.system("nircmd setdefaultsounddevice Kopfhörer")
                    #     else:
                    #         if message.payload == b"OFF":
                    #             if current_os == "linux" and pulse is not None:
                    #                 pulse = pulsectl.Pulse()  # type: ignore
                    #                 for sink in pulse.sink_list():
                    #                     if "AB13X USB Audio" in sink.description:
                    #                         pulse.sink_default_set(sink)
                    #                         break
                    #             else:
                    #                 os.system(
                    #                     "nircmd setdefaultsounddevice Lautsprecher"
                    #                 )
                    #     await client.publish("pc/audio_output/get", message.payload)
                    if current_os in topic:
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
                        if message.payload == b"ON":
                            send_pc_data_task.cancel()
                            await send_off_state(client, current_os, not_current_os)
                            if current_os == "linux":
                                os.system("sudo reboot")
                            else:
                                os.system("shutdown /r /f /t 0")
                        else:
                            await send_on_state(client, current_os, not_current_os)
        except Exception:
            if send_pc_data_task is not None:
                send_pc_data_task.cancel()
            # if send_audio_output_task is not None:
            #     send_audio_output_task.cancel()
            await asyncio.sleep(1)


if __name__ == "__main__":
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore
    asyncio.run(main())
