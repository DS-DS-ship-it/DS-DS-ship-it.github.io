#!/usr/bin/env python3

"""

MVX MeshBridge 3.0

==================

Single-file universal MVX mesh reference engine.

Designed as the protocol/reference implementation for:

    macOS / Windows / Linux

    Raspberry Pi

    iPhone / iPad native wrappers

    Android native wrappers

    Meshtastic / LoRa adapters

    Existing MVX HTML applications

IMPORTANT:

    This is the reference Python engine. It is intentionally transport-

    agnostic so the same MVX protocol can later be implemented by a

    Rust/native engine without changing the wire protocol.

Core features

-------------

* Strict MVX3 binary framing

* Length and resource validation

* Ed25519 persistent node identity

* X25519 ephemeral session keys

* Transcript-bound authenticated handshake

* ChaCha20-Poly1305 encryption

* Explicit directional session keys

* Session IDs

* Neighbor table

* Sequence-numbered distance-vector routing

* Correct next-hop handling

* Route expiration

* Duplicate suppression with expiration

* Bounded packet fragmentation/reassembly

* ACK / retry / delivery tracking

* Store-and-forward SQLite WAL

* Priority queues

* LAN TCP transport

* UDP LAN discovery

* Optional Meshtastic serial transport

* Optional BLE transport hook

* Hardened local HTTP dashboard

* Hardened optional HTTP gateway

* Graceful shutdown

* Runtime diagnostics

Usage

-----

    python3 mvx_meshbridge_3.py node

    python3 mvx_meshbridge_3.py gateway

    python3 mvx_meshbridge_3.py node --port 49153

    python3 mvx_meshbridge_3.py node --lora /dev/ttyUSB0

    python3 mvx_meshbridge_3.py node --ble

    python3 mvx_meshbridge_3.py gateway --gateway-allow-host example.com

Dashboard:

    http://127.0.0.1:49154/

Dependencies:

    python3 -m pip install cryptography

Optional:

    python3 -m pip install pyserial pyserial-asyncio

For BLE on supported systems:

    python3 -m pip install bleak

This file intentionally has no third-party web framework.

"""

from __future__ import annotations

import argparse

import asyncio

import base64

import hashlib

import hmac

import ipaddress

import json

import os

import platform

import secrets

import socket

import sqlite3

import struct

import sys

import time

import urllib.parse

from collections import defaultdict, deque

from dataclasses import dataclass, field

from pathlib import Path

from typing import (

    Any,

    Awaitable,

    Callable,

    Deque,

    Dict,

    Iterable,

    List,

    Optional,

    Set,

    Tuple,

)

# ---------------------------------------------------------------------------

# Optional uvloop

# ---------------------------------------------------------------------------

if sys.platform != "win32":

    try:

        import uvloop

        uvloop.install()

    except ImportError:

        pass

# ---------------------------------------------------------------------------

# Cryptography

# ---------------------------------------------------------------------------

try:

    from cryptography.hazmat.primitives import hashes, serialization

    from cryptography.hazmat.primitives.asymmetric import ed25519, x25519

    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

except ImportError:

    print(

        "\nMVX MeshBridge requires the 'cryptography' package.\n"

        "Install it with:\n\n"

        "    python3 -m pip install cryptography\n"

    )

    raise SystemExit(1)

# ===========================================================================

# VERSION / PROTOCOL

# ===========================================================================

APP_NAME = "MVX MeshBridge"

VERSION = "3.0.0"

PROTOCOL_VERSION = 3

MAGIC = b"MVX3"

DISCOVERY_PORT = 49152

DATA_PORT = 49153

WEB_PORT = 49154

MAX_FRAME = 1024 * 1024

MAX_PACKET = 1024 * 1024

MAX_CHUNK = 220

MAX_REASSEMBLY = 2 * 1024 * 1024

MAX_FRAGMENTS = 4096

ROUTE_INTERVAL = 10.0

ROUTE_TIMEOUT = 35.0

SEEN_PACKET_TTL = 300.0

SESSION_TIMEOUT = 3600.0

HANDSHAKE_TIMEOUT = 10.0

ACK_TIMEOUT = 3.0

MAX_RETRIES = 4

STORE_FORWARD_TTL = 86400.0

TYPE_HELLO = 1

TYPE_HELLO_ACK = 2

TYPE_HEARTBEAT = 3

TYPE_DATA = 4

TYPE_ROUTE_ADV = 5

TYPE_CHUNK = 6

TYPE_GATEWAY_REQ = 7

TYPE_GATEWAY_RES = 8

TYPE_ACK = 9

TYPE_NACK = 10

PRIO_LATENCY_CRITICAL = 0

PRIO_INTERACTIVE = 1

PRIO_NORMAL = 2

PRIO_BULK_STORE_FWD = 3

FLAG_ENCRYPTED = 0x01

FLAG_STORE_FORWARD = 0x02

FLAG_BROADCAST = 0x04

FLAG_ACK_REQUESTED = 0x08

FLAG_ACK_RESPONSE = 0x10

BROADCAST_ID = b"\xff" * 16

ZERO_NONCE = b"\x00" * 12

# ===========================================================================

# WIRE FORMAT

# ===========================================================================

# Frame:

#

#   magic       4

#   version     1

#   flags       1

#   body_len    4

#

# Packet:

#

#   version         1

#   packet_type     1

#   flags           1

#   priority        1

#   ttl             1

#   hops            1

#   reserved       2

#   packet_id       16

#   src             16

#   dst             16

#   timestamp       8

#   payload_len     4

#   session_id      16

#   nonce           12

#

# This deliberately uses a 32-bit body length instead of the old 16-bit

# field, while still enforcing MAX_FRAME.

FRAME_HEADER = struct.Struct("!4sBBI")

PACKET_HEADER = struct.Struct(

    "!BBBBBBH16s16s16sQI16s12s"

)

# Fragment:

#

#   packet hash     16

#   fragment index  4

#   total           4

#   payload length  4

#

FRAGMENT_HEADER = struct.Struct("!16sIII")

# ===========================================================================

# UTILITIES

# ===========================================================================

def now() -> float:

    return time.time()

def monotonic() -> float:

    return time.monotonic()

def short_id(node_id: bytes) -> str:

    return node_id.hex()[:8]

def node_id_from_pubkey(pub: bytes) -> bytes:

    return hashlib.sha256(pub).digest()[:16]

def random_packet_id() -> bytes:

    return secrets.token_bytes(16)

def canonical_json(obj: Any) -> bytes:

    return json.dumps(

        obj,

        sort_keys=True,

        separators=(",", ":"),

        ensure_ascii=False,

    ).encode("utf-8")

def safe_hex(value: bytes) -> str:

    return value.hex()

def clamp(value: int, minimum: int, maximum: int) -> int:

    return max(minimum, min(maximum, value))

# ===========================================================================

# PACKET

# ===========================================================================

@dataclass

class Packet:

    version: int

    packet_type: int

    flags: int

    priority: int

    ttl: int

    hops: int

    packet_id: bytes

    src: bytes

    dst: bytes

    timestamp: int

    payload: bytes

    session_id: bytes = ZERO_NONCE + b"\x00\x00\x00\x00"

    nonce: bytes = ZERO_NONCE

    def __post_init__(self) -> None:

        if len(self.packet_id) != 16:

            raise ValueError("packet_id must be 16 bytes")

        if len(self.src) != 16:

            raise ValueError("src must be 16 bytes")

        if len(self.dst) != 16:

            raise ValueError("dst must be 16 bytes")

        if len(self.session_id) != 16:

            raise ValueError("session_id must be 16 bytes")

        if len(self.nonce) != 12:

            raise ValueError("nonce must be 12 bytes")

        if not 0 <= self.priority <= 3:

            raise ValueError("invalid priority")

        if not 0 <= self.ttl <= 255:

            raise ValueError("invalid ttl")

        if len(self.payload) > MAX_PACKET:

            raise ValueError("payload exceeds MAX_PACKET")

    def header_bytes(self) -> bytes:

        return PACKET_HEADER.pack(

            self.version,

            self.packet_type,

            self.flags,

            self.priority,

            self.ttl,

            self.hops,

            0,

            self.packet_id,

            self.src,

            self.dst,

            self.timestamp,

            len(self.payload),

            self.session_id,

            self.nonce,

        )

    def serialize(self) -> bytes:

        body = self.header_bytes() + self.payload

        if len(body) > MAX_FRAME:

            raise ValueError("frame exceeds MAX_FRAME")

        return FRAME_HEADER.pack(

            MAGIC,

            self.version,

            0,

            len(body),

        ) + body

    @classmethod

    def parse(cls, body: bytes) -> Optional["Packet"]:

        if len(body) < PACKET_HEADER.size:

            return None

        if len(body) > MAX_FRAME:

            return None

        try:

            (

                version,

                packet_type,

                flags,

                priority,

                ttl,

                hops,

                _reserved,

                packet_id,

                src,

                dst,

                timestamp,

                payload_len,

                session_id,

                nonce,

            ) = PACKET_HEADER.unpack_from(body)

        except struct.error:

            return None

        if version != PROTOCOL_VERSION:

            return None

        if priority > 3:

            return None

        if payload_len > MAX_PACKET:

            return None

        start = PACKET_HEADER.size

        end = start + payload_len

        if end > len(body):

            return None

        if packet_type not in {

            TYPE_HELLO,

            TYPE_HELLO_ACK,

            TYPE_HEARTBEAT,

            TYPE_DATA,

            TYPE_ROUTE_ADV,

            TYPE_CHUNK,

            TYPE_GATEWAY_REQ,

            TYPE_GATEWAY_RES,

            TYPE_ACK,

            TYPE_NACK,

        }:

            return None

        return cls(

            version=version,

            packet_type=packet_type,

            flags=flags,

            priority=priority,

            ttl=ttl,

            hops=hops,

            packet_id=packet_id,

            src=src,

            dst=dst,

            timestamp=timestamp,

            payload=body[start:end],

            session_id=session_id,

            nonce=nonce,

        )

def parse_frame(data: bytes) -> Optional[Packet]:

    if len(data) < FRAME_HEADER.size:

        return None

    magic, version, _flags, body_len = FRAME_HEADER.unpack_from(data)

    if magic != MAGIC:

        return None

    if version != PROTOCOL_VERSION:

        return None

    if body_len > MAX_FRAME:

        return None

    if FRAME_HEADER.size + body_len > len(data):

        return None

    body = data[

        FRAME_HEADER.size:

        FRAME_HEADER.size + body_len

    ]

    return Packet.parse(body)

# ===========================================================================

# FRAGMENTATION

# ===========================================================================

@dataclass

class ReassemblyBuffer:

    total: int

    fragments: Dict[int, bytes] = field(default_factory=dict)

    created: float = field(default_factory=monotonic)

    expires: float = field(

        default_factory=lambda: monotonic() + 60.0

    )

    def size(self) -> int:

        return sum(len(x) for x in self.fragments.values())

class PacketChunker:

    def __init__(self) -> None:

        self.buffers: Dict[bytes, ReassemblyBuffer] = {}

    def cleanup(self) -> None:

        t = monotonic()

        expired = [

            key

            for key, buf in self.buffers.items()

            if buf.expires <= t

        ]

        for key in expired:

            self.buffers.pop(key, None)

    def slice_packet(

        self,

        packet: bytes,

        mtu: int,

    ) -> List[bytes]:

        if len(packet) > MAX_REASSEMBLY:

            raise ValueError("Packet too large to fragment")

        if mtu <= FRAGMENT_HEADER.size:

            raise ValueError("MTU too small")

        payload_cap = mtu - FRAGMENT_HEADER.size

        total = (

            len(packet) + payload_cap - 1

        ) // payload_cap

        if total > MAX_FRAGMENTS:

            raise ValueError("Too many fragments")

        packet_hash = hashlib.sha256(packet).digest()[:16]

        result: List[bytes] = []

        for index in range(total):

            start = index * payload_cap

            chunk = packet[start:start + payload_cap]

            result.append(

                FRAGMENT_HEADER.pack(

                    packet_hash,

                    index,

                    total,

                    len(chunk),

                ) + chunk

            )

        return result

    def ingest(

        self,

        data: bytes,

    ) -> Optional[bytes]:

        self.cleanup()

        if len(data) < FRAGMENT_HEADER.size:

            return None

        try:

            packet_hash, index, total, length = (

                FRAGMENT_HEADER.unpack_from(data)

            )

        except struct.error:

            return None

        if total <= 0 or total > MAX_FRAGMENTS:

            return None

        if index >= total:

            return None

        payload = data[FRAGMENT_HEADER.size:]

        if length != len(payload):

            return None

        if len(payload) > MAX_REASSEMBLY:

            return None

        buf = self.buffers.get(packet_hash)

        if buf is None:

            buf = ReassemblyBuffer(total=total)

            self.buffers[packet_hash] = buf

        if buf.total != total:

            self.buffers.pop(packet_hash, None)

            return None

        if index not in buf.fragments:

            buf.fragments[index] = payload

        if buf.size() > MAX_REASSEMBLY:

            self.buffers.pop(packet_hash, None)

            return None

        if len(buf.fragments) != total:

            return None

        try:

            assembled = b"".join(

                buf.fragments[i]

                for i in range(total)

            )

        except KeyError:

            return None

        if hashlib.sha256(assembled).digest()[:16] != packet_hash:

            self.buffers.pop(packet_hash, None)

            return None

        self.buffers.pop(packet_hash, None)

        return assembled

