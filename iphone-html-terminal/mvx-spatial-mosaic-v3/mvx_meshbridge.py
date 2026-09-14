#!/usr/bin/env python3

"""

MVX MeshBridge 1.1

==================

High-performance, encrypted, peer-to-peer mesh networking engine.

Designed as the foundation for:

    * Gaming / low-latency traffic

    * Local P2P networking

    * Offline communications

    * Store-and-forward "sneakernet"

    * Internet gateway relaying

    * File synchronization

    * Future Bluetooth LE transport

    * Future Wi-Fi Direct transport

    * Future LoRa / Meshtastic transport

    * Future iOS / Android native transport

Current transport:

    * TCP/IP

    * UDP LAN discovery

Security:

    * Ed25519 node identity

    * X25519 key agreement

    * HKDF-SHA256 session key derivation

    * ChaCha20-Poly1305 authenticated encryption

    * Signed node identity handshake

Performance:

    * asyncio

    * TCP_NODELAY

    * large socket buffers

    * priority queues

    * bounded queues

    * connection deduplication

    * background-task tracking

    * graceful shutdown

    * binary packet framing

    * SQLite WAL mode

    * store-and-forward

Install:

    python3 -m pip install cryptography

Start node:

    python3 mvx_meshbridge.py node

Start Internet gateway:

    python3 mvx_meshbridge.py gateway

Show identity:

    python3 mvx_meshbridge.py identity

Interactive commands:

    status

    peers

    routes

    identity

    send NODE_ID MESSAGE

    send-fast NODE_ID MESSAGE

    send-low NODE_ID MESSAGE

    file NODE_ID /path/file

    fetch https://example.com/

    ping NODE_ID

    quit

Data directory:

    ~/.mvx_meshbridge/

Database:

    ~/.mvx_meshbridge/meshbridge.db

"""

from __future__ import annotations

# Optional high-performance event loop.
# Falls back automatically to asyncio when uvloop is unavailable.
try:
    import uvloop
    uvloop.install()
except ImportError:
    uvloop = None


import argparse

import asyncio

import base64

import hashlib

import json

import os

import secrets

import signal

import socket

import sqlite3

import sys

import time

import traceback

import urllib.parse

import urllib.request

from collections import defaultdict

from dataclasses import dataclass, field

from pathlib import Path

from typing import Optional

# ============================================================================

# CRYPTOGRAPHY

# ============================================================================

try:

    from cryptography.hazmat.primitives import hashes

    from cryptography.hazmat.primitives import serialization

    from cryptography.hazmat.primitives.asymmetric import (

        ed25519,

        x25519,

    )

    from cryptography.hazmat.primitives.ciphers.aead import (

        ChaCha20Poly1305,

    )

    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

except ImportError:

    print()

    print("MVX MeshBridge requires the 'cryptography' package.")

    print()

    print("Install it with:")

    print()

    print("    python3 -m pip install cryptography")

    print()

    raise

# ============================================================================

# VERSION

# ============================================================================

APP_NAME = "MVX MeshBridge"

VERSION = "1.1.0"

PROTOCOL_VERSION = 1

# ============================================================================

# NETWORK CONSTANTS

# ============================================================================

DISCOVERY_PORT = 49152

DATA_PORT = 49153

MAX_PACKET = 4 * 1024 * 1024

MAX_MESSAGE = 2 * 1024 * 1024

MAX_HOPS = 12

DISCOVERY_INTERVAL = 3.0

PEER_TIMEOUT = 15.0

ROUTE_TIMEOUT = 30.0

CONNECTION_TIMEOUT = 5.0

FETCH_TIMEOUT = 30

MAX_PEER_QUEUE = 4096

MAX_BACKGROUND_TASKS = 4096

# ============================================================================

# PACKET TYPES

# ============================================================================

TYPE_HELLO = 1

TYPE_HELLO_ACK = 2

TYPE_DATA = 3

TYPE_ROUTE = 4

TYPE_ACK = 5

TYPE_FETCH = 6

TYPE_FETCH_RESPONSE = 7

TYPE_FILE = 8

TYPE_PING = 9

TYPE_PONG = 10

# ============================================================================

# FLAGS

# ============================================================================

FLAG_ENCRYPTED = 1

FLAG_STORE_FORWARD = 2

FLAG_GATEWAY = 4

FLAG_ACK_REQUIRED = 8

# ============================================================================

# PRIORITIES

# ============================================================================

PRIORITY_REALTIME = 0

PRIORITY_HIGH = 1

PRIORITY_NORMAL = 2

PRIORITY_LOW = 3

# ============================================================================

# SPECIAL IDs

# ============================================================================

BROADCAST_ID = b"\xff" * 16

# ============================================================================

# BINARY FRAME FORMAT

# ============================================================================

FRAME_HEADER = struct = __import__("struct")

FRAME_HEADER = struct.Struct(

    "!4sBI"

)

PACKET_HEADER = struct.Struct(

    "!BBBB16s16s16sQII"

)

MAGIC = b"MVXB"

# ============================================================================

# UTILITY FUNCTIONS

# ============================================================================

def now_ms() -> int:

    return int(

        time.time() * 1000

    )

def monotonic() -> float:

    return time.monotonic()

def random_bytes(length: int) -> bytes:

    return secrets.token_bytes(length)

def b64(data: bytes) -> str:

    return base64.urlsafe_b64encode(

        data

    ).decode("ascii")

def unb64(data: str) -> bytes:

    return base64.urlsafe_b64decode(

        data.encode("ascii")

    )

def node_id_from_ed25519(

    public_key: bytes,

) -> bytes:

    return hashlib.sha256(

        public_key

    ).digest()[:16]

def node_id_text(

    node_id: bytes,

) -> str:

    return node_id.hex()

def short_id(

    node_id: bytes,

) -> str:

    return node_id.hex()[:8]

# ============================================================================

# CONFIGURATION

# ============================================================================

class Config:

    def __init__(self):

        self.base = (

            Path.home()

            / ".mvx_meshbridge"

        )

        self.base.mkdir(

            parents=True,

            exist_ok=True,

        )

        self.keys = (

            self.base

            / "keys"

        )

        self.keys.mkdir(

            parents=True,

            exist_ok=True,

        )

        self.db = (

            self.base

            / "meshbridge.db"

        )

        self.host = "0.0.0.0"

        self.port = DATA_PORT

        self.discovery_port = (

            DISCOVERY_PORT

        )

        self.max_hops = MAX_HOPS

        self.peer_timeout = (

            PEER_TIMEOUT

        )

        self.gateway = False

        self.node_name = (

            socket.gethostname()

        )

        self.max_connections = 256

        self.queue_limit = (

            MAX_PEER_QUEUE

        )

        self.discovery_enabled = True

        self.fetch_timeout = (

            FETCH_TIMEOUT

        )

        self.log_level = "info"

# ============================================================================

# IDENTITY

# ============================================================================

class Identity:

    def __init__(

        self,

        config: Config,

    ):

        self.config = config

        self.ed_path = (

            config.keys

            / "identity.ed25519"

        )

        self.x_path = (

            config.keys

            / "identity.x25519"

        )

        self.ed_private = None

        self.x_private = None

        self.load_or_create()

        self.ed_public = (

            self.ed_private.public_key()

        )

        self.x_public = (

            self.x_private.public_key()

        )

        self.ed_public_bytes = (

            self.ed_public.public_bytes(

                serialization.Encoding.Raw,

                serialization.PublicFormat.Raw,

            )

        )

        self.x_public_bytes = (

            self.x_public.public_bytes(

                serialization.Encoding.Raw,

                serialization.PublicFormat.Raw,

            )

        )

        self.node_id = (

            node_id_from_ed25519(

                self.ed_public_bytes

            )

        )

    # ------------------------------------------------------------------------

    # CREATE / LOAD

    # ------------------------------------------------------------------------

    def load_or_create(self):

        if self.ed_path.exists():

            raw = (

                self.ed_path.read_bytes()

            )

            if len(raw) != 32:

                raise ValueError(

                    "Invalid Ed25519 identity file"

                )

            self.ed_private = (

                ed25519.Ed25519PrivateKey

                .from_private_bytes(raw)

            )

        else:

            self.ed_private = (

                ed25519.Ed25519PrivateKey

                .generate()

            )

            raw = (

                self.ed_private

                .private_bytes(

                    serialization.Encoding.Raw,

                    serialization.PrivateFormat.Raw,

                    serialization.NoEncryption(),

                )

            )

            self.ed_path.write_bytes(

                raw

            )

            try:

                os.chmod(

                    self.ed_path,

                    0o600,

                )

            except OSError:

                pass

        if self.x_path.exists():

            raw = (

                self.x_path.read_bytes()

            )

            if len(raw) != 32:

                raise ValueError(

                    "Invalid X25519 identity file"

                )

            self.x_private = (

                x25519.X25519PrivateKey

                .from_private_bytes(raw)

            )

        else:

            self.x_private = (

                x25519.X25519PrivateKey

                .generate()

            )

            raw = (

                self.x_private

                .private_bytes(

                    serialization.Encoding.Raw,

                    serialization.PrivateFormat.Raw,

                    serialization.NoEncryption(),

                )

            )

            self.x_path.write_bytes(

                raw

            )

            try:

                os.chmod(

                    self.x_path,

                    0o600,

                )

            except OSError:

                pass

    # ------------------------------------------------------------------------

    # SIGN

    # ------------------------------------------------------------------------

    def sign(

        self,

        data: bytes,

    ) -> bytes:

        return self.ed_private.sign(

            data

        )

    # ------------------------------------------------------------------------

    # VERIFY

    # ------------------------------------------------------------------------

    @staticmethod

    def verify(

        public_key: bytes,

        signature: bytes,

        data: bytes,

    ) -> bool:

        try:

            key = (

                ed25519.Ed25519PublicKey

                .from_public_bytes(

                    public_key

                )

            )

            key.verify(

                signature,

                data,

            )

            return True

        except Exception:

            return False

    # ------------------------------------------------------------------------

    # DERIVE SESSION KEY

    # ------------------------------------------------------------------------

    def derive_key(

        self,

        peer_x25519_public: bytes,

    ) -> bytes:

        peer = (

            x25519.X25519PublicKey

            .from_public_bytes(

                peer_x25519_public

            )

        )

        shared = (

            self.x_private.exchange(

                peer

            )

        )

        first = min(

            self.x_public_bytes,

            peer_x25519_public,

        )

        second = max(

            self.x_public_bytes,

            peer_x25519_public,

        )

        salt = hashlib.sha256(

            b"MVX-MESHBRIDGE-V1"

            + first

            + second

        ).digest()

        return HKDF(

            algorithm=hashes.SHA256(),

            length=32,

            salt=salt,

            info=b"MVX-MESH-SESSION",

        ).derive(

            shared

        )

    # ------------------------------------------------------------------------

    # DESCRIPTION

    # ------------------------------------------------------------------------

    def describe(self) -> dict:

        return {

            "node_id":

                node_id_text(

                    self.node_id

                ),

            "name":

                self.config.node_name,

            "ed25519_public":

                b64(

                    self.ed_public_bytes

                ),

            "x25519_public":

                b64(

                    self.x_public_bytes

                ),

        }

