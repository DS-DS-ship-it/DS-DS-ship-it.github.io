# MVX MeshBridge 1.1.0

MVX MeshBridge is an offline-first peer-to-peer mesh networking engine designed
for low-latency communication, relay networking, store-and-forward messaging,
file transfer, and future multi-transport integration.

## Current native build
The current published binary is:
- macOS Apple Silicon / ARM64
- Nuitka onefile executable
- Python optimization enabled
- LTO enabled
- standalone native executable
- tested before publication

## Download
Latest macOS ARM64 release:
https://github.com/DS-DS-ship-it/DS-DS-ship-it.github.io/releases/latest/download/MVX-MeshBridge-macos-arm64.zip

## Run
After extracting the ZIP:
```bash
./MVX-MeshBridge-macos-arm64 node
```

## Current networking
The current MeshBridge engine includes:
- TCP LAN transport
- UDP discovery
- peer discovery
- Ed25519 node identity
- X25519 key exchange
- ChaCha20-Poly1305 encryption
- HKDF key derivation
- SQLite WAL persistence
- multi-hop routing
- TTL handling
- duplicate suppression
- priority queues
- store-and-forward
- gateway fetch
- file transfer
- ping
- peer inspection
- route inspection
- interactive console
- TCP_NODELAY
- socket buffer tuning
- tracked background tasks
- clean shutdown

## Architecture direction
Future transports can be added behind the MeshBridge transport layer,
including:
- Wi-Fi
- Wi-Fi Direct
- Bluetooth LE
- LoRa
- Meshtastic-compatible radios
- Ethernet
- additional native Apple transports

The current macOS binary is a native desktop executable. It does not run
directly inside Safari or an iPhone HTML page.
The web page can serve as a project/control interface while the native
MeshBridge engine performs the networking work.

## GitHub Pages
https://DS-DS-ship-it.github.io/iphone-html-terminal/mvx-spatial-mosaic-v3/MVX_MeshBridge.html

## Source
The published Python source is included in this directory as:
`mvx_meshbridge.py`

## Version
1.1.0

## Build date
2026-09-13 22:15:50 EDT