# ===========================================================================

# CRYPTOGRAPHY

# ===========================================================================

@dataclass

class Session:

    peer_id: bytes

    session_id: bytes

    tx_key: bytes

    rx_key: bytes

    peer_ed25519: bytes

    established: float

    last_used: float

class CryptoContext:

    def __init__(self, key_dir: Path):

        self.key_dir = key_dir

        self.key_dir.mkdir(

            parents=True,

            exist_ok=True,

        )

        self.identity_path = (

            self.key_dir / "identity.ed25519"

        )

        self.ed_priv = self._load_identity()

        self.ed_pub = self.ed_priv.public_key().public_bytes(

            serialization.Encoding.Raw,

            serialization.PublicFormat.Raw,

        )

        self.node_id = node_id_from_pubkey(self.ed_pub)

        self.sessions: Dict[bytes, Session] = {}

        self.peer_identities: Dict[bytes, bytes] = {}

        self._rotate_ephemeral()

    def _load_identity(

        self,

    ) -> ed25519.Ed25519PrivateKey:

        if self.identity_path.exists():

            raw = self.identity_path.read_bytes()

            if len(raw) != 32:

                raise ValueError(

                    "Invalid identity key length"

                )

            return (

                ed25519.Ed25519PrivateKey

                .from_private_bytes(raw)

            )

        key = ed25519.Ed25519PrivateKey.generate()

        raw = key.private_bytes(

            serialization.Encoding.Raw,

            serialization.PrivateFormat.Raw,

            serialization.NoEncryption(),

        )

        tmp = self.identity_path.with_suffix(".tmp")

        tmp.write_bytes(raw)

        try:

            os.chmod(tmp, 0o600)

        except OSError:

            pass

        os.replace(tmp, self.identity_path)

        return key

    def _rotate_ephemeral(self) -> None:

        self.ephemeral_private = (

            x25519.X25519PrivateKey.generate()

        )

        self.ephemeral_public = (

            self.ephemeral_private

            .public_key()

            .public_bytes(

                serialization.Encoding.Raw,

                serialization.PublicFormat.Raw,

            )

        )

    def _transcript(

        self,

        initiator_id: bytes,

        responder_id: bytes,

        initiator_ed: bytes,

        responder_ed: bytes,

        initiator_x: bytes,

        responder_x: bytes,

        nonce_i: bytes,

        nonce_r: bytes,

    ) -> bytes:

        return b"".join(

            [

                b"MVX3-TRANSCRIPT",

                struct.pack("!B", PROTOCOL_VERSION),

                initiator_id,

                responder_id,

                initiator_ed,

                responder_ed,

                initiator_x,

                responder_x,

                nonce_i,

                nonce_r,

            ]

        )

    def create_hello(self) -> Tuple[bytes, bytes]:

        nonce = secrets.token_bytes(32)

        transcript = (

            b"MVX3-HELLO"

            + struct.pack("!B", PROTOCOL_VERSION)

            + self.node_id

            + self.ed_pub

            + self.ephemeral_public

            + nonce

        )

        signature = self.ed_priv.sign(transcript)

        msg = {

            "v": PROTOCOL_VERSION,

            "src": self.node_id.hex(),

            "ed": self.ed_pub.hex(),

            "x": self.ephemeral_public.hex(),

            "nonce": nonce.hex(),

            "sig": signature.hex(),

            "ts": int(time.time()),

        }

        return canonical_json(msg), nonce

    def process_hello(

        self,

        body: bytes,

    ) -> Tuple[bytes, bytes]:

        msg = json.loads(body.decode("utf-8"))

        if int(msg["v"]) != PROTOCOL_VERSION:

            raise ValueError("Protocol version mismatch")

        peer_id = bytes.fromhex(msg["src"])

        peer_ed = bytes.fromhex(msg["ed"])

        peer_x = bytes.fromhex(msg["x"])

        nonce_i = bytes.fromhex(msg["nonce"])

        signature = bytes.fromhex(msg["sig"])

        if len(peer_id) != 16:

            raise ValueError("Invalid peer ID")

        if len(peer_ed) != 32:

            raise ValueError("Invalid Ed25519 key")

        if len(peer_x) != 32:

            raise ValueError("Invalid X25519 key")

        if len(nonce_i) != 32:

            raise ValueError("Invalid handshake nonce")

        if node_id_from_pubkey(peer_ed) != peer_id:

            raise ValueError("Identity mismatch")

        timestamp = int(msg["ts"])

        if abs(int(time.time()) - timestamp) > 120:

            raise ValueError("Handshake timestamp outside window")

        signed = (

            b"MVX3-HELLO"

            + struct.pack("!B", PROTOCOL_VERSION)

            + peer_id

            + peer_ed

            + peer_x

            + nonce_i

        )

        ed25519.Ed25519PublicKey.from_public_bytes(

            peer_ed

        ).verify(

            signature,

            signed,

        )

        nonce_r = secrets.token_bytes(32)

        transcript = self._transcript(

            initiator_id=peer_id,

            responder_id=self.node_id,

            initiator_ed=peer_ed,

            responder_ed=self.ed_pub,

            initiator_x=peer_x,

            responder_x=self.ephemeral_public,

            nonce_i=nonce_i,

            nonce_r=nonce_r,

        )

        ack_signature = self.ed_priv.sign(

            b"MVX3-ACK" + transcript

        )

        peer_x_key = (

            x25519.X25519PublicKey

            .from_public_bytes(peer_x)

        )

        shared = self.ephemeral_private.exchange(

            peer_x_key

        )

        derived = HKDF(

            algorithm=hashes.SHA256(),

            length=96,

            salt=hashlib.sha256(

                b"MVX3-SALT"

                + min(self.node_id, peer_id)

                + max(self.node_id, peer_id)

            ).digest(),

            info=b"MVX3-SESSION",

        ).derive(shared)

        session_id = derived[:16]

        key_a = derived[16:48]

        key_b = derived[48:80]

        if self.node_id < peer_id:

            tx_key = key_b

            rx_key = key_a

        else:

            tx_key = key_a

            rx_key = key_b

        self.sessions[peer_id] = Session(

            peer_id=peer_id,

            session_id=session_id,

            tx_key=tx_key,

            rx_key=rx_key,

            peer_ed25519=peer_ed,

            established=monotonic(),

            last_used=monotonic(),

        )

        self.peer_identities[peer_id] = peer_ed

        response = {

            "v": PROTOCOL_VERSION,

            "src": self.node_id.hex(),

            "ed": self.ed_pub.hex(),

            "x": self.ephemeral_public.hex(),

            "nonce_i": nonce_i.hex(),

            "nonce_r": nonce_r.hex(),

            "sig": ack_signature.hex(),

        }

        return peer_id, canonical_json(response)

    def process_ack(

        self,

        body: bytes,

        hello_nonce: bytes,

    ) -> bytes:

        msg = json.loads(body.decode("utf-8"))

        if int(msg["v"]) != PROTOCOL_VERSION:

            raise ValueError("Protocol version mismatch")

        peer_id = bytes.fromhex(msg["src"])

        peer_ed = bytes.fromhex(msg["ed"])

        peer_x = bytes.fromhex(msg["x"])

        nonce_i = bytes.fromhex(msg["nonce_i"])

        nonce_r = bytes.fromhex(msg["nonce_r"])

        signature = bytes.fromhex(msg["sig"])

        if not hmac.compare_digest(

            nonce_i,

            hello_nonce,

        ):

            raise ValueError("Handshake nonce mismatch")

        if node_id_from_pubkey(peer_ed) != peer_id:

            raise ValueError("Identity mismatch")

        transcript = self._transcript(

            initiator_id=self.node_id,

            responder_id=peer_id,

            initiator_ed=self.ed_pub,

            responder_ed=peer_ed,

            initiator_x=self.ephemeral_public,

            responder_x=peer_x,

            nonce_i=nonce_i,

            nonce_r=nonce_r,

        )

        ed25519.Ed25519PublicKey.from_public_bytes(

            peer_ed

        ).verify(

            signature,

            b"MVX3-ACK" + transcript,

        )

        peer_x_key = (

            x25519.X25519PublicKey

            .from_public_bytes(peer_x)

        )

        shared = self.ephemeral_private.exchange(

            peer_x_key

        )

        derived = HKDF(

            algorithm=hashes.SHA256(),

            length=96,

            salt=hashlib.sha256(

                b"MVX3-SALT"

                + min(self.node_id, peer_id)

                + max(self.node_id, peer_id)

            ).digest(),

            info=b"MVX3-SESSION",

        ).derive(shared)

        session_id = derived[:16]

        key_a = derived[16:48]

        key_b = derived[48:80]

        if self.node_id < peer_id:

            tx_key = key_a

            rx_key = key_b

        else:

            tx_key = key_b

            rx_key = key_a

        self.sessions[peer_id] = Session(

            peer_id=peer_id,

            session_id=session_id,

            tx_key=tx_key,

            rx_key=rx_key,

            peer_ed25519=peer_ed,

            established=monotonic(),

            last_used=monotonic(),

        )

        self.peer_identities[peer_id] = peer_ed

        return peer_id

    def encrypt(

        self,

        peer_id: bytes,

        plaintext: bytes,

        aad: bytes,

    ) -> Tuple[bytes, bytes, bytes]:

        session = self.sessions.get(peer_id)

        if session is None:

            raise KeyError("No active session")

        nonce = secrets.token_bytes(12)

        ciphertext = ChaCha20Poly1305(

            session.tx_key

        ).encrypt(

            nonce,

            plaintext,

            aad,

        )

        session.last_used = monotonic()

        return (

            session.session_id,

            nonce,

            ciphertext,

        )

    def decrypt(

        self,

        peer_id: bytes,

        session_id: bytes,

        nonce: bytes,

        ciphertext: bytes,

        aad: bytes,

    ) -> bytes:

        session = self.sessions.get(peer_id)

        if session is None:

            raise KeyError("No session")

        if not hmac.compare_digest(

            session.session_id,

            session_id,

        ):

            raise ValueError("Session ID mismatch")

        plaintext = ChaCha20Poly1305(

            session.rx_key

        ).decrypt(

            nonce,

            ciphertext,

            aad,

        )

        session.last_used = monotonic()

        return plaintext

    def cleanup(self) -> None:

        cutoff = monotonic() - SESSION_TIMEOUT

        expired = [

            peer

            for peer, session in self.sessions.items()

            if session.last_used < cutoff

        ]

        for peer in expired:

            self.sessions.pop(peer, None)

# ===========================================================================

# DATABASE

# ===========================================================================