# ============================================================================

# DATABASE

# ============================================================================

class MeshDB:

    def __init__(

        self,

        config: Config,

    ):

        self.path = config.db

        self.conn = sqlite3.connect(

            self.path,

            check_same_thread=False,

        )

        self.conn.execute(

            "PRAGMA journal_mode=WAL"

        )

        self.conn.execute(

            "PRAGMA synchronous=NORMAL"

        )

        self.conn.execute(

            "PRAGMA temp_store=MEMORY"

        )

        self.conn.execute(

            "PRAGMA busy_timeout=3000"

        )

        self.lock = asyncio.Lock()

        self.initialize()

    # ------------------------------------------------------------------------

    # INITIALIZE

    # ------------------------------------------------------------------------

    def initialize(self):

        c = self.conn.cursor()

        c.execute(

            """

            CREATE TABLE IF NOT EXISTS peers (

                node_id BLOB PRIMARY KEY,

                name TEXT,

                host TEXT,

                port INTEGER,

                ed_public BLOB,

                x_public BLOB,

                last_seen REAL,

                hops INTEGER DEFAULT 1,

                rtt REAL DEFAULT 0,

                gateway INTEGER DEFAULT 0

            )

            """

        )

        c.execute(

            """

            CREATE TABLE IF NOT EXISTS routes (

                destination BLOB PRIMARY KEY,

                next_hop BLOB,

                hops INTEGER,

                metric REAL,

                last_seen REAL

            )

            """

        )

        c.execute(

            """

            CREATE TABLE IF NOT EXISTS packets (

                packet_id BLOB PRIMARY KEY,

                source BLOB,

                destination BLOB,

                packet_type INTEGER,

                priority INTEGER,

                payload BLOB,

                created REAL,

                expires REAL,

                delivered INTEGER DEFAULT 0

            )

            """

        )

        c.execute(

            """

            CREATE TABLE IF NOT EXISTS received (

                packet_id BLOB PRIMARY KEY,

                received REAL

            )

            """

        )

        self.conn.commit()

    # ------------------------------------------------------------------------

    # PEERS

    # ------------------------------------------------------------------------

    async def add_peer(

        self,

        node_id,

        name,

        host,

        port,

        ed_public,

        x_public,

        gateway=False,

        hops=1,

        rtt=0,

    ):

        async with self.lock:

            self.conn.execute(

                """

                INSERT INTO peers

                (

                    node_id,

                    name,

                    host,

                    port,

                    ed_public,

                    x_public,

                    last_seen,

                    hops,

                    rtt,

                    gateway

                )

                VALUES

                (?,?,?,?,?,?,?,?,?,?)

                ON CONFLICT(node_id)

                DO UPDATE SET

                    name=excluded.name,

                    host=excluded.host,

                    port=excluded.port,

                    ed_public=excluded.ed_public,

                    x_public=excluded.x_public,

                    last_seen=excluded.last_seen,

                    hops=excluded.hops,

                    rtt=excluded.rtt,

                    gateway=excluded.gateway

                """,

                (

                    node_id,

                    name,

                    host,

                    port,

                    ed_public,

                    x_public,

                    time.time(),

                    hops,

                    rtt,

                    int(gateway),

                ),

            )

            self.conn.commit()

    async def get_peer(

        self,

        node_id,

    ):

        async with self.lock:

            cur = self.conn.execute(

                """

                SELECT *

                FROM peers

                WHERE node_id=?

                """,

                (

                    node_id,

                ),

            )

            return cur.fetchone()

    async def peers(self):

        async with self.lock:

            cur = self.conn.execute(

                """

                SELECT

                    node_id,

                    name,

                    host,

                    port,

                    last_seen,

                    hops,

                    rtt,

                    gateway

                FROM peers

                ORDER BY last_seen DESC

                """

            )

            return cur.fetchall()

    # ------------------------------------------------------------------------

    # ROUTES

    # ------------------------------------------------------------------------

    async def add_route(

        self,

        destination,

        next_hop,

        hops,

        metric,

    ):

        async with self.lock:

            self.conn.execute(

                """

                INSERT INTO routes

                (

                    destination,

                    next_hop,

                    hops,

                    metric,

                    last_seen

                )

                VALUES

                (?,?,?,?,?)

                ON CONFLICT(destination)

                DO UPDATE SET

                    next_hop=excluded.next_hop,

                    hops=excluded.hops,

                    metric=excluded.metric,

                    last_seen=excluded.last_seen

                """,

                (

                    destination,

                    next_hop,

                    hops,

                    metric,

                    time.time(),

                ),

            )

            self.conn.commit()

    async def get_route(

        self,

        destination,

    ):

        async with self.lock:

            cur = self.conn.execute(

                """

                SELECT

                    destination,

                    next_hop,

                    hops,

                    metric,

                    last_seen

                FROM routes

                WHERE destination=?

                """,

                (

                    destination,

                ),

            )

            return cur.fetchone()

    async def route_rows(self):

        async with self.lock:

            cur = self.conn.execute(

                """

                SELECT

                    destination,

                    next_hop,

                    hops,

                    metric,

                    last_seen

                FROM routes

                ORDER BY metric

                """

            )

            return cur.fetchall()

    # ------------------------------------------------------------------------

    # DUPLICATE PACKETS

    # ------------------------------------------------------------------------

    async def mark_received(

        self,

        packet_id,

    ) -> bool:

        async with self.lock:

            cur = self.conn.execute(

                """

                SELECT 1

                FROM received

                WHERE packet_id=?

                """,

                (

                    packet_id,

                ),

            )

            if cur.fetchone():

                return False

            self.conn.execute(

                """

                INSERT INTO received

                (

                    packet_id,

                    received

                )

                VALUES

                (?,?)

                """,

                (

                    packet_id,

                    time.time(),

                ),

            )

            self.conn.commit()

            return True

    # ------------------------------------------------------------------------

    # STORE FORWARD

    # ------------------------------------------------------------------------

    async def queue_packet(

        self,

        packet_id,

        source,

        destination,

        packet_type,

        priority,

        payload,

        ttl=86400,

    ):

        async with self.lock:

            self.conn.execute(

                """

                INSERT OR REPLACE INTO packets

                (

                    packet_id,

                    source,

                    destination,

                    packet_type,

                    priority,

                    payload,

                    created,

                    expires,

                    delivered

                )

                VALUES

                (?,?,?,?,?,?,?,?,0)

                """,

                (

                    packet_id,

                    source,

                    destination,

                    packet_type,

                    priority,

                    payload,

                    time.time(),

                    time.time() + ttl,

                ),

            )

            self.conn.commit()

    async def queued_packets(

        self,

        destination=None,

    ):

        async with self.lock:

            if destination:

                cur = self.conn.execute(

                    """

                    SELECT

                        packet_id,

                        source,

                        destination,

                        packet_type,

                        priority,

                        payload,

                        created,

                        expires

                    FROM packets

                    WHERE delivered=0

                      AND expires>?

                      AND destination=?

                    ORDER BY

                        priority ASC,

                        created ASC

                    """,

                    (

                        time.time(),

                        destination,

                    ),

                )

            else:

                cur = self.conn.execute(

                    """

                    SELECT

                        packet_id,

                        source,

                        destination,

                        packet_type,

                        priority,

                        payload,

                        created,

                        expires

                    FROM packets

                    WHERE delivered=0

                      AND expires>?

                    ORDER BY

                        priority ASC,

                        created ASC

                    """,

                    (

                        time.time(),

                    ),

                )

            return cur.fetchall()

    async def mark_delivered(

        self,

        packet_id,

    ):

        async with self.lock:

            self.conn.execute(

                """

                UPDATE packets

                SET delivered=1

                WHERE packet_id=?

                """,

                (

                    packet_id,

                ),

            )

            self.conn.commit()

    # ------------------------------------------------------------------------

    # CLEANUP

    # ------------------------------------------------------------------------

    async def cleanup(self):

        async with self.lock:

            cutoff = (

                time.time()

                - 86400 * 7

            )

            self.conn.execute(

                """

                DELETE FROM received

                WHERE received<?

                """,

                (

                    cutoff,

                ),

            )

            self.conn.execute(

                """

                DELETE FROM packets

                WHERE expires<?

                """,

                (

                    time.time(),

                ),

            )

            self.conn.execute(

                """

                DELETE FROM routes

                WHERE last_seen<?

                """,

                (

                    time.time()

                    - ROUTE_TIMEOUT,

                ),

            )

            self.conn.execute(

                """

                DELETE FROM peers

                WHERE last_seen<?

                """,

                (

                    time.time()

                    - 120,

                ),

            )

            self.conn.commit()

    # ------------------------------------------------------------------------

    # CLOSE

    # ------------------------------------------------------------------------

    def close(self):

        try:

            self.conn.close()

        except Exception:

            pass

# ============================================================================

# MESH PACKET

# ============================================================================

@dataclass

