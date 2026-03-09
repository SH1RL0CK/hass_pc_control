# hass_pc_control

Fully control a dual-boot PC (Linux/Windows) from **Home Assistant** via MQTT – including power management and automatic GRUB boot selection.

## Overview

```
┌─────────────────────┐         MQTT          ┌──────────────────────────┐
│   Home Assistant     │◄────────────────────► │  boot-selector (Docker)  │
│                      │                       │  • MQTT Listener         │
│  Switches:           │         MQTT          │  • TFTP Server (:69)     │
│  - pc/linux/set      │◄──────────────────►   └──────────┬───────────────┘
│  - pc/windows/set    │                                  │ TFTP
│                      │                                  ▼
│                      │         MQTT          ┌──────────────────────────┐
│  Sensors:            │◄────────────────────► │  pc-agent (on the PC)    │
│  - pc/info/get       │                       │  • CPU / RAM Monitoring  │
│  - pc/info/avail.    │                       │  • Shutdown / Reboot     │
└─────────────────────┘                       └──────────────────────────┘
```

The project consists of **three components**:

| Folder                             | Description                                                             | Runs on                               |
| ---------------------------------- | ----------------------------------------------------------------------- | ------------------------------------- |
| [`pc-agent/`](pc-agent/)           | Agent on the PC – reports status, performs shutdown/reboot              | Dual-boot PC (Linux & Windows)        |
| [`boot-selector/`](boot-selector/) | MQTT→GRUB bridge – receives boot target and serves `grub_conf` via TFTP | Server / Home Assistant host (Docker) |
| [`grub/`](grub/)                   | GRUB configuration – loads boot config via TFTP                         | Dual-boot PC (GRUB)                   |

---

## Flow: Switching OS

1. **Home Assistant** sends `ON` to `pc/windows/set` (or `pc/linux/set`)
2. Both **boot-selector** and **pc-agent** receive the message via MQTT
3. **boot-selector** writes `grub_conf` with the matching GRUB entry
4. **pc-agent** reboots the PC
5. **GRUB** loads `grub_conf` via TFTP → boots the selected OS

---

## 1. boot-selector (Docker)

MQTT listener + TFTP server running as a Docker container. Runs on your server (e.g. the Home Assistant host).

### Setup

```bash
cd boot-selector
cp .env.example .env
# Edit .env (MQTT credentials, GRUB entries)
docker compose up -d --build
```

### Environment Variables

| Variable             | Description                           | Default          |
| -------------------- | ------------------------------------- | ---------------- |
| `MQTT_HOST`          | MQTT broker IP / hostname             | –                |
| `MQTT_USERNAME`      | MQTT username                         | –                |
| `MQTT_PASSWORD`      | MQTT password                         | –                |
| `TOPIC_LINUX_SET`    | MQTT topic for Linux switch           | `pc/linux/set`   |
| `TOPIC_WINDOWS_SET`  | MQTT topic for Windows switch         | `pc/windows/set` |
| `GRUB_LINUX_ENTRY`   | GRUB menu index for Linux (0-based)   | `0`              |
| `GRUB_WINDOWS_ENTRY` | GRUB menu index for Windows (0-based) | `2`              |
| `GRUB_TIMEOUT`       | GRUB timeout in seconds               | `3`              |
| `GRUB_DEFAULT_BOOT`  | Default boot target on startup        | `linux`          |

> **Tip:** Find your GRUB entry indices with `awk -F\' '/menuentry / {print NR-1, $2}' /boot/grub/grub.cfg`

### MQTT Topics

| Topic            | Direction          | Payload | Description                |
| ---------------- | ------------------ | ------- | -------------------------- |
| `pc/linux/set`   | HA → boot-selector | `ON`    | Set boot target to Linux   |
| `pc/windows/set` | HA → boot-selector | `ON`    | Set boot target to Windows |

---

## 2. pc-agent (Systemd Service)