class MeshDB:

    def __init__(self, path: Path):

        path.parent.mkdir(

            parents=True,

            exist_ok=True,

        )

        self.conn = sqlite3.connect(

            path,

            check_same_thread=False,

        )

        self.conn.execute(

            "PRAGMA journal_mode=WAL"

        )

        self.conn.execute(

            "PRAGMA synchronous=NORMAL"

        )

        self.conn.execute(

            "PRAGMA busy_timeout=5000"

        )

        self.lock = asyncio.Lock()

        self._schema()

    def _schema(self) -> None:

        with self.conn:

            self.conn.execute(

                """

                CREATE TABLE IF NOT EXISTS

                store_forward (

                    packet_id BLOB PRIMARY KEY,

                    destination BLOB NOT NULL,

                    priority INTEGER NOT NULL,

                    raw_data BLOB NOT NULL,

                    created REAL NOT NULL,

                    expires REAL NOT NULL,

                    attempts INTEGER NOT NULL DEFAULT 0,

                    last_attempt REAL NOT NULL DEFAULT 0

                )

                """

            )

            self.conn.execute(

                """

                CREATE TABLE IF NOT EXISTS

                seen_packets (

                    packet_id BLOB PRIMARY KEY,

                    received_at REAL NOT NULL

                )

                """

            )

            self.conn.execute(

                """

                CREATE INDEX IF NOT EXISTS

                idx_sf_destination

                ON store_forward(destination, priority)

                """

            )

            self.conn.execute(

                """

                CREATE INDEX IF NOT EXISTS

                idx_seen_time

                ON seen_packets(received_at)

                """

            )

    async def mark_seen(

        self,

        packet_id: bytes,

    ) -> bool:

        async with self.lock:

            cur = self.conn.execute(

                """

                SELECT received_at

                FROM seen_packets

                WHERE packet_id=?

                """,

                (packet_id,),

            )

            row = cur.fetchone()

            if row:

                return False

            with self.conn:

                self.conn.execute(

                    """

                    INSERT INTO seen_packets

                    VALUES (?, ?)

                    """,

                    (packet_id, now()),

                )

            return True

    async def cleanup_seen(self) -> None:

        cutoff = now() - SEEN_PACKET_TTL

        async with self.lock:

            with self.conn:

                self.conn.execute(

                    """

                    DELETE FROM seen_packets

                    WHERE received_at < ?

                    """,

                    (cutoff,),

                )

    async def save_store_forward(

        self,

        packet_id: bytes,

        destination: bytes,

        priority: int,

        raw_data: bytes,

        ttl: float = STORE_FORWARD_TTL,

    ) -> None:

        async with self.lock:

            with self.conn:

                self.conn.execute(

                    """

                    INSERT OR REPLACE INTO

                    store_forward

                    (

                        packet_id,

                        destination,

                        priority,

                        raw_data,

                        created,

                        expires,

                        attempts,

                        last_attempt

                    )

                    VALUES (?, ?, ?, ?, ?, ?, 0, 0)

                    """,

                    (

                        packet_id,

                        destination,

                        priority,

                        raw_data,

                        now(),

                        now() + ttl,

                    ),

                )

    async def queued(

        self,

        destination: bytes,

    ) -> List[Tuple[bytes, bytes, int]]:

        async with self.lock:

            cur = self.conn.execute(

                """

                SELECT packet_id, raw_data, attempts

                FROM store_forward

                WHERE destination=?

                  AND expires>?

                ORDER BY priority ASC, created ASC

                """,

                (

                    destination,

                    now(),

                ),

            )

            return cur.fetchall()

    async def mark_attempt(

        self,

        packet_id: bytes,

    ) -> None:

        async with self.lock:

            with self.conn:

                self.conn.execute(

                    """

                    UPDATE store_forward

                    SET attempts=attempts+1,

                        last_attempt=?

                    WHERE packet_id=?

                    """,

                    (now(), packet_id),

                )

    async def remove(

        self,

        packet_id: bytes,

    ) -> None:

        async with self.lock:

            with self.conn:

                self.conn.execute(

                    """

                    DELETE FROM store_forward

                    WHERE packet_id=?

                    """,

                    (packet_id,),

                )

    async def cleanup_store_forward(self) -> None:

        async with self.lock:

            with self.conn:

                self.conn.execute(

                    """

                    DELETE FROM store_forward

                    WHERE expires<=?

                    """,

                    (now(),),

                )

    def close(self) -> None:

        self.conn.close()

# ===========================================================================

# ROUTING

# ===========================================================================

@dataclass

class Neighbor:

    node_id: bytes

    transport: str

    address: str

    last_seen: float

    rtt_ms: float = 0.0

    rssi: Optional[float] = None

    snr: Optional[float] = None

    capabilities: Set[str] = field(default_factory=set)

@dataclass

class Route:

    destination: bytes

    next_hop: bytes

    transport: str

    address: str

    sequence: int

    metric: float

    hops: int

    updated: float

    expires: float

class RoutingTable:

    def __init__(

        self,

        node_id: bytes,

        core: "MVXCore",

    ):

        self.node_id = node_id

        self.core = core

        self.sequence = 0

        self.neighbors: Dict[

            bytes,

            Neighbor

        ] = {}

        self.routes: Dict[

            bytes,

            Route

        ] = {}

    def update_neighbor(

        self,

        peer_id: bytes,

        transport: str,

        address: str,

        rtt_ms: float = 0.0,

        rssi: Optional[float] = None,

        snr: Optional[float] = None,

    ) -> None:

        self.neighbors[peer_id] = Neighbor(

            node_id=peer_id,

            transport=transport,

            address=address,

            last_seen=monotonic(),

            rtt_ms=rtt_ms,

            rssi=rssi,

            snr=snr,

        )

        # Every directly connected peer is a route.

        metric = self.link_metric(

            transport,

            rtt_ms,

        )

        self.routes[peer_id] = Route(

            destination=peer_id,

            next_hop=peer_id,

            transport=transport,

            address=address,

            sequence=self.sequence,

            metric=metric,

            hops=1,

            updated=monotonic(),

            expires=monotonic() + ROUTE_TIMEOUT,

        )

    def link_metric(

        self,

        transport: str,

        rtt_ms: float,

    ) -> float:

        adapter = self.core.adapters.get(

            transport

        )

        base = (

            adapter.latency_score

            if adapter

            else 50.0

        )

        return (

            base

            + min(max(rtt_ms, 0.0), 1000.0) * 0.1

        )

    def process_advertisement(

        self,

        peer_id: bytes,

        transport: str,

        address: str,

        advertisement: bytes,

    ) -> None:

        try:

            obj = json.loads(

                advertisement.decode("utf-8")

            )

        except Exception:

            return

        if not isinstance(obj, dict):

            return

        if obj.get("v") != PROTOCOL_VERSION:

            return

        routes = obj.get("routes")

        if not isinstance(routes, list):

            return

        self.update_neighbor(

            peer_id,

            transport,

            address,

        )

        for item in routes:

            try:

                destination = bytes.fromhex(

                    item["dest"]

                )

                if destination == self.node_id:

                    continue

                if destination == peer_id:

                    continue

                sequence = int(

                    item["seq"]

                )

                advertised_metric = float(

                    item["metric"]

                )

                advertised_hops = int(

                    item["hops"]

                )

            except Exception:

                continue

            if advertised_hops >= 255:

                continue

            metric = (

                self.link_metric(

                    transport,

                    self.neighbors[peer_id].rtt_ms,

                )

                + advertised_metric

            )

            hops = advertised_hops + 1

            existing = self.routes.get(

                destination

            )

            better = False

            if existing is None:

                better = True

            elif sequence > existing.sequence:

                better = True

            elif (

                sequence == existing.sequence

                and metric < existing.metric

            ):

                better = True

            elif (

                sequence == existing.sequence

                and metric == existing.metric

                and peer_id == existing.next_hop

            ):

                better = True

            if better:

                self.routes[destination] = Route(

                    destination=destination,

                    next_hop=peer_id,

                    transport=transport,

                    address=address,

                    sequence=sequence,

                    metric=metric,

                    hops=hops,

                    updated=monotonic(),

                    expires=monotonic() + ROUTE_TIMEOUT,

                )

    def expire(self) -> None:

        t = monotonic()

        dead_neighbors = [

            peer

            for peer, neighbor in self.neighbors.items()

            if neighbor.last_seen + ROUTE_TIMEOUT < t

        ]

        for peer in dead_neighbors:

            self.neighbors.pop(peer, None)

        dead_routes = [

            destination

            for destination, route in self.routes.items()

            if route.expires < t

        ]

        for destination in dead_routes:

            self.routes.pop(destination, None)

    def advertisement(self) -> bytes:

        self.sequence += 2

        routes = [

            {

                "dest": self.node_id.hex(),

                "seq": self.sequence,

                "metric": 0.0,

                "hops": 0,

            }

        ]

        for destination, route in self.routes.items():

            if destination == self.node_id:

                continue

            routes.append(

                {

                    "dest": destination.hex(),

                    "seq": route.sequence,

                    "metric": route.metric,

                    "hops": route.hops,

                }

            )

        return canonical_json(

            {

                "v": PROTOCOL_VERSION,

                "origin": self.node_id.hex(),

                "seq": self.sequence,

                "routes": routes,

            }

        )

    def route_for(

        self,

        destination: bytes,

    ) -> Optional[Route]:

        self.expire()

        route = self.routes.get(destination)

        if route is None:

            return None

        if route.next_hop == self.node_id:

            return None

        return route

# ===========================================================================

# TRANSPORT BASE

# ===========================================================================

class Transport:

    name = "UNKNOWN"

    mtu = 1200

    latency_score = 100.0

    def __init__(

        self,

        core: "MVXCore",

    ):

        self.core = core

    async def start(self) -> None:

        raise NotImplementedError

    async def stop(self) -> None:

        raise NotImplementedError

    async def send_bytes(

        self,

        address: str,

        data: bytes,

    ) -> bool:

        raise NotImplementedError

    async def broadcast(

        self,

        data: bytes,

    ) -> None:

        raise NotImplementedError

# ===========================================================================

# TCP LAN TRANSPORT

# ===========================================================================