class MeshPacket:

    version: int

    packet_type: int

    flags: int

    priority: int

    packet_id: bytes

    source: bytes

    destination: bytes

    timestamp: int

    ttl: int

    payload: bytes

    # ------------------------------------------------------------------------

    # ENCODE

    # ------------------------------------------------------------------------

    def encode(self) -> bytes:

        if len(self.packet_id) != 16:

            raise ValueError(

                "packet_id must be 16 bytes"

            )

        if len(self.source) != 16:

            raise ValueError(

                "source must be 16 bytes"

            )

        if len(self.destination) != 16:

            raise ValueError(

                "destination must be 16 bytes"

            )

        if len(self.payload) > MAX_PACKET:

            raise ValueError(

                "payload too large"

            )

        header = PACKET_HEADER.pack(

            self.version,

            self.packet_type,

            self.flags,

            self.priority,

            self.packet_id,

            self.source,

            self.destination,

            self.timestamp,

            self.ttl,

            len(self.payload),

        )

        return (

            header

            + self.payload

        )

    # ------------------------------------------------------------------------

    # DECODE

    # ------------------------------------------------------------------------

    @staticmethod

    def decode(

        data: bytes,

    ) -> "MeshPacket":

        if len(data) < PACKET_HEADER.size:

            raise ValueError(

                "packet too short"

            )

        (

            version,

            packet_type,

            flags,

            priority,

            packet_id,

            source,

            destination,

            timestamp,

            ttl,

            payload_len,

        ) = PACKET_HEADER.unpack_from(

            data

        )

        if version != PROTOCOL_VERSION:

            raise ValueError(

                "unsupported protocol version"

            )

        if payload_len > MAX_PACKET:

            raise ValueError(

                "payload too large"

            )

        expected = (

            PACKET_HEADER.size

            + payload_len

        )

        if len(data) != expected:

            raise ValueError(

                "invalid packet length"

            )

        return MeshPacket(

            version=version,

            packet_type=packet_type,

            flags=flags,

            priority=priority,

            packet_id=packet_id,

            source=source,

            destination=destination,

            timestamp=timestamp,

            ttl=ttl,

            payload=data[

                PACKET_HEADER.size:

            ],

        )

# ============================================================================

# CRYPTO SESSION CACHE

# ============================================================================

class CryptoSession:

    def __init__(

        self,

        identity: Identity,

    ):

        self.identity = identity

        self.sessions = {}

    def set_peer_key(

        self,

        peer_id: bytes,

        x_public: bytes,

    ):

        self.sessions[

            peer_id

        ] = self.identity.derive_key(

            x_public

        )

    def has_key(

        self,

        peer_id: bytes,

    ) -> bool:

        return (

            peer_id

            in self.sessions

        )

    def encrypt(

        self,

        peer_id: bytes,

        plaintext: bytes,

        aad: bytes,

    ) -> bytes:

        key = self.sessions.get(

            peer_id

        )

        if key is None:

            raise ValueError(

                "no encryption session"

            )

        nonce = random_bytes(12)

        ciphertext = (

            ChaCha20Poly1305(

                key

            ).encrypt(

                nonce,

                plaintext,

                aad,

            )

        )

        return (

            nonce

            + ciphertext

        )

    def decrypt(

        self,

        peer_id: bytes,

        ciphertext: bytes,

        aad: bytes,

    ) -> bytes:

        key = self.sessions.get(

            peer_id

        )

        if key is None:

            raise ValueError(

                "no encryption session"

            )

        if len(ciphertext) < 12:

            raise ValueError(

                "encrypted payload too short"

            )

        nonce = ciphertext[:12]

        body = ciphertext[12:]

        return (

            ChaCha20Poly1305(

                key

            ).decrypt(

                nonce,

                body,

                aad,

            )

        )

# ============================================================================

# PEER

# ============================================================================

@dataclass

class Peer:

    node_id: bytes

    name: str

    host: str

    port: int

    ed_public: bytes

    x_public: bytes

    gateway: bool = False

    reader: Optional[

        asyncio.StreamReader

    ] = None

    writer: Optional[

        asyncio.StreamWriter

    ] = None

    last_seen: float = field(

        default_factory=monotonic

    )

    rtt: float = 0.0

    send_queue: Optional[

        asyncio.PriorityQueue

    ] = None

    connected: bool = False

    send_task: Optional[

        asyncio.Task

    ] = None

    def __post_init__(self):

        self.send_queue = (

            asyncio.PriorityQueue(

                maxsize=MAX_PEER_QUEUE

            )

        )

# ============================================================================

# DISCOVERY PROTOCOL

# ============================================================================

class DiscoveryProtocol(

    asyncio.DatagramProtocol

):

    def __init__(

        self,

        mesh,

    ):

        self.mesh = mesh

    def datagram_received(

        self,

        data,

        addr,

    ):

        self.mesh.spawn_task(

            self.mesh.process_discovery(

                data,

                addr,

            )

        )

# ============================================================================

# DISCOVERY

# ============================================================================

class Discovery:

    def __init__(

        self,

        mesh,

    ):

        self.mesh = mesh

        self.transport = None

    async def start(self):

        loop = (

            asyncio.get_running_loop()

        )

        sock = socket.socket(

            socket.AF_INET,

            socket.SOCK_DGRAM,

            socket.IPPROTO_UDP,

        )

        sock.setsockopt(

            socket.SOL_SOCKET,

            socket.SO_REUSEADDR,

            1,

        )

        try:

            sock.setsockopt(

                socket.SOL_SOCKET,

                socket.SO_BROADCAST,

                1,

            )

        except OSError:

            pass

        sock.bind(

            (

                "0.0.0.0",

                self.mesh.config.discovery_port,

            )

        )

        self.transport, _ = (

            await loop.create_datagram_endpoint(

                lambda:

                    DiscoveryProtocol(

                        self.mesh

                    ),

                sock=sock,

            )

        )

        self.mesh.spawn_task(

            self.broadcast_loop()

        )

    async def broadcast_loop(

        self,

    ):

        while self.mesh.running:

            try:

                await self.broadcast()

            except asyncio.CancelledError:

                raise

            except Exception:

                pass

            try:

                await asyncio.sleep(

                    DISCOVERY_INTERVAL

                )

            except asyncio.CancelledError:

                raise

    async def broadcast(

        self,

    ):

        payload = {

            "magic":

                "MVXBRIDGE",

            "version":

                VERSION,

            "node_id":

                node_id_text(

                    self.mesh.identity.node_id

                ),

            "name":

                self.mesh.config.node_name,

            "port":

                self.mesh.config.port,

            "ed":

                b64(

                    self.mesh.identity

                    .ed_public_bytes

                ),

            "x":

                b64(

                    self.mesh.identity

                    .x_public_bytes

                ),

            "gateway":

                self.mesh.config.gateway,

            "time":

                time.time(),

        }

        raw = json.dumps(

            payload,

            separators=(",", ":"),

        ).encode()

        if self.transport is not None:

            self.transport.sendto(

                raw,

                (

                    "255.255.255.255",

                    self.mesh.config

                    .discovery_port,

                ),

            )

    def stop(self):

        if self.transport:

            try:

                self.transport.close()

            except Exception:

                pass

            self.transport = None

# ============================================================================

# MESH ENGINE

# ============================================================================