Runs directly on the dual-boot PC as a systemd service (Linux) or scheduled task (Windows).

### Setup (Linux)

```bash
cd pc-agent
pip install -r requirements.txt
cp .env.example .env
# Edit .env

# Install service
sudo cp pc_agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pc_agent
```

### Setup (Windows)

```powershell
cd pc-agent
pip install -r requirements.txt
copy .env.example .env
# Edit .env
# Set up autostart (Task Scheduler or NSSM)
```

### Environment Variables

| Variable             | Description                   | Default                |
| -------------------- | ----------------------------- | ---------------------- |
| `MQTT_HOST`          | MQTT broker IP / hostname     | –                      |
| `MQTT_USERNAME`      | MQTT username                 | –                      |
| `MQTT_PASSWORD`      | MQTT password                 | –                      |
| `TOPIC_LINUX_SET`    | MQTT topic for Linux switch   | `pc/linux/set`         |
| `TOPIC_LINUX_GET`    | MQTT topic for Linux state    | `pc/linux/get`         |
| `TOPIC_WINDOWS_SET`  | MQTT topic for Windows switch | `pc/windows/set`       |
| `TOPIC_WINDOWS_GET`  | MQTT topic for Windows state  | `pc/windows/get`       |
| `TOPIC_INFO`         | MQTT topic for PC usage data  | `pc/info/get`          |
| `TOPIC_AVAILABILITY` | MQTT topic for availability   | `pc/info/availability` |
| `PC_DATA_INTERVAL`   | Seconds between usage updates | `5`                    |
| `RECONNECT_DELAY`    | Seconds before MQTT reconnect | `1`                    |

### MQTT Topics

| Topic                  | Direction | Payload                   | Description                   |
| ---------------------- | --------- | ------------------------- | ----------------------------- |
| `pc/linux/set`         | HA → PC   | `ON` / `OFF`              | Boot into Linux / shut down   |
| `pc/windows/set`       | HA → PC   | `ON` / `OFF`              | Boot into Windows / shut down |
| `pc/linux/get`         | PC → HA   | `ON` / `OFF`              | Linux status                  |
| `pc/windows/get`       | PC → HA   | `ON` / `OFF`              | Windows status                |
| `pc/info/get`          | PC → HA   | `{"cpu": %, "memory": %}` | PC usage (every 5s)           |
| `pc/info/availability` | PC → HA   | `online` / `offline`      | Availability                  |

---

## 3. GRUB Configuration

The file [`grub/40_custom`](grub/40_custom) is installed on the dual-boot PC. It makes GRUB load its boot configuration via TFTP from the boot-selector server.

### Installation

```bash
sudo cp grub/40_custom /etc/grub.d/40_custom
sudo chmod +x /etc/grub.d/40_custom
sudo grub-mkconfig -o /boot/grub/grub.cfg
```

### Configuration

Edit the network addresses in `40_custom` before installing:

```
net_add_addr efinet1:link efinet1 <PC_IP>              # Static IP for this PC
source (tftp,<BOOT_SELECTOR_IP>)/grub_conf             # IP of the boot-selector server
```

---

## Project Structure

```
hass_pc_control/
├── boot-selector/                # Docker: MQTT → GRUB Config → TFTP
│   ├── grub_boot_selector.py
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── .env.example
├── pc-agent/                     # Systemd: PC Status & Power Control
│   ├── pc_agent.py
│   ├── requirements.txt
│   ├── pc_agent.service
│   └── .env.example
├── grub/                         # GRUB: TFTP Boot-Config Loader
│   └── 40_custom
├── .gitignore
└── README.md
```

## Prerequisites

- **Server:** Docker + Docker Compose, MQTT broker (e.g. Mosquitto in HA)
- **PC:** Python 3.10+, systemd (Linux) or Task Scheduler (Windows)
- **Network:** PC and server on the same network, port 69/UDP (TFTP) open
- **GRUB:** EFI network support (`efinet` module)

## License

MIT