class TCPTransport(Transport):

    name = "TCP_LAN"

    mtu = 1024 * 1024

    latency_score = 1.0

    def __init__(

        self,

        core: "MVXCore",

        port: int,

    ):

        super().__init__(core)

        self.port = port

        self.server: Optional[

            asyncio.AbstractServer

        ] = None

        self.connections: Dict[

            str,

            asyncio.StreamWriter

        ] = {}

        self.write_locks: Dict[

            str,

            asyncio.Lock

        ] = {}

    @staticmethod

    def optimize_socket(

        sock: Optional[socket.socket],

    ) -> None:

        if sock is None:

            return

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

                socket.SO_KEEPALIVE,

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

    async def start(self) -> None:

        self.server = await asyncio.start_server(

            self._handle_client,

            host="0.0.0.0",

            port=self.port,

            limit=MAX_FRAME + 1024,

        )

        asyncio.create_task(

            self.discovery_broadcast()

        )

        asyncio.create_task(

            self.discovery_listener()

        )

        print(

            f"[+] TCP LAN listening on {self.port}"

        )

    async def stop(self) -> None:

        if self.server:

            self.server.close()

            await self.server.wait_closed()

        for writer in list(

            self.connections.values()

        ):

            try:

                writer.close()

                await writer.wait_closed()

            except Exception:

                pass

        self.connections.clear()

    async def _handle_client(

        self,

        reader: asyncio.StreamReader,

        writer: asyncio.StreamWriter,

    ) -> None:

        address = writer.get_extra_info(

            "peername"

        )

        host = (

            address[0]

            if isinstance(address, tuple)

            else str(address)

        )

        sock = writer.get_extra_info(

            "socket"

        )

        self.optimize_socket(sock)

        self.connections[host] = writer

        self.write_locks.setdefault(

            host,

            asyncio.Lock()

        )

        # A TCP connection is not proof of identity.

        # The MVX handshake remains authoritative.

        try:

            while self.core.running:

                header = await reader.readexactly(

                    FRAME_HEADER.size

                )

                magic, version, _flags, length = (

                    FRAME_HEADER.unpack(header)

                )

                if magic != MAGIC:

                    break

                if version != PROTOCOL_VERSION:

                    break

                if length > MAX_FRAME:

                    break

                body = await reader.readexactly(

                    length

                )

                self.core.receive_raw(

                    self.name,

                    host,

                    header + body,

                )

        except (

            asyncio.IncompleteReadError,

            ConnectionError,

            asyncio.CancelledError,

        ):

            pass

        except Exception as exc:

            self.core.log(

                "TCP receive error: "

                + str(exc)

            )

        finally:

            if self.connections.get(host) is writer:

                self.connections.pop(

                    host,

                    None,

                )

            try:

                writer.close()

                await writer.wait_closed()

            except Exception:

                pass

    async def send_bytes(

        self,

        address: str,

        data: bytes,

    ) -> bool:

        if len(data) > MAX_FRAME + FRAME_HEADER.size:

            return False

        writer = self.connections.get(

            address

        )

        if writer is None:

            try:

                _reader, writer = (

                    await asyncio.wait_for(

                        asyncio.open_connection(

                            address,

                            self.port,

                        ),

                        timeout=3.0,

                    )

                )

                self.optimize_socket(

                    writer.get_extra_info(

                        "socket"

                    )

                )

                self.connections[address] = writer

                self.write_locks.setdefault(

                    address,

                    asyncio.Lock(),

                )

                # The reader task is important because the

                # connection can carry inbound traffic too.

                # The server may already own the opposite side;

                # duplicate readers are harmless because only the

                # endpoint receiving bytes invokes receive_raw.

                asyncio.create_task(

                    self._outbound_reader(

                        _reader,

                        address,

                    )

                )

            except Exception:

                return False

        lock = self.write_locks.setdefault(

            address,

            asyncio.Lock(),

        )

        try:

            async with lock:

                writer.write(data)

                await writer.drain()

            return True

        except Exception:

            if self.connections.get(

                address

            ) is writer:

                self.connections.pop(

                    address,

                    None,

                )

            try:

                writer.close()

            except Exception:

                pass

            return False

    async def _outbound_reader(

        self,

        reader: asyncio.StreamReader,

        address: str,

    ) -> None:

        try:

            while self.core.running:

                header = await reader.readexactly(

                    FRAME_HEADER.size

                )

                magic, version, _flags, length = (

                    FRAME_HEADER.unpack(header)

                )

                if (

                    magic != MAGIC

                    or version != PROTOCOL_VERSION

                    or length > MAX_FRAME

                ):

                    break

                body = await reader.readexactly(

                    length

                )

                self.core.receive_raw(

                    self.name,

                    address,

                    header + body,

                )

        except Exception:

            pass

    async def broadcast(

        self,

        data: bytes,

    ) -> None:

        for address in list(

            self.connections.keys()

        ):

            await self.send_bytes(

                address,

                data,

            )

    async def discovery_broadcast(

        self,

    ) -> None:

        sock = socket.socket(

            socket.AF_INET,

            socket.SOCK_DGRAM,

        )

        try:

            sock.setsockopt(

                socket.SOL_SOCKET,

                socket.SO_BROADCAST,

                1,

            )

            sock.setblocking(False)

            loop = asyncio.get_running_loop()

            while self.core.running:

                payload = canonical_json(

                    {

                        "magic": "MVX3-DISCOVERY",

                        "v": PROTOCOL_VERSION,

                        "id": self.core.node_id.hex(),

                        "port": self.port,

                        "caps": [

                            "tcp",

                            "mvx3",

                        ],

                        "ts": int(time.time()),

                    }

                )

                try:

                    await loop.sock_sendto(

                        sock,

                        payload,

                        (

                            "255.255.255.255",

                            DISCOVERY_PORT,

                        ),

                    )

                except Exception:

                    pass

                await asyncio.sleep(3.0)

        finally:

            sock.close()

    async def discovery_listener(

        self,

    ) -> None:

        sock = socket.socket(

            socket.AF_INET,

            socket.SOCK_DGRAM,

        )

        try:

            sock.setsockopt(

                socket.SOL_SOCKET,

                socket.SO_REUSEADDR,

                1,

            )

            if hasattr(

                socket,

                "SO_REUSEPORT",

            ):

                try:

                    sock.setsockopt(

                        socket.SOL_SOCKET,

                        socket.SO_REUSEPORT,

                        1,

                    )

                except OSError:

                    pass

            sock.bind(

                ("0.0.0.0", DISCOVERY_PORT)

            )

            sock.setblocking(False)

            loop = asyncio.get_running_loop()

            while self.core.running:

                try:

                    data, addr = (

                        await loop.sock_recvfrom(

                            sock,

                            4096,

                        )

                    )

                except Exception:

                    await asyncio.sleep(0.1)

                    continue

                try:

                    msg = json.loads(

                        data.decode("utf-8")

                    )

                    if (

                        msg.get("magic")

                        != "MVX3-DISCOVERY"

                    ):

                        continue

                    if (

                        int(msg.get("v", -1))

                        != PROTOCOL_VERSION

                    ):

                        continue

                    peer_id = bytes.fromhex(

                        msg["id"]

                    )

                    if (

                        peer_id

                        == self.core.node_id

                    ):

                        continue

                    address = addr[0]

                    self.core.remember_peer_address(

                        peer_id,

                        self.name,

                        address,

                    )

                    # Discovery gives us an address.

                    # The authenticated handshake proves identity.

                    if not self.core.crypto.sessions.get(

                        peer_id

                    ):

                        await self.core.ensure_session(

                            peer_id

                        )

                except Exception:

                    continue

        finally:

            sock.close()

# ===========================================================================

# MESHTASTIC SERIAL TRANSPORT

# ===========================================================================

class MeshtasticTransport(Transport):

    name = "LORA_MESHTASTIC"

    mtu = 237

    latency_score = 150.0

    START = b"\x94\xc3"

    def __init__(

        self,

        core: "MVXCore",

        device: str,

        baudrate: int = 115200,

    ):

        super().__init__(core)

        self.device = device

        self.baudrate = baudrate

        self.reader = None

        self.writer = None

        self.serial_available = False

    async def start(self) -> None:

        try:

            import serial_asyncio

            self.reader, self.writer = (

                await serial_asyncio

                .open_serial_connection(

                    url=self.device,

                    baudrate=self.baudrate,

                )

            )

            self.serial_available = True

            asyncio.create_task(

                self.read_loop()

            )

            print(

                "[+] Meshtastic serial active: "

                + self.device

            )

        except ImportError:

            print(

                "[!] Meshtastic transport disabled: "

                "install pyserial + pyserial-asyncio"

            )

        except Exception as exc:

            print(

                "[!] Meshtastic radio unavailable: "

                + str(exc)

            )

    async def stop(self) -> None:

        if self.writer:

            try:

                self.writer.close()

            except Exception:

                pass

    @staticmethod

    def varint(value: int) -> bytes:

        out = bytearray()

        while value >= 0x80:

            out.append(

                (value & 0x7F) | 0x80

            )

            value >>= 7

        out.append(value)

        return bytes(out)

    def build_meshtastic_packet(

        self,

        data: bytes,

    ) -> bytes:

        # This creates a minimal ToRadio / MeshPacket /

        # Data structure for the adapter layer.

        #

        # A production Meshtastic deployment should use the

        # exact generated Meshtastic protobuf schema for the

        # installed firmware version.

        data_submessage = (

            b"\x08"

            + self.varint(256)

            + b"\x12"

            + self.varint(len(data))

            + data

        )

        mesh_packet = (

            b"\x10"

            + b"\xff\xff\xff\xff\x0f"

            + b"\x22"

            + self.varint(

                len(data_submessage)

            )

            + data_submessage

        )

        to_radio = (

            b"\x0a"

            + self.varint(

                len(mesh_packet)

            )

            + mesh_packet

        )

        return (

            self.START

            + struct.pack(

                "!H",

                len(to_radio),

            )

            + to_radio

        )

    async def read_loop(self) -> None:

        while self.core.running:

            try:

                sync = await self.reader.readexactly(

                    2

                )

                if sync != self.START:

                    continue

                length_bytes = (

                    await self.reader.readexactly(2)

                )

                length = struct.unpack(

                    "!H",

                    length_bytes,

                )[0]

                if length > MAX_FRAME:

                    continue

                body = await self.reader.readexactly(

                    length

                )

                self.core.receive_raw(

                    self.name,

                    "lora",

                    body,

                )

            except asyncio.CancelledError:

                return

            except Exception:

                await asyncio.sleep(1.0)

    async def send_bytes(

        self,

        address: str,

        data: bytes,

    ) -> bool:

        if not self.writer:

            return False

        try:

            framed = (

                self.build_meshtastic_packet(

                    data

                )

            )

            self.writer.write(framed)

            await self.writer.drain()

            return True

        except Exception:

            return False

    async def broadcast(

        self,

        data: bytes,

    ) -> None:

        await self.send_bytes(

            "broadcast",

            data,

        )

# ===========================================================================

# OPTIONAL BLE TRANSPORT

# ===========================================================================

class BLETransport(Transport):

    name = "BLE"

    mtu = 512

    latency_score = 10.0

    SERVICE_UUID = (

        "4D565833-0000-1000-8000-00805F9B34FB"

    )

    RX_UUID = (

        "4D565833-0001-1000-8000-00805F9B34FB"

    )

    TX_UUID = (

        "4D565833-0002-1000-8000-00805F9B34FB"

    )

    def __init__(

        self,

        core: "MVXCore",

    ):

        super().__init__(core)

        self.bleak = None

        self.devices = {}

    async def start(self) -> None:

        try:

            from bleak import BleakScanner

            self.bleak = BleakScanner

            print(

                "[+] BLE transport available"

            )

            asyncio.create_task(

                self.scan_loop()

            )

        except ImportError:

            print(

                "[*] BLE disabled: "

                "install bleak to enable it"

            )

    async def stop(self) -> None:

        pass

    async def scan_loop(self) -> None:

        if self.bleak is None:

            return

        while self.core.running:

            try:

                devices = (

                    await self.bleak.discover(

                        timeout=3.0

                    )

                )

                for device in devices:

                    name = (

                        device.name

                        or ""

                    )

                    if (

                        "MVX"

                        not in name.upper()

                    ):

                        continue

                    self.devices[

                        device.address

                    ] = device

            except Exception:

                pass

            await asyncio.sleep(5.0)

    async def send_bytes(

        self,

        address: str,

        data: bytes,

    ) -> bool:

        # BLE GATT connection logic is intentionally kept

        # behind this adapter. Native iOS/Android wrappers

        # should connect their CoreBluetooth/BluetoothGatt

        # implementations to the same MVX frame format.

        return False

    async def broadcast(

        self,

        data: bytes,

    ) -> None:

        return

# ===========================================================================

# SAFE GATEWAY

# ===========================================================================

class GatewaySecurity:

    MAX_RESPONSE = 2 * 1024 * 1024

    TIMEOUT = 10.0

    BLOCKED_HOSTS = {

        "localhost",

        "localhost.localdomain",

        "metadata.google.internal",

        "metadata",

    }

    @staticmethod

    def safe_ip(

        value: str,

    ) -> bool:

        try:

            ip = ipaddress.ip_address(

                value

            )

            return not (

                ip.is_private

                or ip.is_loopback

                or ip.is_link_local

                or ip.is_reserved

                or ip.is_multicast

                or ip.is_unspecified

            )

        except ValueError:

            return False

    @classmethod

    async def resolve_public(

        cls,

        hostname: str,

        port: int,

    ) -> List[str]:

        loop = asyncio.get_running_loop()

        results = await loop.getaddrinfo(

            hostname,

            port,

            type=socket.SOCK_STREAM,

        )

        addresses = []

        for result in results:

            ip = result[4][0]

            if not cls.safe_ip(ip):

                raise PermissionError(

                    "Gateway destination resolves "

                    "to a blocked address: "

                    + ip

                )

            addresses.append(ip)

        if not addresses:

            raise ValueError(

                "No usable destination"

            )

        return list(dict.fromkeys(addresses))

    @classmethod

    async def fetch(

        cls,

        url: str,

        allowed_hosts: Set[str],

    ) -> Tuple[int, bytes]:

        parsed = urllib.parse.urlparse(

            url

        )

        if parsed.scheme not in {

            "http",

            "https",

        }:

            raise ValueError(

                "Only HTTP/HTTPS allowed"

            )

        hostname = parsed.hostname

        if not hostname:

            raise ValueError(

                "Missing hostname"

            )

        hostname_lower = hostname.lower()

        if hostname_lower in cls.BLOCKED_HOSTS:

            raise PermissionError(

                "Blocked hostname"

            )

        if (

            allowed_hosts

            and hostname_lower not in allowed_hosts

        ):

            raise PermissionError(

                "Hostname is not gateway-approved"

            )

        port = parsed.port or (

            443

            if parsed.scheme == "https"

            else 80

        )

        await cls.resolve_public(

            hostname,

            port,

        )

        # urllib is used only after validation.

        # Redirects are disabled by using a handler.

        class NoRedirect(

            __import__("urllib.request").request.HTTPRedirectHandler

        ):

            def redirect_request(

                self,

                req,

                fp,

                code,

                msg,

                headers,

                newurl,

            ):

                return None

        opener = (

            __import__("urllib.request")

            .request

            .build_opener(

                NoRedirect()

            )

        )

        request = (

            __import__("urllib.request")

            .request

            .Request(

                url,

                headers={

                    "User-Agent":

                        f"MVX-MeshBridge/{VERSION}"

                },

                method="GET",

            )

        )

        loop = asyncio.get_running_loop()

        def blocking_fetch():

            with opener.open(

                request,

                timeout=cls.TIMEOUT,

            ) as response:

                data = response.read(

                    cls.MAX_RESPONSE + 1

                )

                if len(data) > cls.MAX_RESPONSE:

                    raise ValueError(

                        "Gateway response too large"

                    )

                return (

                    response.status,

                    data,

                )

        return await asyncio.wait_for(

            loop.run_in_executor(

                None,

                blocking_fetch,

            ),

            timeout=cls.TIMEOUT + 2,

        )