class MeshBridge:

    def __init__(

        self,

        config: Config,

    ):

        self.config = config

        self.identity = Identity(

            config

        )

        self.db = MeshDB(

            config

        )

        self.crypto = CryptoSession(

            self.identity

        )

        self.peers = {}

        # One lock per peer.

        self.peer_locks = defaultdict(

            asyncio.Lock

        )

        # Every background task is tracked.

        self.background_tasks = set()

        # Connection attempts are tracked independently.

        self.connect_tasks = {}

        self.running = False

        self.server = None

        self.discovery = None

        self.stats = defaultdict(int)

        self.start_time = monotonic()

        self.shutdown_started = False

    # ------------------------------------------------------------------------

    # LOG

    # ------------------------------------------------------------------------

    def log(

        self,

        *args,

    ):

        print(

            f"[{time.strftime('%H:%M:%S')}]",

            *args,

            flush=True,

        )

    # ------------------------------------------------------------------------

    # TASK MANAGEMENT

    # ------------------------------------------------------------------------

    def spawn_task(

        self,

        coro,

    ):

        if len(

            self.background_tasks

        ) >= MAX_BACKGROUND_TASKS:

            self.stats[

                "background_task_drops"

            ] += 1

            try:

                coro.close()

            except Exception:

                pass

            return None

        task = asyncio.create_task(

            coro

        )

        self.background_tasks.add(

            task

        )

        def finished(

            done_task,

        ):

            self.background_tasks.discard(

                done_task

            )

            if not done_task.cancelled():

                try:

                    done_task.exception()

                except Exception:

                    pass

        task.add_done_callback(

            finished

        )

        return task

    # ------------------------------------------------------------------------

    # START

    # ------------------------------------------------------------------------

    async def start(

        self,

    ):

        if self.running:

            return

        self.running = True

        self.shutdown_started = False

        self.start_time = monotonic()

        self.server = (

            await asyncio.start_server(

                self.handle_connection,

                self.config.host,

                self.config.port,

                limit=MAX_PACKET + 1024,

                family=socket.AF_INET,

                backlog=256,

            )

        )

        # Optimize every listening socket.

        for sock in (

            self.server.sockets or []

        ):

            self.optimize_socket(

                sock

            )

        if (

            self.config.discovery_enabled

        ):

            self.discovery = (

                Discovery(self)

            )

            await self.discovery.start()

        self.log(

            f"{APP_NAME} {VERSION} started"

        )

        self.log(

            "Node ID:",

            node_id_text(

                self.identity.node_id

            ),

        )

        self.log(

            "Listening:",

            self.config.port,

        )

        if self.config.gateway:

            self.log(

                "Gateway mode: ENABLED"

            )

        self.spawn_task(

            self.maintenance_loop()

        )

        self.spawn_task(

            self.route_announcement_loop()

        )

        self.spawn_task(

            self.store_forward_loop()

        )

    # ------------------------------------------------------------------------

    # SOCKET OPTIMIZATION

    # ------------------------------------------------------------------------

    @staticmethod

    def optimize_socket(

        sock,

    ):

        try:

            sock.setsockopt(

                socket.IPPROTO_TCP,

                socket.TCP_NODELAY,

                1,

            )

        except OSError:

            pass

        try:

            sock.setsockopt(

                socket.SOL_SOCKET,

                socket.SO_SNDBUF,

                1024 * 1024,

            )

        except OSError:

            pass

        try:

            sock.setsockopt(

                socket.SOL_SOCKET,

                socket.SO_RCVBUF,

                1024 * 1024,

            )

        except OSError:

            pass

    # ------------------------------------------------------------------------

    # CONNECTION HANDLER

    # ------------------------------------------------------------------------

    async def handle_connection(

        self,

        reader,

        writer,

    ):

        peer_addr = (

            writer.get_extra_info(

                "peername"

            )

        )

        try:

            self.optimize_socket(

                writer.transport

                .get_extra_info(

                    "socket"

                )

            )

        except Exception:

            pass

        try:

            writer.transport.set_write_buffer_limits(

                high=1024 * 1024,

                low=256 * 1024,

            )

        except Exception:

            pass

        try:

            await self.perform_handshake(

                reader,

                writer,

            )

            while self.running:

                frame = (

                    await self.read_frame(

                        reader

                    )

                )

                if frame is None:

                    break

                await self.handle_frame(

                    frame,

                    reader,

                    writer,

                )

        except asyncio.CancelledError:

            raise

        except (

            asyncio.IncompleteReadError,

            ConnectionResetError,

            BrokenPipeError,

            ConnectionAbortedError,

        ):

            pass

        except Exception as exc:

            self.stats[

                "connection_errors"

            ] += 1

            if (

                self.config.log_level

                == "debug"

            ):

                self.log(

                    "connection error",

                    peer_addr,

                    repr(exc),

                )

        finally:

            try:

                writer.close()

                await writer.wait_closed()

            except Exception:

                pass

    # ------------------------------------------------------------------------

    # HANDSHAKE

    # ------------------------------------------------------------------------

    async def perform_handshake(

        self,

        reader,

        writer,

    ):

        hello = {

            "type":

                "HELLO",

            "version":

                PROTOCOL_VERSION,

            "node_id":

                b64(

                    self.identity.node_id

                ),

            "name":

                self.config.node_name,

            "ed":

                b64(

                    self.identity

                    .ed_public_bytes

                ),

            "x":

                b64(

                    self.identity

                    .x_public_bytes

                ),

            "gateway":

                self.config.gateway,

            "port":

                self.config.port,

            "time":

                time.time(),

        }

        identity_blob = (

            self.identity.node_id

            + self.identity.x_public_bytes

            + str(

                PROTOCOL_VERSION

            ).encode()

        )

        hello["sig"] = b64(

            self.identity.sign(

                identity_blob

            )

        )

        await self.write_frame(

            writer,

            json.dumps(

                hello,

                separators=(",", ":"),

            ).encode(),

        )

        remote_raw = (

            await asyncio.wait_for(

                self.read_frame(reader),

                timeout=CONNECTION_TIMEOUT,

            )

        )

        if remote_raw is None:

            raise ConnectionError(

                "no handshake response"

            )

        if remote_raw == b"MVX_OK":

            return None

        remote = json.loads(

            remote_raw.decode()

        )

        if remote.get("type") != "HELLO":

            raise ConnectionError(

                "invalid handshake"

            )

        remote_id = unb64(

            remote["node_id"]

        )

        remote_ed = unb64(

            remote["ed"]

        )

        remote_x = unb64(

            remote["x"]

        )

        signature = unb64(

            remote["sig"]

        )

        identity_blob = (

            remote_id

            + remote_x

            + str(

                PROTOCOL_VERSION

            ).encode()

        )

        if not Identity.verify(

            remote_ed,

            signature,

            identity_blob,

        ):

            raise ConnectionError(

                "peer identity signature invalid"

            )

        if (

            remote_id

            == self.identity.node_id

        ):

            raise ConnectionError(

                "self connection"

            )

        self.crypto.set_peer_key(

            remote_id,

            remote_x,

        )

        remote_addr = (

            writer.get_extra_info(

                "peername"

            )

        )

        host = (

            remote_addr[0]

            if remote_addr

            else "unknown"

        )

        port = int(

            remote.get(

                "port",

                DATA_PORT,

            )

        )

        peer = self.peers.get(

            remote_id

        )

        if peer is None:

            peer = Peer(

                node_id=remote_id,

                name=remote.get(

                    "name",

                    short_id(

                        remote_id

                    ),

                ),

                host=host,

                port=port,

                ed_public=remote_ed,

                x_public=remote_x,

                gateway=bool(

                    remote.get(

                        "gateway"

                    )

                ),

            )

            self.peers[

                remote_id

            ] = peer

        peer.reader = reader

        peer.writer = writer

        peer.connected = True

        peer.last_seen = monotonic()

        await self.db.add_peer(

            remote_id,

            peer.name,

            host,

            port,

            remote_ed,

            remote_x,

            peer.gateway,

        )

        self.stats[

            "handshakes"

        ] += 1

        await self.write_frame(

            writer,

            b"MVX_OK",

        )

        return peer

    # ------------------------------------------------------------------------

    # FRAME READ

    # ------------------------------------------------------------------------

    async def read_frame(

        self,

        reader,

    ) -> Optional[bytes]:

        header = (

            await reader.readexactly(

                FRAME_HEADER.size

            )

        )

        magic, version, length = (

            FRAME_HEADER.unpack(

                header

            )

        )

        if magic != MAGIC:

            raise ValueError(

                "bad frame magic"

            )

        if version != PROTOCOL_VERSION:

            raise ValueError(

                "bad frame version"

            )

        if (

            length < 0

            or length > MAX_PACKET

        ):

            raise ValueError(

                "frame too large"

            )

        return (

            await reader.readexactly(

                length

            )

        )

    # ------------------------------------------------------------------------

    # FRAME WRITE

    # ------------------------------------------------------------------------

    async def write_frame(

        self,

        writer,

        payload: bytes,

    ):

        if len(payload) > MAX_PACKET:

            raise ValueError(

                "frame too large"

            )

        header = FRAME_HEADER.pack(

            MAGIC,

            PROTOCOL_VERSION,

            len(payload),

        )

        writer.write(

            header

        )

        writer.write(

            payload

        )

        await writer.drain()

    # ------------------------------------------------------------------------

    # PACKET HANDLER

    # ------------------------------------------------------------------------

    async def handle_frame(

        self,

        frame,

        reader,

        writer,

    ):

        if frame == b"MVX_OK":

            return

        try:

            packet = MeshPacket.decode(

                frame

            )

        except Exception:

            self.stats[

                "invalid_packets"

            ] += 1

            return

        self.stats[

            "packets_received"

        ] += 1

        self.stats[

            "bytes_received"

        ] += len(frame)

        if (

            packet.source

            == self.identity.node_id

        ):

            return

        if not await self.db.mark_received(

            packet.packet_id

        ):

            self.stats[

                "duplicates"

            ] += 1

            return

        if packet.ttl <= 0:

            self.stats[

                "ttl_drops"

            ] += 1

            return

        if (

            packet.destination

            == self.identity.node_id

            or packet.destination

            == BROADCAST_ID

        ):

            await self.process_local_packet(

                packet

            )

            return

        packet.ttl -= 1

        if packet.ttl <= 0:

            return

        await self.forward_packet(

            packet

        )

    # ------------------------------------------------------------------------

    # LOCAL PACKET

    # ------------------------------------------------------------------------

    async def process_local_packet(

        self,

        packet,

    ):

        self.stats[

            "packets_delivered"

        ] += 1

        if (

            packet.packet_type

            == TYPE_DATA

        ):

            await self.process_data(

                packet

            )

        elif (

            packet.packet_type

            == TYPE_FILE

        ):

            await self.process_file(

                packet

            )

        elif (

            packet.packet_type

            == TYPE_FETCH

        ):

            await self.process_fetch(

                packet

            )

        elif (

            packet.packet_type

            == TYPE_FETCH_RESPONSE

        ):

            await self.process_fetch_response(

                packet

            )

        elif (

            packet.packet_type

            == TYPE_ROUTE

        ):

            await self.process_route(

                packet

            )

        elif (

            packet.packet_type

            == TYPE_PING

        ):

            await self.process_ping(

                packet

            )

        elif (

            packet.packet_type

            == TYPE_PONG

        ):

            await self.process_pong(

                packet

            )

    # ------------------------------------------------------------------------

    # AAD

    # ------------------------------------------------------------------------

    @staticmethod

    def packet_aad(

        packet,

    ) -> bytes:

        return (

            packet.packet_id

            + packet.source

            + packet.destination

            + bytes(

                [

                    packet.packet_type,

                    packet.priority,

                ]

            )

        )

    # ------------------------------------------------------------------------

    # DATA

    # ------------------------------------------------------------------------

    async def process_data(

        self,

        packet,

    ):

        try:

            plaintext = (

                self.crypto.decrypt(

                    packet.source,

                    packet.payload,

                    self.packet_aad(

                        packet

                    ),

                )

            )

        except Exception:

            self.stats[

                "decrypt_errors"

            ] += 1

            return

        try:

            message = json.loads(

                plaintext.decode()

            )

        except Exception:

            message = {

                "text":

                    plaintext.decode(

                        "utf-8",

                        "replace",

                    )

            }

        print()

        print(

            f"[MESSAGE from "

            f"{short_id(packet.source)}]"

        )

        print(

            json.dumps(

                message,

                indent=2,

            ),

            flush=True,

        )

        print()

    # ------------------------------------------------------------------------

    # FILE

    # ------------------------------------------------------------------------

    async def process_file(

        self,

        packet,

    ):

        try:

            plaintext = (

                self.crypto.decrypt(

                    packet.source,

                    packet.payload,

                    self.packet_aad(

                        packet

                    ),

                )

            )

            obj = json.loads(

                plaintext.decode()

            )

            filename = Path(

                obj.get(

                    "filename",

                    (

                        "received_"

                        + packet.packet_id.hex()

                    ),

                )

            ).name

            data = unb64(

                obj["data"]

            )

            receive_dir = (

                self.config.base

                / "received"

            )

            receive_dir.mkdir(

                parents=True,

                exist_ok=True,

            )

            path = (

                receive_dir

                / filename

            )

            path.write_bytes(

                data

            )

            self.log(

                "Received file:",

                path,

            )

        except Exception as exc:

            self.log(

                "file error:",

                exc,

            )

    # ------------------------------------------------------------------------

    # ROUTES

    # ------------------------------------------------------------------------

    async def process_route(

        self,

        packet,

    ):

        try:

            raw = (

                self.crypto.decrypt(

                    packet.source,

                    packet.payload,

                    self.packet_aad(

                        packet

                    ),

                )

            )

            data = json.loads(

                raw.decode()

            )

            destination = unb64(

                data["destination"]

            )

            hops = (

                int(

                    data.get(

                        "hops",

                        0,

                    )

                )

                + 1

            )

            if (

                destination

                == self.identity.node_id

            ):

                return

            metric = (

                float(

                    data.get(

                        "metric",

                        1.0,

                    )

                )

                + 1.0

            )

            current = await self.db.get_route(

                destination

            )

            # Keep the better route.

            if (

                current is None

                or metric < current[3]

                or (

                    time.time()

                    - current[4]

                    > ROUTE_TIMEOUT

                )

            ):

                await self.db.add_route(

                    destination,

                    packet.source,

                    hops,

                    metric,

                )

                self.stats[

                    "routes_learned"

                ] += 1

        except Exception:

            self.stats[

                "route_errors"

            ] += 1

    # ------------------------------------------------------------------------

    # ROUTE ANNOUNCEMENT

    # ------------------------------------------------------------------------

    async def route_announcement_loop(

        self,

    ):

        try:

            while self.running:

                await asyncio.sleep(

                    5

                )

                for peer in list(

                    self.peers.values()

                ):

                    if not peer.connected:

                        continue

                    payload = {

                        "destination":

                            b64(

                                self.identity

                                .node_id

                            ),

                        "hops":

                            0,

                        "metric":

                            1.0,

                    }

                    try:

                        await self.send_encrypted(

                            peer.node_id,

                            TYPE_ROUTE,

                            payload,

                            PRIORITY_LOW,

                            ttl=self.config

                            .max_hops,

                            store_forward=False,

                        )

                    except Exception:

                        pass

        except asyncio.CancelledError:

            raise

    # ------------------------------------------------------------------------

    # PING

    # ------------------------------------------------------------------------

    async def process_ping(

        self,

        packet,

    ):

        try:

            data = (

                self.crypto.decrypt(

                    packet.source,

                    packet.payload,

                    self.packet_aad(

                        packet

                    ),

                )

            )

            await self.send_encrypted(

                packet.source,

                TYPE_PONG,

                {

                    "echo":

                        b64(data),

                    "time":

                        time.time(),

                },

                PRIORITY_REALTIME,

                ttl=self.config.max_hops,

            )

        except Exception:

            pass

    # ------------------------------------------------------------------------

    # PONG

    # ------------------------------------------------------------------------

    async def process_pong(

        self,

        packet,

    ):

        try:

            raw = (

                self.crypto.decrypt(

                    packet.source,

                    packet.payload,

                    self.packet_aad(

                        packet

                    ),

                )

            )

            obj = json.loads(

                raw.decode()

            )

            timestamp = float(

                obj.get(

                    "time",

                    time.time(),

                )

            )

            rtt = max(

                0.0,

                time.time()

                - timestamp,

            )

            peer = self.peers.get(

                packet.source

            )

            if peer:

                peer.rtt = rtt

                await self.db.add_peer(

                    peer.node_id,

                    peer.name,

                    peer.host,

                    peer.port,

                    peer.ed_public,

                    peer.x_public,

                    peer.gateway,

                    rtt=rtt,

                )

            self.log(

                "PONG",

                short_id(

                    packet.source

                ),

                f"{rtt * 1000:.2f} ms",

            )

        except Exception:

            pass

    # ------------------------------------------------------------------------

    # FORWARD PACKET

    # ------------------------------------------------------------------------

    async def forward_packet(

        self,

        packet,

    ):

        route = (

            await self.db.get_route(

                packet.destination

            )

        )

        candidates = []

        if route:

            next_hop = route[1]

            peer = self.peers.get(

                next_hop

            )

            if peer:

                candidates = [

                    peer

                ]

        if not candidates:

            candidates = list(

                self.peers.values()

            )

        for peer in candidates:

            if peer is None:

                continue

            if (

                peer.node_id

                == packet.source

            ):

                continue

            if not peer.connected:

                await self.connect_peer(

                    peer

                )

            if not peer.connected:

                continue

            try:

                await self.enqueue_peer(

                    peer,

                    packet.priority,

                    packet.encode(),

                )

                self.stats[

                    "packets_forwarded"

                ] += 1

            except Exception:

                pass

        if (

            not candidates

            and (

                packet.flags

                & FLAG_STORE_FORWARD

            )

        ):

            await self.db.queue_packet(

                packet.packet_id,

                packet.source,

                packet.destination,

                packet.packet_type,

                packet.priority,

                packet.encode(),

            )

    # ------------------------------------------------------------------------

    # PEER SEND QUEUE

    # ------------------------------------------------------------------------

    async def enqueue_peer(

        self,

        peer,

        priority,

        packet_data,

    ):

        if (

            not peer.connected

            or peer.writer is None

        ):

            raise ConnectionError(

                "peer offline"

            )

        try:

            peer.send_queue.put_nowait(

                (

                    priority,

                    monotonic(),

                    packet_data,

                )

            )

        except asyncio.QueueFull:

            self.stats[

                "queue_drops"

            ] += 1

            raise

        if (

            peer.send_task is None

            or peer.send_task.done()

        ):

            peer.send_task = (

                self.spawn_task(

                    self.peer_sender(

                        peer

                    )

                )

            )

    async def peer_sender(

        self,

        peer,

    ):

        try:

            while (

                self.running

                and peer.connected

            ):

                try:

                    (

                        priority,

                        created,

                        data,

                    ) = await asyncio.wait_for(

                        peer.send_queue.get(),

                        timeout=5,

                    )

                except asyncio.TimeoutError:

                    continue

                await self.write_frame(

                    peer.writer,

                    data,

                )

                self.stats[

                    "packets_sent"

                ] += 1

                self.stats[

                    "bytes_sent"

                ] += len(data)

        except asyncio.CancelledError:

            raise

        except Exception:

            peer.connected = False

    # ------------------------------------------------------------------------

    # CONNECT PEER

    # ------------------------------------------------------------------------

    async def connect_peer(

        self,

        peer: Peer,

    ) -> bool:

        if (

            peer.connected

            and peer.writer

        ):

            return True

        current_task = (

            asyncio.current_task()

        )

        existing = self.connect_tasks.get(

            peer.node_id

        )

        if (

            existing is not None

            and not existing.done()

            and existing

            is not current_task

        ):

            try:

                return bool(

                    await asyncio.shield(

                        existing

                    )

                )

            except asyncio.CancelledError:

                raise

            except Exception:

                return False

        lock = self.peer_locks[

            peer.node_id

        ]

        async with lock:

            if (

                peer.connected

                and peer.writer

            ):

                return True

            try:

                reader, writer = (

                    await asyncio.wait_for(

                        asyncio.open_connection(

                            peer.host,

                            peer.port,

                            limit=(

                                MAX_PACKET

                                + 1024

                            ),

                        ),

                        timeout=CONNECTION_TIMEOUT,

                    )

                )

                self.optimize_socket(

                    writer.transport

                    .get_extra_info(

                        "socket"

                    )

                )

                try:

                    writer.transport.set_write_buffer_limits(

                        high=1024 * 1024,

                        low=256 * 1024,

                    )

                except Exception:

                    pass

                # IMPORTANT:

                #

                # perform_handshake() is deliberately

                # performed before registering the reader.

                #

                # This prevents two reader tasks from

                # consuming the same stream.

                remote_peer = (

                    await self.perform_handshake(

                        reader,

                        writer,

                    )

                )

                if remote_peer is not None:

                    peer = remote_peer

                peer.reader = reader

                peer.writer = writer

                peer.connected = True

                peer.last_seen = monotonic()

                self.spawn_task(

                    self.read_connected_peer(

                        peer,

                        reader,

                        writer,

                    )

                )

                return True

            except asyncio.CancelledError:

                raise

            except Exception as exc:

                peer.connected = False

                if (

                    self.config.log_level

                    == "debug"

                ):

                    self.log(

                        "connect failed",

                        short_id(

                            peer.node_id

                        ),

                        exc,

                    )

                return False

    # ------------------------------------------------------------------------

    # TRACKED CONNECTION ATTEMPT

    # ------------------------------------------------------------------------

    async def tracked_connect_peer(

        self,

        peer,

    ):

        current = (

            asyncio.current_task()

        )

        try:

            return await self.connect_peer(

                peer

            )

        except asyncio.CancelledError:

            raise

        except Exception:

            return False

        finally:

            registered = (

                self.connect_tasks.get(

                    peer.node_id

                )

            )

            if registered is current:

                self.connect_tasks.pop(

                    peer.node_id,

                    None,

                )

    # ------------------------------------------------------------------------

    # CONNECTED READER

    # ------------------------------------------------------------------------

    async def read_connected_peer(

        self,

        peer,

        reader,

        writer,

    ):

        try:

            while self.running:

                frame = (

                    await self.read_frame(

                        reader

                    )

                )

                if frame is None:

                    break

                peer.last_seen = monotonic()

                await self.handle_frame(

                    frame,

                    reader,

                    writer,

                )

        except asyncio.CancelledError:

            raise

        except (

            asyncio.IncompleteReadError,

            ConnectionResetError,

            BrokenPipeError,

            ConnectionAbortedError,

        ):

            pass

        except Exception as exc:

            if (

                self.config.log_level

                == "debug"

            ):

                self.log(

                    "peer reader error",

                    short_id(

                        peer.node_id

                    ),

                    exc,

                )

        finally:

            peer.connected = False

            if peer.writer is writer:

                peer.writer = None

            if peer.reader is reader:

                peer.reader = None

            try:

                writer.close()

                await writer.wait_closed()

            except Exception:

                pass

    # ------------------------------------------------------------------------

    # ENCRYPTED SEND

    # ------------------------------------------------------------------------

    async def send_encrypted(

        self,

        destination: bytes,

        packet_type: int,

        obj,

        priority=PRIORITY_NORMAL,

        ttl=None,

        store_forward=True,

    ):

        packet_id = random_bytes(

            16

        )

        plaintext = json.dumps(

            obj,

            separators=(",", ":"),

        ).encode()

        packet = MeshPacket(

            version=PROTOCOL_VERSION,

            packet_type=packet_type,

            flags=(

                FLAG_ENCRYPTED

                | (

                    FLAG_STORE_FORWARD

                    if store_forward

                    else 0

                )

            ),

            priority=priority,

            packet_id=packet_id,

            source=self.identity.node_id,

            destination=destination,

            timestamp=now_ms(),

            ttl=(

                ttl

                if ttl is not None

                else self.config.max_hops

            ),

            payload=b"",

        )

        # --------------------------------------------------------------------

        # Obtain destination encryption key.

        # --------------------------------------------------------------------

        if not self.crypto.has_key(

            destination

        ):

            peer_row = (

                await self.db.get_peer(

                    destination

                )

            )

            if peer_row:

                self.crypto.set_peer_key(

                    destination,

                    peer_row[5],

                )

        if not self.crypto.has_key(

            destination

        ):

            raise ConnectionError(

                "no public key for destination"

            )

        packet.payload = (

            self.crypto.encrypt(

                destination,

                plaintext,

                self.packet_aad(

                    packet

                ),

            )

        )

        data = packet.encode()

        # --------------------------------------------------------------------

        # Find route.

        # --------------------------------------------------------------------

        peer = await self.ensure_route_peer(

            destination

        )

        candidates = []

        if peer:

            candidates = [

                peer

            ]

        else:

            # Unknown route: controlled flooding

            # through currently known peers.

            candidates = list(

                self.peers.values()

            )

        sent = False

        for candidate in candidates:

            if candidate is None:

                continue

            if (

                candidate.node_id

                == self.identity.node_id

            ):

                continue

            if not candidate.connected:

                await self.connect_peer(

                    candidate

                )

            if not candidate.connected:

                continue

            try:

                await self.enqueue_peer(

                    candidate,

                    priority,

                    data,

                )

                sent = True

            except Exception:

                pass

        if not sent:

            if store_forward:

                await self.db.queue_packet(

                    packet.packet_id,

                    packet.source,

                    packet.destination,

                    packet.packet_type,

                    priority,

                    data,

                )

                self.stats[

                    "store_forward_queued"

                ] += 1

            raise ConnectionError(

                "packet queued for "

                "store-and-forward"

            )

        return packet_id

    # ------------------------------------------------------------------------

    # ENSURE ROUTE PEER

    # ------------------------------------------------------------------------

    async def ensure_route_peer(

        self,

        destination,

    ):

        # Direct peer.

        direct = self.peers.get(

            destination

        )

        if direct:

            if await self.connect_peer(

                direct

            ):

                return direct

        # Learned route.

        route = await self.db.get_route(

            destination

        )

        if route:

            next_hop = route[1]

            peer = self.peers.get(

                next_hop

            )

            if peer:

                if await self.connect_peer(

                    peer

                ):

                    return peer

        # Database peer.

        row = await self.db.get_peer(

            destination

        )

        if row:

            peer = self.peers.get(

                destination

            )

            if peer is None:

                peer = Peer(

                    node_id=row[0],

                    name=row[1],

                    host=row[2],

                    port=row[3],

                    ed_public=row[4],

                    x_public=row[5],

                    gateway=bool(

                        row[9]

                    ),

                )

                self.peers[

                    destination

                ] = peer

            self.crypto.set_peer_key(

                destination,

                row[5],

            )

            if await self.connect_peer(

                peer

            ):

                return peer

        return None

    # ------------------------------------------------------------------------

    # DISCOVERY PROCESSING

    # ------------------------------------------------------------------------

    async def process_discovery(

        self,

        data,

        addr,

    ):

        try:

            obj = json.loads(

                data.decode()

            )

            if (

                obj.get("magic")

                != "MVXBRIDGE"

            ):

                return

            remote_id = unb64(

                b64(

                    bytes.fromhex(

                        obj["node_id"]

                    )

                )

            )

            if (

                remote_id

                == self.identity.node_id

            ):

                return

            ed_public = unb64(

                obj["ed"]

            )

            x_public = unb64(

                obj["x"]

            )

            host = addr[0]

            port = int(

                obj.get(

                    "port",

                    DATA_PORT,

                )

            )

            peer = self.peers.get(

                remote_id

            )

            if peer is None:

                peer = Peer(

                    node_id=remote_id,

                    name=obj.get(

                        "name",

                        short_id(

                            remote_id

                        ),

                    ),

                    host=host,

                    port=port,

                    ed_public=ed_public,

                    x_public=x_public,

                    gateway=bool(

                        obj.get(

                            "gateway"

                        )

                    ),

                )

                self.peers[

                    remote_id

                ] = peer

            else:

                peer.host = host

                peer.port = port

                peer.last_seen = monotonic()

                peer.ed_public = (

                    ed_public

                )

                peer.x_public = (

                    x_public

                )

                peer.gateway = bool(

                    obj.get(

                        "gateway"

                    )

                )

            self.crypto.set_peer_key(

                remote_id,

                x_public,

            )

            await self.db.add_peer(

                remote_id,

                peer.name,

                host,

                port,

                ed_public,

                x_public,

                peer.gateway,

            )

            # ---------------------------------------------------------------

            # IMPORTANT:

            #

            # Never create another connect task if one is already pending.

            # ---------------------------------------------------------------

            if (

                not peer.connected

                and self.running

            ):

                existing = (

                    self.connect_tasks.get(

                        remote_id

                    )

                )

                if (

                    existing is None

                    or existing.done()

                ):

                    task = self.spawn_task(

                        self.tracked_connect_peer(

                            peer

                        )

                    )

                    if task is not None:

                        self.connect_tasks[

                            remote_id

                        ] = task

        except Exception:

            self.stats[

                "discovery_errors"

            ] += 1

    # ------------------------------------------------------------------------

    # FETCH

    # ------------------------------------------------------------------------

    async def process_fetch(

        self,

        packet,

    ):

        if not self.config.gateway:

            return

        try:

            plaintext = (

                self.crypto.decrypt(

                    packet.source,

                    packet.payload,

                    self.packet_aad(

                        packet

                    ),

                )

            )

            req = json.loads(

                plaintext.decode()

            )

            url = req["url"]

            parsed = urllib.parse.urlparse(

                url

            )

            if parsed.scheme not in (

                "http",

                "https",

            ):

                raise ValueError(

                    "only HTTP/HTTPS "

                    "URLs are supported"

                )

            request = (

                urllib.request.Request(

                    url,

                    headers={

                        "User-Agent":

                            "MVX-MeshBridge/1.1"

                    },

                )

            )

            with urllib.request.urlopen(

                request,

                timeout=self.config.fetch_timeout,

            ) as response:

                data = response.read(

                    MAX_MESSAGE

                )

                result = {

                    "ok": True,

                    "url": url,

                    "status":

                        response.status,

                    "content_type":

                        response.headers.get(

                            "Content-Type",

                            "",

                        ),

                    "data":

                        b64(data),

                }

        except Exception as exc:

            result = {

                "ok": False,

                "error": str(exc),

            }

        try:

            await self.send_encrypted(

                packet.source,

                TYPE_FETCH_RESPONSE,

                result,

                PRIORITY_HIGH,

            )

        except Exception:

            pass

    # ------------------------------------------------------------------------

    # FETCH RESPONSE

    # ------------------------------------------------------------------------

    async def process_fetch_response(

        self,

        packet,

    ):

        try:

            plaintext = (

                self.crypto.decrypt(

                    packet.source,

                    packet.payload,

                    self.packet_aad(

                        packet

                    ),

                )

            )

            result = json.loads(

                plaintext.decode()

            )

            out = (

                self.config.base

                / "downloads"

            )

            out.mkdir(

                parents=True,

                exist_ok=True,

            )

            filename = (

                "fetch_"

                + str(

                    int(

                        time.time()

                    )

                )

                + ".bin"

            )

            path = (

                out

                / filename

            )

            if result.get(

                "ok"

            ):

                data = unb64(

                    result["data"]

                )

                path.write_bytes(

                    data

                )

                print()

                print(

                    "Gateway response saved:"

                )

                print(

                    path

                )

                print(

                    "HTTP status:",

                    result.get(

                        "status"

                    ),

                )

                print(

                    "Content-Type:",

                    result.get(

                        "content_type"

                    ),

                )

            else:

                print(

                    "\nGateway error:",

                    result.get(

                        "error"

                    ),

                )

        except Exception as exc:

            self.log(

                "fetch response error:",

                exc,

            )

    # ------------------------------------------------------------------------

    # STORE FORWARD LOOP

    # ------------------------------------------------------------------------

    async def store_forward_loop(

        self,

    ):

        try:

            while self.running:

                await asyncio.sleep(

                    2

                )

                rows = (

                    await self.db

                    .queued_packets()

                )

                for row in rows[:256]:

                    (

                        packet_id,

                        source,

                        destination,

                        packet_type,

                        priority,

                        payload,

                        created,

                        expires,

                    ) = row

                    if (

                        expires

                        <= time.time()

                    ):

                        continue

                    peer = (

                        await self.ensure_route_peer(

                            destination

                        )

                    )

                    if peer is None:

                        continue

                    if not peer.connected:

                        continue

                    try:

                        await self.enqueue_peer(

                            peer,

                            priority,

                            payload,

                        )

                        await self.db.mark_delivered(

                            packet_id

                        )

                    except Exception:

                        pass

        except asyncio.CancelledError:

            raise

    # ------------------------------------------------------------------------

    # MAINTENANCE

    # ------------------------------------------------------------------------

    async def maintenance_loop(

        self,

    ):

        try:

            while self.running:

                await asyncio.sleep(

                    5

                )

                current = monotonic()

                for peer in list(

                    self.peers.values()

                ):

                    if (

                        current

                        - peer.last_seen

                        > self.config

                        .peer_timeout

                    ):

                        if (

                            not peer.connected

                        ):

                            continue

                await self.db.cleanup()

        except asyncio.CancelledError:

            raise

    # ------------------------------------------------------------------------

    # SEND MESSAGE

    # ------------------------------------------------------------------------

    async def send_message(

        self,

        destination_text,

        text,

        priority=PRIORITY_NORMAL,

    ):

        destination = bytes.fromhex(

            destination_text

        )

        return await self.send_encrypted(

            destination,

            TYPE_DATA,

            {

                "text": text,

                "sender_name":

                    self.config.node_name,

                "time":

                    time.time(),

            },

            priority=priority,

        )

    # ------------------------------------------------------------------------

    # SEND FILE

    # ------------------------------------------------------------------------

    async def send_file(

        self,

        destination_text,

        filename,

    ):

        destination = bytes.fromhex(

            destination_text

        )

        path = Path(

            filename

        ).expanduser()

        if not path.exists():

            raise FileNotFoundError(

                path

            )

        size = path.stat().st_size

        if size > MAX_MESSAGE:

            raise ValueError(

                f"file is {size} bytes; "

                f"maximum is {MAX_MESSAGE}"

            )

        data = path.read_bytes()

        return await self.send_encrypted(

            destination,

            TYPE_FILE,

            {

                "filename":

                    path.name,

                "data":

                    b64(data),

            },

            priority=PRIORITY_LOW,

        )

    # ------------------------------------------------------------------------

    # FETCH THROUGH GATEWAY

    # ------------------------------------------------------------------------

    async def fetch(

        self,

        url,

    ):

        gateways = [

            p

            for p in self.peers.values()

            if p.gateway

        ]

        if not gateways:

            raise ConnectionError(

                "no Internet gateway "

                "discovered"

            )

        gateways.sort(

            key=lambda p:

                p.rtt

                if p.rtt

                else 999999

        )

        gateway = gateways[0]

        if not gateway.connected:

            if not await self.connect_peer(

                gateway

            ):

                raise ConnectionError(

                    "could not connect "

                    "to gateway"

                )

        return await self.send_encrypted(

            gateway.node_id,

            TYPE_FETCH,

            {

                "url":

                    url,

                "time":

                    time.time(),

            },

            priority=PRIORITY_HIGH,

        )

    # ------------------------------------------------------------------------

    # PING

    # ------------------------------------------------------------------------

    async def ping(

        self,

        destination_text,

    ):

        destination = bytes.fromhex(

            destination_text

        )

        start = monotonic()

        await self.send_encrypted(

            destination,

            TYPE_PING,

            {

                "time":

                    time.time(),

                "nonce":

                    b64(

                        random_bytes(

                            16

                        )

                    ),

            },

            priority=PRIORITY_REALTIME,

        )

        return (

            monotonic()

            - start

        )

    # ------------------------------------------------------------------------

    # STATUS

    # ------------------------------------------------------------------------

    async def status(

        self,

    ):

        uptime = (

            monotonic()

            - self.start_time

        )

        peers = (

            await self.db.peers()

        )

        routes = (

            await self.db.route_rows()

        )

        connected = sum(

            1

            for p in self.peers.values()

            if p.connected

        )

        print()

        print(

            "=" * 76

        )

        print(

            APP_NAME,

            VERSION,

        )

        print(

            "=" * 76

        )

        print(

            "Node:",

            node_id_text(

                self.identity.node_id

            ),

        )

        print(

            "Name:",

            self.config.node_name,

        )

        print(

            "Uptime:",

            f"{uptime:.1f}s",

        )

        print(

            "Gateway:",

            self.config.gateway,

        )

        print(

            "Listening:",

            self.config.port,

        )

        print(

            "Connected peers:",

            connected,

        )

        print(

            "Known peers:",

            len(peers),

        )

        print(

            "Routes:",

            len(routes),

        )

        print(

            "Background tasks:",

            len(

                self.background_tasks

            ),

        )

        print(

            "Pending connections:",

            sum(

                1

                for task

                in self.connect_tasks.values()

                if not task.done()

            ),

        )

        print()

        print(

            "Statistics:"

        )

        for key in sorted(

            self.stats

        ):

            print(

                f"  {key:30s}",

                self.stats[key],

            )

        print()

        print(

            "Peers:"

        )

        for row in peers:

            (

                node_id,

                name,

                host,

                port,

                last_seen,

                hops,

                rtt,

                gateway,

            ) = row

            age = (

                time.time()

                - last_seen

            )

            peer = self.peers.get(

                node_id

            )

            connected_state = (

                peer.connected

                if peer

                else False

            )

            print(

                f"  {short_id(node_id):8s}"

                f"  {name[:20]:20s}"

                f"  {host}:{port}"

                f"  age={age:.1f}s"

                f"  hops={hops}"

                f"  rtt={rtt * 1000:.2f}ms"

                f"  connected={connected_state}"

                f"  gateway={bool(gateway)}"

            )

        print(

            "=" * 76

        )

    # ------------------------------------------------------------------------

    # STOP

    # ------------------------------------------------------------------------

    async def stop(

        self,

    ):

        if self.shutdown_started:

            return

        self.shutdown_started = True

        self.running = False

        self.log(

            "Stopping MeshBridge..."

        )

        # --------------------------------------------------------------------

        # Stop discovery first.

        # --------------------------------------------------------------------

        if self.discovery:

            try:

                self.discovery.stop()

            except Exception:

                pass

            self.discovery = None

        # --------------------------------------------------------------------

        # Stop listening server.

        # --------------------------------------------------------------------

        if self.server:

            self.server.close()

            try:

                await self.server.wait_closed()

            except Exception:

                pass

            self.server = None

        # --------------------------------------------------------------------

        # Cancel connection attempts.

        # --------------------------------------------------------------------

        connection_tasks = list(

            self.connect_tasks.values()

        )

        self.connect_tasks.clear()

        for task in connection_tasks:

            if (

                task

                and not task.done()

            ):

                task.cancel()

        if connection_tasks:

            await asyncio.gather(

                *connection_tasks,

                return_exceptions=True,

            )

        # --------------------------------------------------------------------

        # Close peer sockets.

        # --------------------------------------------------------------------

        writers = []

        for peer in list(

            self.peers.values()

        ):

            peer.connected = False

            if peer.writer:

                writers.append(

                    peer.writer

                )

                try:

                    peer.writer.close()

                except Exception:

                    pass

        for writer in writers:

            try:

                await writer.wait_closed()

            except Exception:

                pass

        # --------------------------------------------------------------------

        # Cancel every remaining tracked task.

        # --------------------------------------------------------------------

        current = (

            asyncio.current_task()

        )

        tasks = [

            task

            for task

            in list(

                self.background_tasks

            )

            if (

                task is not current

                and not task.done()

            )

        ]

        for task in tasks:

            task.cancel()

        if tasks:

            await asyncio.gather(

                *tasks,

                return_exceptions=True,

            )

        self.background_tasks.clear()

        # --------------------------------------------------------------------

        # Close database.

        # --------------------------------------------------------------------

        try:

            self.db.close()

        except Exception:

            pass

        self.log(

            "MeshBridge stopped cleanly."

        )

