
# BitTorrent CLI Application

This is a BitTorrent client simulation supporting basic torrenting operations: tracker setup, torrent file creation, seeding, and leeching. It mimics classic BitTorrent behavior via a command-line interface.

---

## 📦 Project Structure

```
.
├── BitTorrent_CLI.py       # Main entry CLI to control and run all commands
├── Peer.py                 # Logic for peers (seeders and leechers)
├── Tracker.py              # Tracker server handling peer announcements
├── torrent_file.py         # Torrent file creation and parsing logic
└── Sim/                    # Contains simulation peers and file storage
```

---

## 🛠 Prerequisites

- Python 3.8+
- Required packages: `keyboard`, `bencodepy`, `bitarray`, `requests`

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## 🚀 How to Run

### 1. **Start the CLI Shell**

Before using any other command, launch the BitTorrent CLI interface:

```bash
python BitTorrent_CLI.py
```

This opens an interactive shell where you can type commands like `torrent-create`, `torrent-tracker`, etc.

---

## 🧭 Usage Guide

### ➤ Create a Torrent File (Seeder)

```bash
torrent-create -id <sim_peer_id> -f <filename> -url <tracker_url>
```

Example:

```bash
torrent-create -id 1 -f ubuntu.iso -url http://127.0.0.1:6882/announce
```

---

### ➤ Start the Tracker

```bash
torrent-tracker -p 6882 -ip 127.0.0.1
```

---

### ➤ Start a Seeder

```bash
torrent-seed -id <sim_peer_id> -ip <ip> -p <port> -f <torrent_file> -url <tracker_url>
```

Example:

```bash
torrent-seed -id 1 -ip 127.0.0.1 -p 5001 -f ubuntu.iso.torrent -url http://127.0.0.1:6882/announce
```

---

### ➤ Start a Leecher

```bash
torrent-leech -id <sim_peer_id> -ip <ip> -p <port> -f <torrent_file> -url <tracker_url>
```

Example:

```bash
torrent-leech -id 2 -ip 127.0.0.1 -p 5002 -f ubuntu.iso.torrent -url http://127.0.0.1:6882/announce
```

---

### ➤ Show Torrent Info

```bash
torrent-show -id <sim_peer_id> -f <torrent_file>
```

---

### ➤ List All Torrent Files for a Peer

```bash
torrent-fetch -id <sim_peer_id>
```

Or list for **all** peers:

```bash
torrent-fetch
```

---

### ➤ Stop All Peers Gracefully

```bash
torrent-leave
```

---

## 🧪 Notes

- All file paths are relative to the `Sim/<id>/File` structure.
- `.torrent` files and raw files must be correctly placed in corresponding folders.
- Ensure that `torrent_file.py` is invoked properly within the CLI commands.

---

## 📄 License

MIT License