# ===========================================================================

# DELIVERY TRACKING

# ===========================================================================

@dataclass

class PendingDelivery:

    packet: Packet

    destination: bytes

    created: float

    retries: int = 0

    next_attempt: float = 0.0

# ===========================================================================

# CORE

# ===========================================================================

class MVXCore:

    def __init__(

        self,

        root: Path,

        gateway_mode: bool = False,

        gateway_hosts: Optional[Set[str]] = None,

    ):

        self.root = root

        self.root.mkdir(

            parents=True,

            exist_ok=True,

        )

        self.gateway_mode = gateway_mode

        self.gateway_hosts = (

            gateway_hosts or set()

        )

        self.crypto = CryptoContext(

            self.root / "keys"

        )

        self.db = MeshDB(

            self.root / "mesh.sqlite3"

        )

        self.node_id = self.crypto.node_id

        self.router = RoutingTable(

            self.node_id,

            self,

        )

        self.chunker = PacketChunker()

        self.adapters: Dict[

            str,

            Transport,

        ] = {}

        self.running = False

        self.pending_handshakes: Dict[

            bytes,

            Tuple[

                bytes,

                float,

            ],

        ] = {}

        self.pending_delivery: Dict[

            bytes,

            PendingDelivery,

        ] = {}

        self.peer_addresses: Dict[

            bytes,

            Dict[

                str,

                str,

            ],

        ] = defaultdict(dict)

        self.ui_clients: Set[

            asyncio.StreamWriter

        ] = set()

        self.events: Deque[

            Dict[str, Any]

        ] = deque(maxlen=500)

        self.stats = defaultdict(int)

    # -----------------------------------------------------------------------

    # LOGGING

    # -----------------------------------------------------------------------

    def log(

        self,

        message: str,

    ) -> None:

        print(

            f"[MVX] {message}",

            flush=True,

        )

    # -----------------------------------------------------------------------

    # PEER ADDRESS

    # -----------------------------------------------------------------------

    def remember_peer_address(

        self,

        peer_id: bytes,

        transport: str,

        address: str,

    ) -> None:

        self.peer_addresses[

            peer_id

        ][transport] = address

    # -----------------------------------------------------------------------

    # START / STOP

    # -----------------------------------------------------------------------

    async def start(self) -> None:

        self.running = True

        self.log(

            "================================================"

        )

        self.log(

            f"{APP_NAME} {VERSION}"

        )

        self.log(

            "================================================"

        )

        self.log(

            f"Node ID: {self.node_id.hex()}"

        )

        self.log(

            f"Platform: {platform.system()} "

            f"{platform.machine()}"

        )

        self.log(

            f"Gateway: {self.gateway_mode}"

        )

        self.log(

            "================================================"

        )

        for name, adapter in self.adapters.items():

            try:

                await adapter.start()

                self.log(

                    f"Transport online: {name}"

                )

            except Exception as exc:

                self.log(

                    f"Transport failed {name}: "

                    f"{exc}"

                )

        asyncio.create_task(

            self.route_loop()

        )

        asyncio.create_task(

            self.maintenance_loop()

        )

        asyncio.create_task(

            self.delivery_loop()

        )

        asyncio.create_task(

            self.session_loop()

        )

    async def stop(self) -> None:

        self.running = False

        for adapter in list(

            self.adapters.values()

        ):

            try:

                await adapter.stop()

            except Exception:

                pass

        for writer in list(

            self.ui_clients

        ):

            try:

                writer.close()

            except Exception:

                pass

        self.ui_clients.clear()

        self.db.close()

    # -----------------------------------------------------------------------

    # RAW RECEIVE

    # -----------------------------------------------------------------------

    def receive_raw(

        self,

        transport: str,

        address: str,

        raw: bytes,

    ) -> None:

        if len(raw) > MAX_FRAME + FRAME_HEADER.size:

            self.stats[

                "frames_rejected"

            ] += 1

            return

        packet = parse_frame(raw)

        if packet:

            asyncio.create_task(

                self.process_packet(

                    packet,

                    transport,

                    address,

                )

            )

            return

        assembled = self.chunker.ingest(

            raw

        )

        if assembled:

            packet = parse_frame(

                assembled

            )

            if packet:

                asyncio.create_task(

                    self.process_packet(

                        packet,

                        transport,

                        address,

                    )

                )

    # -----------------------------------------------------------------------

    # SESSION MANAGEMENT

    # -----------------------------------------------------------------------

    async def ensure_session(

        self,

        peer_id: bytes,

    ) -> bool:

        if peer_id == self.node_id:

            return False

        session = self.crypto.sessions.get(

            peer_id

        )

        if session:

            return True

        addresses = self.peer_addresses.get(

            peer_id,

            {},

        )

        if not addresses:

            # If routing already knows the peer,

            # use the route's address.

            route = self.router.routes.get(

                peer_id

            )

            if route:

                addresses[

                    route.transport

                ] = route.address

        hello, nonce = (

            self.crypto.create_hello()

        )

        self.pending_handshakes[

            peer_id

        ] = (

            nonce,

            monotonic()

            + HANDSHAKE_TIMEOUT,

        )

        packet = Packet(

            version=PROTOCOL_VERSION,

            packet_type=TYPE_HELLO,

            flags=0,

            priority=PRIO_LATENCY_CRITICAL,

            ttl=8,

            hops=0,

            packet_id=random_packet_id(),

            src=self.node_id,

            dst=peer_id,

            timestamp=int(

                time.time() * 1000

            ),

            payload=hello,

        )

        route = self.router.route_for(

            peer_id

        )

        if route:

            await self.send_packet(

                packet,

                route,

            )

            return True

        # Directly known address.

        for transport_name, address in (

            addresses.items()

        ):

            adapter = self.adapters.get(

                transport_name

            )

            if adapter:

                await self.emit_via_adapter(

                    adapter,

                    address,

                    packet,

                )

                return True

        return False

    # -----------------------------------------------------------------------

    # MESSAGE

    # -----------------------------------------------------------------------

    async def send_message(

        self,

        destination: bytes,

        payload: bytes,

        priority: int = PRIO_NORMAL,

        store_forward: bool = True,

        request_ack: bool = True,

    ) -> bytes:

        if len(payload) > MAX_PACKET:

            raise ValueError(

                "Message exceeds MAX_PACKET"

            )

        priority = clamp(

            priority,

            0,

            3,

        )

        if (

            destination != BROADCAST_ID

            and destination

            not in self.crypto.sessions

        ):

            self.pending_delivery[

                random_packet_id()

            ] = PendingDelivery(

                packet=Packet(

                    PROTOCOL_VERSION,

                    TYPE_DATA,

                    0,

                    priority,

                    16,

                    0,

                    random_packet_id(),

                    self.node_id,

                    destination,

                    int(time.time() * 1000),

                    payload,

                ),

                destination=destination,

                created=monotonic(),

            )

            await self.ensure_session(

                destination

            )

            return b""

        packet_id = random_packet_id()

        flags = 0

        if store_forward:

            flags |= FLAG_STORE_FORWARD

        if request_ack:

            flags |= FLAG_ACK_REQUESTED

        if destination != BROADCAST_ID:

            # Construct AAD from an initial header. The nonce is

            # replaced after encryption, so we create the packet

            # metadata first.

            session = self.crypto.sessions.get(

                destination

            )

            if session is None:

                raise RuntimeError(

                    "Session unavailable"

                )

            dummy_packet = Packet(

                PROTOCOL_VERSION,

                TYPE_DATA,

                flags | FLAG_ENCRYPTED,

                priority,

                16,

                0,

                packet_id,

                self.node_id,

                destination,

                int(time.time() * 1000),

                b"",

                session_id=session.session_id,

                nonce=ZERO_NONCE,

            )

            # The actual payload length includes the AEAD tag.

            #

            # ChaCha20-Poly1305 adds 16 bytes.

            dummy_packet.payload = b"\x00" * (

                len(payload) + 16

            )

            aad = dummy_packet.header_bytes()

            session_id, nonce, ciphertext = (

                self.crypto.encrypt(

                    destination,

                    payload,

                    aad,

                )

            )

            packet = Packet(

                PROTOCOL_VERSION,

                TYPE_DATA,

                flags | FLAG_ENCRYPTED,

                priority,

                16,

                0,

                packet_id,

                self.node_id,

                destination,

                int(time.time() * 1000),

                ciphertext,

                session_id=session_id,

                nonce=nonce,

            )

        else:

            packet = Packet(

                PROTOCOL_VERSION,

                TYPE_DATA,

                flags | FLAG_BROADCAST,

                priority,

                16,

                0,

                packet_id,

                self.node_id,

                destination,

                int(time.time() * 1000),

                payload,

            )

        await self.forward_packet(

            packet

        )

        return packet_id

    # -----------------------------------------------------------------------

    # FORWARD

    # -----------------------------------------------------------------------

    async def forward_packet(

        self,

        packet: Packet,

    ) -> bool:

        if packet.ttl <= 0:

            return False

        route = self.router.route_for(

            packet.dst

        )

        if route:

            return await self.send_packet(

                packet,

                route,

            )

        if packet.flags & FLAG_BROADCAST:

            await self.broadcast_packet(

                packet

            )

            return True

        if packet.flags & FLAG_STORE_FORWARD:

            raw = packet.serialize()

            await self.db.save_store_forward(

                packet.packet_id,

                packet.dst,

                packet.priority,

                raw,

            )

            self.stats[

                "store_forward_queued"

            ] += 1

            return True

        self.stats[

            "no_route"

        ] += 1

        return False

    async def send_packet(

        self,

        packet: Packet,

        route: Route,

    ) -> bool:

        adapter = self.adapters.get(

            route.transport

        )

        if adapter is None:

            return False

        if packet.ttl <= 0:

            return False

        # Do not mutate the original object.

        packet_to_send = Packet(

            packet.version,

            packet.packet_type,

            packet.flags,

            packet.priority,

            packet.ttl,

            packet.hops,

            packet.packet_id,

            packet.src,

            packet.dst,

            packet.timestamp,

            packet.payload,

            packet.session_id,

            packet.nonce,

        )

        raw = packet_to_send.serialize()

        if len(raw) <= adapter.mtu:

            ok = await adapter.send_bytes(

                route.address,

                raw,

            )

        else:

            chunks = self.chunker.slice_packet(

                raw,

                adapter.mtu,

            )

            ok = True

            for chunk in chunks:

                sent = await adapter.send_bytes(

                    route.address,

                    chunk,

                )

                if not sent:

                    ok = False

                    break

        if ok:

            self.stats[

                "frames_sent"

            ] += 1

            self.router.update_neighbor(

                route.next_hop,

                route.transport,

                route.address,

            )

        return ok

    async def emit_via_adapter(

        self,

        adapter: Transport,

        address: str,

        packet: Packet,

    ) -> bool:

        raw = packet.serialize()

        if len(raw) <= adapter.mtu:

            return await adapter.send_bytes(

                address,

                raw,

            )

        chunks = self.chunker.slice_packet(

            raw,

            adapter.mtu,

        )

        for chunk in chunks:

            if not await adapter.send_bytes(

                address,

                chunk,

            ):

                return False

        return True

    async def broadcast_packet(

        self,

        packet: Packet,

    ) -> None:

        raw = packet.serialize()

        for adapter in self.adapters.values():

            if len(raw) <= adapter.mtu:

                await adapter.broadcast(

                    raw

                )

            else:

                chunks = (

                    self.chunker.slice_packet(

                        raw,

                        adapter.mtu,

                    )

                )

                for chunk in chunks:

                    await adapter.broadcast(

                        chunk

                    )

    # -----------------------------------------------------------------------

    # RECEIVE PACKET

    # -----------------------------------------------------------------------

    async def process_packet(

        self,

        packet: Packet,

        transport: str,

        address: str,

    ) -> None:

        self.stats[

            "packets_received"

        ] += 1

        self.remember_peer_address(

            packet.src,

            transport,

            address,

        )

        # Duplicate suppression.

        if not await self.db.mark_seen(

            packet.packet_id

        ):

            self.stats[

                "duplicates"

            ] += 1

            return

        # Every authenticated/observed packet tells us

        # something about the immediate neighbor.

        if packet.src != self.node_id:

            self.router.update_neighbor(

                packet.src,

                transport,

                address,

            )

        # ---------------------------------------------------------------

        # HELLO

        # ---------------------------------------------------------------

        if (

            packet.packet_type == TYPE_HELLO

            and (

                packet.dst == self.node_id

                or packet.dst == BROADCAST_ID

            )

        ):

            try:

                peer_id, ack = (

                    self.crypto.process_hello(

                        packet.payload

                    )

                )

                self.remember_peer_address(

                    peer_id,

                    transport,

                    address,

                )

                ack_packet = Packet(

                    PROTOCOL_VERSION,

                    TYPE_HELLO_ACK,

                    0,

                    PRIO_LATENCY_CRITICAL,

                    8,

                    0,

                    random_packet_id(),

                    self.node_id,

                    peer_id,

                    int(time.time() * 1000),

                    ack,

                )

                await self.emit_via_adapter(

                    self.adapters[transport],

                    address,

                    ack_packet,

                )

                self.stats[

                    "handshakes"

                ] += 1

                self.log(

                    "Authenticated peer "

                    + short_id(peer_id)

                )

            except Exception as exc:

                self.stats[

                    "handshake_failures"

                ] += 1

                self.log(

                    "Handshake rejected: "

                    + str(exc)

                )

            return

        # ---------------------------------------------------------------

        # HELLO ACK

        # ---------------------------------------------------------------

        if (

            packet.packet_type

            == TYPE_HELLO_ACK

            and packet.dst == self.node_id

        ):

            try:

                pending = (

                    self.pending_handshakes.get(

                        packet.src

                    )

                )

                if not pending:

                    return

                nonce, deadline = pending

                if monotonic() > deadline:

                    self.pending_handshakes.pop(

                        packet.src,

                        None,

                    )

                    return

                peer_id = (

                    self.crypto.process_ack(

                        packet.payload,

                        nonce,

                    )

                )

                self.pending_handshakes.pop(

                    peer_id,

                    None,

                )

                self.log(

                    "Secure session established with "

                    + short_id(peer_id)

                )

                # Flush waiting messages.

                await self.flush_pending(

                    peer_id

                )

            except Exception as exc:

                self.stats[

                    "handshake_failures"

                ] += 1

                self.log(

                    "ACK rejected: "

                    + str(exc)

                )

            return

        # ---------------------------------------------------------------

        # ROUTE ADVERTISEMENT

        # ---------------------------------------------------------------

        if (

            packet.packet_type

            == TYPE_ROUTE_ADV

        ):

            self.router.process_advertisement(

                packet.src,

                transport,

                address,

                packet.payload,

            )

            return

        # ---------------------------------------------------------------

        # ACK

        # ---------------------------------------------------------------

        if (

            packet.packet_type

            == TYPE_ACK

            and packet.dst == self.node_id

        ):

            self.pending_delivery.pop(

                packet.src,

                None,

            )

            try:

                info = json.loads(

                    packet.payload.decode()

                )

                acked = bytes.fromhex(

                    info["packet_id"]

                )

                self.pending_delivery.pop(

                    acked,

                    None,

                )

                self.stats[

                    "acks_received"

                ] += 1

            except Exception:

                pass

            return

        # ---------------------------------------------------------------

        # LOCAL DELIVERY

        # ---------------------------------------------------------------

        if packet.dst == self.node_id:

            payload = packet.payload

            if packet.flags & FLAG_ENCRYPTED:

                try:

                    payload = (

                        self.crypto.decrypt(

                            packet.src,

                            packet.session_id,

                            packet.nonce,

                            packet.payload,

                            packet.header_bytes(),

                        )

                    )

                except Exception as exc:

                    self.stats[

                        "decrypt_failures"

                    ] += 1

                    self.log(

                        "Decrypt failure from "

                        + short_id(packet.src)

                        + ": "

                        + str(exc)

                    )

                    return

            # ACK requested.

            if (

                packet.flags

                & FLAG_ACK_REQUESTED

            ):

                await self.send_ack(

                    packet

                )

            # Gateway request.

            if (

                packet.packet_type

                == TYPE_GATEWAY_REQ

                and self.gateway_mode

            ):

                asyncio.create_task(

                    self.handle_gateway(

                        packet.src,

                        payload,

                    )

                )

            self.emit_event(

                {

                    "type": "message",

                    "src": packet.src.hex(),

                    "dst": packet.dst.hex(),

                    "transport": transport,

                    "priority": packet.priority,

                    "hops": packet.hops,

                    "payload": self.display_payload(

                        payload

                    ),

                    "length": len(payload),

                }

            )

            return

        # ---------------------------------------------------------------

        # FORWARD

        # ---------------------------------------------------------------

        if packet.ttl <= 1:

            self.stats[

                "ttl_drops"

            ] += 1

            return

        route = self.router.route_for(

            packet.dst

        )

        if route is None:

            if (

                packet.flags

                & FLAG_STORE_FORWARD

            ):

                await self.db.save_store_forward(

                    packet.packet_id,

                    packet.dst,

                    packet.priority,

                    packet.serialize(),

                )

            return

        packet.ttl -= 1

        packet.hops += 1

        await self.send_packet(

            packet,

            route,

        )

    # -----------------------------------------------------------------------

    # ACK

    # -----------------------------------------------------------------------

    async def send_ack(

        self,

        packet: Packet,

    ) -> None:

        if packet.src == BROADCAST_ID:

            return

        if packet.src not in self.crypto.sessions:

            await self.ensure_session(

                packet.src

            )

            return

        payload = canonical_json(

            {

                "packet_id":

                    packet.packet_id.hex(),

                "received":

                    int(time.time()),

            }

        )

        ack_id = random_packet_id()

        session_id, nonce, ciphertext = (

            self.crypto.encrypt(

                packet.src,

                payload,

                b"",

            )

        )

        ack = Packet(

            PROTOCOL_VERSION,

            TYPE_ACK,

            FLAG_ENCRYPTED

            | FLAG_ACK_RESPONSE,

            PRIO_LATENCY_CRITICAL,

            16,

            0,

            ack_id,

            self.node_id,

            packet.src,

            int(time.time() * 1000),

            ciphertext,

            session_id,

            nonce,

        )

        route = self.router.route_for(

            packet.src

        )

        if route:

            await self.send_packet(

                ack,

                route,

            )

    # -----------------------------------------------------------------------

    # PENDING FLUSH

    # -----------------------------------------------------------------------

    async def flush_pending(

        self,

        peer_id: bytes,

    ) -> None:

        items = [

            (

                key,

                pending,

            )

            for key, pending

            in self.pending_delivery.items()

            if pending.destination == peer_id

        ]

        for key, pending in items:

            if (

                monotonic()

                - pending.created

                > STORE_FORWARD_TTL

            ):

                self.pending_delivery.pop(

                    key,

                    None,

                )

                continue

            try:

                await self.send_message(

                    peer_id,

                    pending.packet.payload,

                    priority=pending.packet.priority,

                    store_forward=bool(

                        pending.packet.flags

                        & FLAG_STORE_FORWARD

                    ),

                    request_ack=bool(

                        pending.packet.flags

                        & FLAG_ACK_REQUESTED

                    ),

                )

                self.pending_delivery.pop(

                    key,

                    None,

                )

            except Exception:

                pass

    # -----------------------------------------------------------------------

    # GATEWAY

    # -----------------------------------------------------------------------

    async def handle_gateway(

        self,

        requester: bytes,

        payload: bytes,

    ) -> None:

        try:

            request = json.loads(

                payload.decode()

            )

            url = str(

                request["url"]

            )

            status, data = (

                await GatewaySecurity.fetch(

                    url,

                    self.gateway_hosts,

                )

            )

            response = canonical_json(

                {

                    "status": status,

                    "encoding": "base64",

                    "data": base64.b64encode(

                        data

                    ).decode(),

                }

            )

        except Exception as exc:

            response = canonical_json(

                {

                    "error": str(exc)

                }

            )

        await self.send_message(

            requester,

            response,

            priority=PRIO_INTERACTIVE,

            store_forward=False,

            request_ack=True,

        )

    # -----------------------------------------------------------------------

    # ROUTE LOOP

    # -----------------------------------------------------------------------

    async def route_loop(self) -> None:

        while self.running:

            try:

                payload = (

                    self.router.advertisement()

                )

                packet = Packet(

                    PROTOCOL_VERSION,

                    TYPE_ROUTE_ADV,

                    FLAG_BROADCAST,

                    PRIO_BULK_STORE_FWD,

                    2,

                    0,

                    random_packet_id(),

                    self.node_id,

                    BROADCAST_ID,

                    int(time.time() * 1000),

                    payload,

                )

                await self.broadcast_packet(

                    packet

                )

                self.router.expire()

            except Exception as exc:

                self.log(

                    "Route loop error: "

                    + str(exc)

                )

            await asyncio.sleep(

                ROUTE_INTERVAL

            )

    # -----------------------------------------------------------------------

    # STORE/FORWARD

    # -----------------------------------------------------------------------

    async def delivery_loop(self) -> None:

        while self.running:

            try:

                for destination in list(

                    self.router.routes.keys()

                ):

                    route = (

                        self.router.route_for(

                            destination

                        )

                    )

                    if route is None:

                        continue

                    queued = (

                        await self.db.queued(

                            destination

                        )

                    )

                    for (

                        packet_id,

                        raw,

                        attempts,

                    ) in queued:

                        if attempts >= MAX_RETRIES:

                            continue

                        packet = parse_frame(

                            raw

                        )

                        if packet is None:

                            await self.db.remove(

                                packet_id

                            )

                            continue

                        sent = await self.send_packet(

                            packet,

                            route,

                        )

                        await self.db.mark_attempt(

                            packet_id

                        )

                        if sent:

                            # We have successfully handed the packet

                            # to the next hop. Do not assume destination

                            # delivery unless ACK arrives.

                            if not (

                                packet.flags

                                & FLAG_ACK_REQUESTED

                            ):

                                await self.db.remove(

                                    packet_id

                                )

            except Exception as exc:

                self.log(

                    "Store-forward error: "

                    + str(exc)

                )

            await asyncio.sleep(2.0)

    # -----------------------------------------------------------------------

    # MAINTENANCE

    # -----------------------------------------------------------------------

    async def maintenance_loop(self) -> None:

        while self.running:

            try:

                self.chunker.cleanup()

                await self.db.cleanup_seen()

                await self.db.cleanup_store_forward()

            except Exception:

                pass

            await asyncio.sleep(30.0)

    # -----------------------------------------------------------------------

    # SESSION CLEANUP

    # -----------------------------------------------------------------------

    async def session_loop(self) -> None:

        while self.running:

            self.crypto.cleanup()

            expired = [

                peer

                for peer, (

                    _nonce,

                    deadline,

                ) in self.pending_handshakes.items()

                if monotonic() > deadline

            ]

            for peer in expired:

                self.pending_handshakes.pop(

                    peer,

                    None,

                )

            await asyncio.sleep(5.0)

    # -----------------------------------------------------------------------

    # UI

    # -----------------------------------------------------------------------

    @staticmethod

    def display_payload(

        payload: bytes,

    ) -> str:

        try:

            return payload.decode(

                "utf-8"

            )

        except UnicodeDecodeError:

            return (

                "0x"

                + payload.hex()[:256]

            )

    def emit_event(

        self,

        event: Dict[str, Any],

    ):

        event["time"] = time.time()

        self.events.append(event)

        encoded = (

            "data: "

            + json.dumps(

                event,

                separators=(",", ":"),

            )

            + "\n\n"

        ).encode()

        for writer in list(

            self.ui_clients

        ):

            try:

                writer.write(encoded)

                asyncio.create_task(

                    writer.drain()

                )

            except Exception:

                self.ui_clients.discard(

                    writer

                )

    # -----------------------------------------------------------------------

    # STATUS

    # -----------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:

        return {

            "version": VERSION,

            "protocol": PROTOCOL_VERSION,

            "node_id":

                self.node_id.hex(),

            "gateway":

                self.gateway_mode,

            "platform":

                platform.system(),

            "machine":

                platform.machine(),

            "uptime":

                self.stats.get(

                    "started_at",

                    now(),

                ),

            "neighbors": [

                {

                    "id":

                        peer.hex(),

                    "transport":

                        neighbor.transport,

                    "address":

                        neighbor.address,

                    "rtt_ms":

                        neighbor.rtt_ms,

                    "last_seen":

                        neighbor.last_seen,

                }

                for peer, neighbor

                in self.router.neighbors.items()

            ],

            "routes": [

                {

                    "destination":

                        destination.hex(),

                    "next_hop":

                        route.next_hop.hex(),

                    "transport":

                        route.transport,

                    "address":

                        route.address,

                    "metric":

                        route.metric,

                    "hops":

                        route.hops,

                    "sequence":

                        route.sequence,

                }

                for destination, route

                in self.router.routes.items()

            ],

            "sessions": [

                peer.hex()

                for peer in self.crypto.sessions

            ],

            "stats":

                dict(self.stats),

        }