# ============================================================================

# INTERACTIVE SHELL

# ============================================================================

async def interactive_shell(

    mesh: MeshBridge,

):

    print()

    print(

        "MVX MeshBridge interactive console"

    )

    print(

        "Type 'help' for commands."

    )

    print()

    while mesh.running:

        try:

            command = (

                await asyncio.to_thread(

                    input,

                    "mesh> ",

                )

            )

        except EOFError:

            break

        except KeyboardInterrupt:

            break

        command = command.strip()

        if not command:

            continue

        parts = command.split(

            maxsplit=2

        )

        cmd = (

            parts[0]

            .lower()

        )

        try:

            # ---------------------------------------------------------------

            # EXIT

            # ---------------------------------------------------------------

            if cmd in (

                "quit",

                "exit",

            ):

                break

            # ---------------------------------------------------------------

            # HELP

            # ---------------------------------------------------------------

            elif cmd == "help":

                print(

                    """

status

peers

routes

identity

send NODE_ID MESSAGE

send-fast NODE_ID MESSAGE

send-low NODE_ID MESSAGE

file NODE_ID /path/to/file

fetch https://example.com/

ping NODE_ID

quit

"""

                )

            # ---------------------------------------------------------------

            # STATUS

            # ---------------------------------------------------------------

            elif cmd == "status":

                await mesh.status()

            # ---------------------------------------------------------------

            # PEERS

            # ---------------------------------------------------------------

            elif cmd == "peers":

                rows = (

                    await mesh.db.peers()

                )

                if not rows:

                    print(

                        "No peers discovered."

                    )

                for row in rows:

                    (

                        node_id,

                        name,

                        host,

                        port,

                        last_seen,

                        hops,

                        rtt,

                        gateway,

                    ) = row

                    peer = mesh.peers.get(

                        node_id

                    )

                    connected = (

                        peer.connected

                        if peer

                        else False

                    )

                    print(

                        short_id(

                            node_id

                        ),

                        name,

                        f"{host}:{port}",

                        f"rtt="

                        f"{rtt * 1000:.2f}ms",

                        f"connected="

                        f"{connected}",

                        f"gateway="

                        f"{bool(gateway)}",

                    )

            # ---------------------------------------------------------------

            # ROUTES

            # ---------------------------------------------------------------

            elif cmd == "routes":

                rows = (

                    await mesh.db

                    .route_rows()

                )

                if not rows:

                    print(

                        "No routes learned."

                    )

                for row in rows:

                    (

                        destination,

                        next_hop,

                        hops,

                        metric,

                        last_seen,

                    ) = row

                    print(

                        short_id(

                            destination

                        ),

                        "via",

                        short_id(

                            next_hop

                        ),

                        "hops=",

                        hops,

                        "metric=",

                        metric,

                    )

            # ---------------------------------------------------------------

            # IDENTITY

            # ---------------------------------------------------------------

            elif cmd == "identity":

                print(

                    json.dumps(

                        mesh.identity.describe(),

                        indent=2,

                    )

                )

            # ---------------------------------------------------------------

            # SEND

            # ---------------------------------------------------------------

            elif cmd in (

                "send",

                "send-fast",

                "send-low",

            ):

                if len(parts) < 3:

                    print(

                        "usage:"

                        " send NODE_ID MESSAGE"

                    )

                    continue

                priority = {

                    "send":

                        PRIORITY_NORMAL,

                    "send-fast":

                        PRIORITY_REALTIME,

                    "send-low":

                        PRIORITY_LOW,

                }[cmd]

                packet_id = (

                    await mesh.send_message(

                        parts[1],

                        parts[2],

                        priority=priority,

                    )

                )

                print(

                    "Packet queued:",

                    packet_id.hex(),

                )

            # ---------------------------------------------------------------

            # FILE

            # ---------------------------------------------------------------

            elif cmd == "file":

                if len(parts) < 3:

                    print(

                        "usage:"

                        " file NODE_ID PATH"

                    )

                    continue

                packet_id = (

                    await mesh.send_file(

                        parts[1],

                        parts[2],

                    )

                )

                print(

                    "File queued:",

                    packet_id.hex(),

                )

            # ---------------------------------------------------------------

            # FETCH

            # ---------------------------------------------------------------

            elif cmd == "fetch":

                if len(parts) < 2:

                    print(

                        "usage:"

                        " fetch URL"

                    )

                    continue

                packet_id = (

                    await mesh.fetch(

                        parts[1]

                    )

                )

                print(

                    "Gateway request queued:",

                    packet_id.hex(),

                )

            # ---------------------------------------------------------------

            # PING

            # ---------------------------------------------------------------

            elif cmd == "ping":

                if len(parts) < 2:

                    print(

                        "usage:"

                        " ping NODE_ID"

                    )

                    continue

                elapsed = (

                    await mesh.ping(

                        parts[1]

                    )

                )

                print(

                    "Request queued in:",

                    f"{elapsed * 1000:.2f} ms",

                )

            # ---------------------------------------------------------------

            # UNKNOWN

            # ---------------------------------------------------------------

            else:

                print(

                    "Unknown command."

                    " Type 'help'."

                )

        except Exception as exc:

            print(

                "ERROR:",

                exc,

            )