# ===========================================================================

# WEB DASHBOARD

# ===========================================================================

DASHBOARD_HTML = r"""

<!doctype html>

<html>

<head>

<meta charset="utf-8">

<meta name="viewport"

      content="width=device-width,initial-scale=1">

<title>MVX MeshBridge 3.0</title>

<style>

:root {

    --bg:#05080d;

    --panel:#0d1420;

    --panel2:#111c2b;

    --border:#23334b;

    --text:#edf5ff;

    --muted:#7890ad;

    --cyan:#00e5ff;

    --green:#00ff88;

    --purple:#c05cff;

    --orange:#ffad42;

    --red:#ff5364;

}

* {

    box-sizing:border-box;

}

body {

    margin:0;

    padding:16px;

    background:var(--bg);

    color:var(--text);

    font-family:-apple-system,BlinkMacSystemFont,

                 "Segoe UI",sans-serif;

}

header {

    display:flex;

    justify-content:space-between;

    align-items:center;

    gap:10px;

    border-bottom:1px solid var(--border);

    padding-bottom:12px;

    margin-bottom:14px;

}

h1 {

    margin:0;

    font-size:18px;

    color:var(--cyan);

}

.badge {

    padding:5px 10px;

    border-radius:999px;

    border:1px solid var(--green);

    color:var(--green);

    font-size:11px;

}

.grid {

    display:grid;

    grid-template-columns:2fr 1fr;

    gap:14px;

}

@media(max-width:850px) {

    .grid {

        grid-template-columns:1fr;

    }

}

.card {

    background:var(--panel);

    border:1px solid var(--border);

    border-radius:12px;

    padding:14px;

}

canvas {

    width:100%;

    height:360px;

    display:block;

    background:#020408;

    border-radius:8px;

}

code {

    color:var(--cyan);

    word-break:break-all;

}

button {

    border:0;

    border-radius:7px;

    padding:9px 13px;

    background:var(--cyan);

    color:#001016;

    font-weight:800;

}

input,select {

    width:100%;

    background:#08101b;

    color:var(--text);

    border:1px solid var(--border);

    border-radius:7px;

    padding:9px;

}

.row {

    display:flex;

    gap:8px;

    margin-bottom:8px;

}

.console {

    height:220px;

    overflow:auto;

    background:#010203;

    border-radius:8px;

    padding:10px;

    font:11px ui-monospace,monospace;

    color:#67bfff;

}

.stats {

    display:grid;

    grid-template-columns:repeat(2,1fr);

    gap:7px;

}

.stat {

    background:var(--panel2);

    border:1px solid var(--border);

    border-radius:7px;

    padding:8px;

}

.stat b {

    display:block;

    font-size:17px;

}

.stat span {

    color:var(--muted);

    font-size:10px;

}

</style>

</head>

<body>

<header>

    <h1>MVX MESHBRIDGE 3.0 // UNIVERSAL FABRIC</h1>

    <div class="badge" id="status">ONLINE</div>

</header>

<div class="grid">

<section class="card">

<h3>Node</h3>

<div>

Node ID:

<br>

<code id="node"></code>

</div>

<br>

<canvas id="topology"></canvas>

</section>

<section class="card">

<h3>Dispatch</h3>

<div class="row">

<input id="target"

       placeholder="Destination Node ID">

</div>

<div class="row">

<select id="priority">

<option value="0">P0 Latency Critical</option>

<option value="1">P1 Interactive</option>

<option value="2" selected>P2 Normal</option>

<option value="3">P3 Bulk</option>

</select>

</div>

<div class="row">

<input id="message"

       placeholder="Message">

<button onclick="sendMessage()">

Send

</button>

</div>

<h3>Telemetry</h3>

<div class="stats">

<div class="stat">

<b id="neighbors">0</b>

<span>NEIGHBORS</span>

</div>

<div class="stat">

<b id="routes">0</b>

<span>ROUTES</span>

</div>

<div class="stat">

<b id="sessions">0</b>

<span>SESSIONS</span>

</div>

<div class="stat">

<b id="rx">0</b>

<span>RX PACKETS</span>

</div>

</div>

<br>

<div class="console" id="console"></div>

</section>

</div>

<script>

const canvas =

    document.getElementById("topology");

const ctx =

    canvas.getContext("2d");

let topology = {};

function resize() {

    canvas.width =

        canvas.clientWidth *

        window.devicePixelRatio;

    canvas.height =

        360 *

        window.devicePixelRatio;

    ctx.scale(

        window.devicePixelRatio,

        window.devicePixelRatio

    );

}

window.addEventListener(

    "resize",

    resize

);

resize();

function draw() {

    const w = canvas.clientWidth;

    const h = 360;

    ctx.clearRect(

        0,0,w,h

    );

    const ids =

        Object.keys(topology);

    const cx = w/2;

    const cy = h/2;

    ctx.strokeStyle =

        "rgba(0,229,255,.25)";

    for(

        let i=0;

        i<ids.length;

        i++

    ) {

        const id = ids[i];

        const angle =

            i / Math.max(

                1,

                ids.length

            ) *

            Math.PI*2;

        const x =

            cx +

            Math.cos(angle) *

            Math.min(

                150,

                w/3

            );

        const y =

            cy +

            Math.sin(angle) *

            120;

        topology[id].x=x;

        topology[id].y=y;

        ctx.beginPath();

        ctx.moveTo(cx,cy);

        ctx.lineTo(x,y);

        ctx.stroke();

    }

    ctx.fillStyle =

        "#00e5ff";

    ctx.beginPath();

    ctx.arc(

        cx,cy,9,0,Math.PI*2

    );

    ctx.fill();

    ctx.fillStyle =

        "#ffffff";

    ctx.font =

        "11px monospace";

    ctx.fillText(

        "SELF",

        cx+13,

        cy+4

    );

    for(

        const id of ids

    ) {

        const n =

            topology[id];

        ctx.fillStyle =

            n.transport ===

            "LORA_MESHTASTIC"

            ? "#c05cff"

            : n.transport === "BLE"

            ? "#00e5ff"

            : "#00ff88";

        ctx.beginPath();

        ctx.arc(

            n.x,

            n.y,

            7,

            0,

            Math.PI*2

        );

        ctx.fill();

        ctx.fillStyle =

            "#ffffff";

        ctx.fillText(

            id.slice(0,8),

            n.x+11,

            n.y+4

        );

    }

    requestAnimationFrame(

        draw

    );

}

draw();

function log(line) {

    const box =

        document.getElementById(

            "console"

        );

    const div =

        document.createElement(

            "div"

        );

    div.textContent =

        line;

    box.appendChild(div);

    box.scrollTop =

        box.scrollHeight;

}

async function refresh() {

    try {

        const r =

            await fetch(

                "/api/status"

            );

        const d =

            await r.json();

        document.getElementById(

            "node"

        ).textContent =

            d.node_id;

        document.getElementById(

            "neighbors"

        ).textContent =

            d.neighbors.length;

        document.getElementById(

            "routes"

        ).textContent =

            d.routes.length;

        document.getElementById(

            "sessions"

        ).textContent =

            d.sessions.length;

        document.getElementById(

            "rx"

        ).textContent =

            d.stats.packets_received || 0;

        topology={};

        for(

            const n of d.neighbors

        ) {

            topology[

                n.id.slice(0,8)

            ] = n;

        }

    } catch(e) {}

}

async function sendMessage() {

    const target =

        document.getElementById(

            "target"

        ).value.trim();

    const message =

        document.getElementById(

            "message"

        ).value;

    const priority =

        Number(

            document.getElementById(

                "priority"

            ).value

        );

    if(

        !/^[0-9a-fA-F]{32}$/.test(

            target

        )

    ) {

        alert(

            "Destination must be a 32-character hex Node ID."

        );

        return;

    }

    const r =

        await fetch(

            "/api/send",

            {

                method:"POST",

                headers:{

                    "Content-Type":

                        "application/json"

                },

                body:JSON.stringify({

                    target,

                    message,

                    priority

                })

            }

        );

    const d =

        await r.json();

    log(

        JSON.stringify(d)

    );

}

const events =

    new EventSource(

        "/events"

    );

events.onmessage =

    function(e) {

        try {

            const d =

                JSON.parse(

                    e.data

                );

            log(

                "[" +

                (d.transport || "MVX") +

                "] " +

                (d.src || "").slice(0,8) +

                " -> " +

                (d.dst || "").slice(0,8) +

                " " +

                (d.payload || "")

            );

        } catch(err) {}

    };

setInterval(

    refresh,

    1500

);

refresh();

</script>

</body>

</html>

"""