# ============================================================================

# RUN NODE

# ============================================================================

async def run_node(

    config: Config,

):

    mesh = MeshBridge(

        config

    )

    await mesh.start()

    loop = (

        asyncio.get_running_loop()

    )

    stop_event = asyncio.Event()

    def stop_signal():

        if not stop_event.is_set():

            stop_event.set()

    for sig in (

        signal.SIGINT,

        signal.SIGTERM,

    ):

        try:

            loop.add_signal_handler(

                sig,

                stop_signal,

            )

        except (

            NotImplementedError,

            RuntimeError,

        ):

            pass

    shell_task = (

        mesh.spawn_task(

            interactive_shell(

                mesh

            )

        )

    )

    stop_task = (

        asyncio.create_task(

            stop_event.wait()

        )

    )

    try:

        wait_tasks = [

            stop_task

        ]

        if shell_task:

            wait_tasks.append(

                shell_task

            )

        done, pending = (

            await asyncio.wait(

                wait_tasks,

                return_when=(

                    asyncio.FIRST_COMPLETED

                ),

            )

        )

        for task in pending:

            task.cancel()

        if pending:

            await asyncio.gather(

                *pending,

                return_exceptions=True,

            )

    finally:

        await mesh.stop()

# ============================================================================

# ARGUMENT PARSER