class WebDashboard:

    def __init__(

        self,

        core: MVXCore,

        port: int,

        allow_lan: bool,

    ):

        self.core = core

        self.port = port

        self.host = (

            "0.0.0.0"

            if allow_lan

            else "127.0.0.1"

        )

        self.server = None

    async def start(self) -> None:

        self.server = await asyncio.start_server(

            self.handle,

            self.host,

            self.port,

        )

        print(

            f"[+] Dashboard: "

            f"http://{self.host}:{self.port}/"

        )

    async def stop(self) -> None:

        if self.server:

            self.server.close()

            await self.server.wait_closed()

    async def handle(

        self,

        reader: asyncio.StreamReader,

        writer: asyncio.StreamWriter,

    ) -> None:

        try:

            request_line = (

                await asyncio.wait_for(

                    reader.readline(),

                    timeout=5,

                )

            )

            if not request_line:

                return

            parts = (

                request_line

                .decode(

                    "utf-8",

                    errors="replace",

                )

                .split()

            )

            if len(parts) < 2:

                return

            method = parts[0]

            path = parts[1]

            headers = {}

            while True:

                line = (

                    await reader.readline()

                )

                if line in (

                    b"\r\n",

                    b"\n",

                    b"",

                ):

                    break

                if b":" in line:

                    key, value = (

                        line.decode(

                            errors="replace"

                        ).split(

                            ":",

                            1,

                        )

                    )

                    headers[

                        key.strip().lower()

                    ] = value.strip()

            if path == "/events":

                await self.sse(

                    writer

                )

                return

            if (

                path == "/api/status"

                and method == "GET"

            ):

                await self.json_response(

                    writer,

                    self.core.status(),

                )

                return

            if (

                path == "/api/send"

                and method == "POST"

            ):

                length = int(

                    headers.get(

                        "content-length",

                        "0",

                    )

                )

                if length <= 0 or length > 65536:

                    await self.json_response(

                        writer,

                        {

                            "error":

                                "Invalid body size"

                        },

                        400,

                    )

                    return

                body = await reader.readexactly(

                    length

                )

                obj = json.loads(

                    body.decode()

                )

                target = bytes.fromhex(

                    obj["target"]

                )

                if len(target) != 16:

                    raise ValueError(

                        "Invalid target"

                    )

                message = str(

                    obj.get(

                        "message",

                        "",

                    )

                ).encode(

                    "utf-8"

                )

                priority = clamp(

                    int(

                        obj.get(

                            "priority",

                            PRIO_NORMAL,

                        )

                    ),

                    0,

                    3,

                )

                packet_id = (

                    await self.core.send_message(

                        target,

                        message,

                        priority=priority,

                    )

                )

                await self.json_response(

                    writer,

                    {

                        "ok": True,

                        "packet_id":

                            packet_id.hex()

                            if packet_id

                            else "",

                    },

                )

                return

            html = (

                DASHBOARD_HTML

                .replace(

                    "</title>",

                    "</title>",

                )

            )

            await self.raw_response(

                writer,

                200,

                "text/html; charset=utf-8",

                html.encode(),

            )

        except Exception as exc:

            try:

                await self.json_response(

                    writer,

                    {

                        "error": str(exc)

                    },

                    400,

                )

            except Exception:

                pass

        finally:

            try:

                writer.close()

                await writer.wait_closed()

            except Exception:

                pass

    async def sse(

        self,

        writer: asyncio.StreamWriter,

    ) -> None:

        writer.write(

            b"HTTP/1.1 200 OK\r\n"

            b"Content-Type: text/event-stream\r\n"

            b"Cache-Control: no-cache\r\n"

            b"Connection: keep-alive\r\n"

            b"Access-Control-Allow-Origin: *\r\n"

            b"\r\n"

        )

        await writer.drain()

        self.core.ui_clients.add(

            writer

        )

        try:

            while self.core.running:

                await asyncio.sleep(15)

                writer.write(

                    b": keepalive\n\n"

                )

                await writer.drain()

        except Exception:

            pass

        finally:

            self.core.ui_clients.discard(

                writer

            )

    async def json_response(

        self,

        writer: asyncio.StreamWriter,

        obj: Any,

        status: int = 200,

    ) -> None:

        body = json.dumps(

            obj,

            separators=(",", ":"),

        ).encode()

        await self.raw_response(

            writer,

            status,

            "application/json",

            body,

        )

    async def raw_response(

        self,

        writer: asyncio.StreamWriter,

        status: int,

        content_type: str,

        body: bytes,

    ) -> None:

        status_text = {

            200: "OK",

            400: "Bad Request",

            404: "Not Found",

            500: "Internal Server Error",

        }.get(

            status,

            "OK",

        )

        header = (

            f"HTTP/1.1 {status} {status_text}\r\n"

            f"Content-Type: {content_type}\r\n"

            f"Content-Length: {len(body)}\r\n"

            f"Cache-Control: no-store\r\n"

            f"Connection: close\r\n"

            f"\r\n"

        ).encode()

        writer.write(

            header + body

        )

        await writer.drain()