# ============================================================================

def build_parser():

    parser = argparse.ArgumentParser(

        description=APP_NAME,

    )

    parser.add_argument(

        "--base",

        help="MeshBridge data directory",

    )

    parser.add_argument(

        "--name",

        help="Node display name",

    )

    parser.add_argument(

        "--port",

        type=int,

        default=DATA_PORT,

    )

    parser.add_argument(

        "--debug",

        action="store_true",

    )

    sub = (

        parser.add_subparsers(

            dest="command"

        )

    )

    node = sub.add_parser(

        "node"

    )

    node.add_argument(

        "--no-discovery",

        action="store_true",

    )

    gateway = sub.add_parser(

        "gateway"

    )

    gateway.add_argument(

        "--no-discovery",

        action="store_true",

    )

    sub.add_parser(

        "identity"

    )

    sub.add_parser(

        "peers"

    )

    sub.add_parser(

        "status"

    )

    sub.add_parser(

        "routes"

    )

    send = sub.add_parser(

        "send"

    )

    send.add_argument(

        "node_id"

    )

    send.add_argument(

        "message"

    )

    send.add_argument(

        "--fast",

        action="store_true",

    )

    send.add_argument(

        "--low",

        action="store_true",

    )

    queue = sub.add_parser(

        "queue"

    )

    queue.add_argument(

        "node_id"

    )

    queue.add_argument(

        "path"

    )

    fetch = sub.add_parser(

        "fetch"

    )

    fetch.add_argument(

        "url"

    )

    ping = sub.add_parser(

        "ping"

    )

    ping.add_argument(

        "node_id"

    )

    return parser

# ============================================================================

# COMMAND MAIN

# ============================================================================

async def command_main(

    args,

):

    config = Config()

    # ------------------------------------------------------------------------

    # Custom data directory.

    # ------------------------------------------------------------------------

    if args.base:

        config.base = (

            Path(

                args.base

            )

            .expanduser()

            .resolve()

        )

        config.base.mkdir(

            parents=True,

            exist_ok=True,

        )

        config.keys = (

            config.base

            / "keys"

        )

        config.keys.mkdir(

            parents=True,

            exist_ok=True,

        )

        config.db = (

            config.base

            / "meshbridge.db"

        )

    # ------------------------------------------------------------------------

    # Name.

    # ------------------------------------------------------------------------

    if args.name:

        config.node_name = (

            args.name

        )

    # ------------------------------------------------------------------------

    # Port.

    # ------------------------------------------------------------------------

    config.port = args.port

    # ------------------------------------------------------------------------

    # Debug.

    # ------------------------------------------------------------------------

    if args.debug:

        config.log_level = "debug"

    command = args.command

    # ------------------------------------------------------------------------

    # IDENTITY.

    # ------------------------------------------------------------------------

    if command == "identity":

        identity = Identity(

            config

        )

        print(

            json.dumps(

                identity.describe(),

                indent=2,

            )

        )

        print()

        print(

            "Identity directory:",

            config.keys,

        )

        return

    # ------------------------------------------------------------------------

    # INFORMATIONAL COMMANDS.

    # ------------------------------------------------------------------------

    if command in (

        "peers",

        "status",

        "routes",

    ):

        mesh = MeshBridge(

            config

        )

        try:

            if command == "peers":

                rows = (

                    await mesh.db.peers()

                )

                for row in rows:

                    print(

                        short_id(

                            row[0]

                        ),

                        row[1],

                        row[2],

                        row[3],

                        "gateway=",

                        bool(row[7]),

                    )

            elif command == "routes":

                rows = (

                    await mesh.db.route_rows()

                )

                for row in rows:

                    print(

                        short_id(

                            row[0]

                        ),

                        "via",

                        short_id(

                            row[1]

                        ),

                        "hops=",

                        row[2],

                        "metric=",

                        row[3],

                    )

            else:

                await mesh.status()

        finally:

            mesh.db.close()

        return

    # ------------------------------------------------------------------------

    # NODE.

    # ------------------------------------------------------------------------

    if command == "node":

        config.gateway = False

        config.discovery_enabled = (

            not args.no_discovery

        )

        await run_node(

            config

        )

        return

    # ------------------------------------------------------------------------

    # GATEWAY.

    # ------------------------------------------------------------------------

    if command == "gateway":

        config.gateway = True

        config.discovery_enabled = (

            not args.no_discovery

        )

        await run_node(

            config

        )

        return

    # ------------------------------------------------------------------------

    # ONE-SHOT NETWORK COMMAND.

    # ------------------------------------------------------------------------

    if command in (

        "send",

        "queue",

        "fetch",

        "ping",

    ):

        mesh = MeshBridge(

            config

        )

        await mesh.start()

        try:

            if command == "send":

                priority = (

                    PRIORITY_NORMAL

                )

                if args.fast:

                    priority = (

                        PRIORITY_REALTIME

                    )

                elif args.low:

                    priority = (

                        PRIORITY_LOW

                    )

                packet_id = (

                    await mesh.send_message(

                        args.node_id,

                        args.message,

                        priority,

                    )

                )

                print(

                    "Packet:",

                    packet_id.hex(),

                )

            elif command == "queue":

                packet_id = (

                    await mesh.send_file(

                        args.node_id,

                        args.path,

                    )

                )

                print(

                    "Packet:",

                    packet_id.hex(),

                )

            elif command == "fetch":

                packet_id = (

                    await mesh.fetch(

                        args.url

                    )

                )

                print(

                    "Request:",

                    packet_id.hex(),

                )

            elif command == "ping":

                elapsed = (

                    await mesh.ping(

                        args.node_id

                    )

                )

                print(

                    "Queued in:",

                    f"{elapsed * 1000:.2f} ms",

                )

        finally:

            await mesh.stop()

        return

    # ------------------------------------------------------------------------

    # DEFAULT.

    # ------------------------------------------------------------------------

    config.gateway = False

    await run_node(

        config

    )

# ============================================================================

# MAIN

# ============================================================================

def main():

    parser = build_parser()

    args = parser.parse_args()

    try:

        asyncio.run(

            command_main(

                args

            )

        )

    except KeyboardInterrupt:

        pass

    except Exception as exc:

        print(

            "\nMVX MeshBridge ERROR:",

            exc,

            file=sys.stderr,

        )

        if getattr(

            args,

            "debug",

            False,

        ):

            traceback.print_exc()

        sys.exit(1)

# ============================================================================

# ENTRY POINT

# ============================================================================

if __name__ == "__main__":

    main()