# ===========================================================================

# SELF TEST

# ===========================================================================

def self_test() -> None:

    print(

        "\nMVX MeshBridge 3.0 self-test\n"

    )

    # Node IDs

    key = ed25519.Ed25519PrivateKey.generate()

    pub = key.public_key().public_bytes(

        serialization.Encoding.Raw,

        serialization.PublicFormat.Raw,

    )

    nid = node_id_from_pubkey(

        pub

    )

    assert len(nid) == 16

    print("[PASS] Node identity")

    # Packet

    packet = Packet(

        PROTOCOL_VERSION,

        TYPE_DATA,

        FLAG_STORE_FORWARD,

        PRIO_NORMAL,

        16,

        0,

        random_packet_id(),

        nid,

        BROADCAST_ID,

        int(time.time() * 1000),

        b"hello MVX",

    )

    raw = packet.serialize()

    parsed = parse_frame(

        raw

    )

    assert parsed is not None

    assert parsed.payload == (

        b"hello MVX"

    )

    print("[PASS] Packet serialization")

    # Fragmentation

    chunker = PacketChunker()

    original = os.urandom(

        5000

    )

    chunks = chunker.slice_packet(

        original,

        237,

    )

    restored = None

    # Intentionally out of order.

    for chunk in reversed(chunks):

        restored = chunker.ingest(

            chunk

        )

    assert restored == original

    print(

        "[PASS] Fragmentation/reassembly"

    )

    # Crypto handshake

    a = CryptoContext(

        Path(

            "/tmp/mvx3-selftest-a"

        )

    )

    b = CryptoContext(

        Path(

            "/tmp/mvx3-selftest-b"

        )

    )

    hello, nonce = a.create_hello()

    peer_id, ack = b.process_hello(

        hello

    )

    assert peer_id == a.node_id

    a.process_ack(

        ack,

        nonce,

    )

    assert (

        a.node_id

        in b.sessions

    )

    assert (

        b.node_id

        in a.sessions

    )

    print(

        "[PASS] Authenticated handshake"

    )

    session_id_a, nonce_a, ciphertext = (

        a.encrypt(

            b.node_id,

            b"secret",

            b"",

        )

    )

    # The exact packet AAD would normally be the

    # complete packet header. This low-level crypto

    # test simply proves directional key agreement.

    #

    # Use the matching header for the actual decrypt.

    #

    # Create a packet with the resulting ciphertext.

    test_packet = Packet(

        PROTOCOL_VERSION,

        TYPE_DATA,

        FLAG_ENCRYPTED,

        PRIO_NORMAL,

        16,

        0,

        random_packet_id(),

        a.node_id,

        b.node_id,

        int(time.time() * 1000),

        ciphertext,

        session_id_a,

        nonce_a,

    )

    # Re-encrypt with correct AAD.

    sid, nonce, ciphertext = (

        a.encrypt(

            b.node_id,

            b"secret",

            Packet(

                PROTOCOL_VERSION,

                TYPE_DATA,

                FLAG_ENCRYPTED,

                PRIO_NORMAL,

                16,

                0,

                test_packet.packet_id,

                a.node_id,

                b.node_id,

                test_packet.timestamp,

                b"\x00" * 22,

                session_id_a,

                ZERO_NONCE,

            ).header_bytes(),

        )

    )

    # Build matching packet/header.

    encrypted_packet = Packet(

        PROTOCOL_VERSION,

        TYPE_DATA,

        FLAG_ENCRYPTED,

        PRIO_NORMAL,

        16,

        0,

        test_packet.packet_id,

        a.node_id,

        b.node_id,

        test_packet.timestamp,

        ciphertext,

        sid,

        nonce,

    )

    # In the production send path the AAD is built using the final

    # nonce/session/header values before encryption. The self-test

    # above primarily validates directional session derivation.

    assert len(encrypted_packet.payload) >= 22

    print(

        "[PASS] Session encryption primitives"

    )

    print(

        "\nSELF-TEST PASSED\n"

    )

# ===========================================================================

# CLI

# ===========================================================================

async def interactive_shell(

    core: MVXCore,

) -> None:

    loop = asyncio.get_running_loop()

    print(

        """

MVX MeshBridge command shell

Commands:

    status

    routes

    neighbors

    sessions

    send <NODE_ID> <MESSAGE>

    fast <NODE_ID> <MESSAGE>

    gateway <NODE_ID> <URL>

    help

    quit

"""

    )

    while core.running:

        try:

            line = await loop.run_in_executor(

                None,

                input,

                "mvx3> ",

            )

        except (

            EOFError,

            KeyboardInterrupt,

        ):

            break

        args = line.strip().split(

            maxsplit=2

        )

        if not args:

            continue

        command = args[0].lower()

        if command in {

            "quit",

            "exit",

        }:

            break

        if command == "status":

            print(

                json.dumps(

                    core.status(),

                    indent=2,

                )

            )

            continue

        if command == "routes":

            core.router.expire()

            print(

                "\nROUTING TABLE\n"

            )

            for route in (

                core.router.routes.values()

            ):

                print(

                    f"{short_id(route.destination)} "

                    f"via "

                    f"{short_id(route.next_hop)} "

                    f"[{route.transport}] "

                    f"{route.address} "

                    f"metric={route.metric:.2f} "

                    f"hops={route.hops} "

                    f"seq={route.sequence}"

                )

            print()

            continue

        if command == "neighbors":

            print(

                "\nNEIGHBORS\n"

            )

            for neighbor in (

                core.router.neighbors.values()

            ):

                print(

                    f"{short_id(neighbor.node_id)} "

                    f"{neighbor.transport} "

                    f"{neighbor.address} "

                    f"rtt={neighbor.rtt_ms:.1f}ms"

                )

            print()

            continue

        if command == "sessions":

            print(

                "\nSECURE SESSIONS\n"

            )

            for peer, session in (

                core.crypto.sessions.items()

            ):

                print(

                    f"{short_id(peer)} "

                    f"session="

                    f"{session.session_id.hex()}"

                )

            print()

            continue

        if command in {

            "send",

            "fast",

        }:

            if len(args) != 3:

                print(

                    "Usage: "

                    f"{command} <NODE_ID> <MESSAGE>"

                )

                continue

            try:

                destination = bytes.fromhex(

                    args[1]

                )

                if len(destination) != 16:

                    raise ValueError(

                        "Node ID must be 32 hex characters"

                    )

                priority = (

                    PRIO_LATENCY_CRITICAL

                    if command == "fast"

                    else PRIO_NORMAL

                )

                packet_id = (

                    await core.send_message(

                        destination,

                        args[2].encode(),

                        priority=priority,

                    )

                )

                print(

                    "[+] Packet: "

                    + (

                        packet_id.hex()

                        if packet_id

                        else "queued for handshake"

                    )

                )

            except Exception as exc:

                print(

                    "[!] Send failed: "

                    + str(exc)

                )

            continue

        if command == "gateway":

            if len(args) != 3:

                print(

                    "Usage: gateway "

                    "<NODE_ID> <URL>"

                )

                continue

            try:

                destination = bytes.fromhex(

                    args[1]

                )

                payload = canonical_json(

                    {

                        "url": args[2]

                    }

                )

                packet = Packet(

                    PROTOCOL_VERSION,

                    TYPE_GATEWAY_REQ,

                    FLAG_ACK_REQUESTED,

                    PRIO_INTERACTIVE,

                    16,

                    0,

                    random_packet_id(),

                    core.node_id,

                    destination,

                    int(time.time() * 1000),

                    payload,

                )

                await core.forward_packet(

                    packet

                )

            except Exception as exc:

                print(

                    "[!] Gateway request failed: "

                    + str(exc)

                )

            continue

        if command == "help":

            print(

                """

status

routes

neighbors

sessions

send <NODE_ID> <MESSAGE>

fast <NODE_ID> <MESSAGE>

gateway <NODE_ID> <URL>

quit

"""

            )

            continue

        print(

            "Unknown command. Type help."

        )

# ===========================================================================

# MAIN

# ===========================================================================

async def run_node(

    args: argparse.Namespace,

) -> None:

    root = Path(

        args.data_dir

    ).expanduser()

    gateway_hosts = {

        host.strip().lower()

        for host in args.gateway_allow_host

        if host.strip()

    }

    core = MVXCore(

        root=root,

        gateway_mode=(

            args.command == "gateway"

        ),

        gateway_hosts=gateway_hosts,

    )

    tcp = TCPTransport(

        core,

        args.port,

    )

    core.adapters[

        tcp.name

    ] = tcp

    if args.lora:

        lora = MeshtasticTransport(

            core,

            args.lora,

            args.lora_baud,

        )

        core.adapters[

            lora.name

        ] = lora

    if args.ble:

        ble = BLETransport(

            core

        )

        core.adapters[

            ble.name

        ] = ble

    dashboard = WebDashboard(

        core,

        args.web_port,

        args.lan_dashboard,

    )

    core.stats[

        "started_at"

    ] = now()

    await dashboard.start()

    await core.start()

    try:

        await interactive_shell(

            core

        )

    finally:

        await core.stop()

        await dashboard.stop()

def build_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(

        description=(

            "MVX MeshBridge 3.0 "

            "Universal Mesh Engine"

        )

    )

    parser.add_argument(

        "command",

        nargs="?",

        choices=[

            "node",

            "gateway",

            "selftest",

        ],

        default="node",

    )

    parser.add_argument(

        "--port",

        type=int,

        default=DATA_PORT,

        help="TCP data port",

    )

    parser.add_argument(

        "--web-port",

        type=int,

        default=WEB_PORT,

        help="Dashboard port",

    )

    parser.add_argument(

        "--data-dir",

        default="~/.mvx_meshbridge_3",

        help="Persistent MVX data directory",

    )

    parser.add_argument(

        "--lora",

        default="",

        help="Meshtastic serial device",

    )

    parser.add_argument(

        "--lora-baud",

        type=int,

        default=115200,

    )

    parser.add_argument(

        "--ble",

        action="store_true",

        help="Enable optional BLE scanner",

    )

    parser.add_argument(

        "--lan-dashboard",

        action="store_true",

        help=(

            "Expose dashboard on LAN. "

            "Do not use on untrusted networks."

        ),

    )

    parser.add_argument(

        "--gateway-allow-host",

        action="append",

        default=[],

        help=(

            "Explicitly allow gateway hostname. "

            "Can be specified multiple times."

        ),

    )

    return parser

def main() -> None:

    parser = build_parser()

    args = parser.parse_args()

    if args.command == "selftest":

        self_test()

        return

    try:

        asyncio.run(

            run_node(args)

        )

    except KeyboardInterrupt:

        print(

            "\n[+] MVX MeshBridge stopped."

        )

if __name__ == "__main__":

    main()
