# REEL / AURA

REEL (AURA container format) is an experimental frame-based video container and codec pipeline written in Rust.  
It is designed around predictable frame access, simple container structure, and efficient sequential decoding while remaining relatively lightweight and easy to inspect.

The project currently focuses on:

- YUV420p frame storage
- Independent frame compression
- Fast sequential decoding
- Random-access frame retrieval through indexed offsets
- Simple binary container design
- Optional audio chunk storage
- Minimal runtime overhead
- Fully native Rust implementation

---

# Design Goals

## Predictable Frame Access

REEL stores byte offsets for every frame inside an Offset Index Table (OIT), allowing direct frame seeking without scanning the entire file.

This enables:

- Constant-time frame lookup
- Deterministic seeking
- Simplified decoding logic
- Stable behavior for editing workflows

Unlike delivery codecs optimized for streaming efficiency, REEL prioritizes predictability and tooling simplicity.

---

## Simple Binary Layout

The container format is intentionally compact and explicit.

File structure:

```text
[ File Header ]
[ Frame 0 ]
[ Frame 1 ]
[ Frame 2 ]
...
[ Audio Data ]
[ Offset Index Table ]
[ OIT Footer Pointer ]
```

The final 8 bytes of the file contain the OIT offset, allowing readers to locate the frame index immediately without scanning the file.

---

# Architecture

## Core Modules

### `header.rs`

Defines the global file header structure and format metadata.

Contains:

- Magic bytes
- Format version
- Resolution
- Frame count
- FPS information
- Audio offsets
- OIT offset

The file header is fixed-size for deterministic parsing.

---

### `frame.rs`

Defines all frame-related structures and processing logic.

Includes:

- `FrameHeader`
- `TimeStamp`
- `YuvFrame`
- `CompressedFrame`
- `DecodedFrame`
- Audio frame abstraction
- Paeth predictor utilities

Frames are stored as independent compressed Y, U, and V planes.

Compression currently uses Zstandard.

---

### `reader.rs`

Implements decoding and container traversal.

Responsibilities include:

- Header validation
- OIT loading
- Random-access frame reads
- Sequential decode
- Audio extraction
- Corruption checks

Frame access is performed through the OIT rather than sequential scanning.

---

### `writer.rs`

Responsible for container generation.

Responsibilities include:

- Header serialization
- Frame compression
- Offset tracking
- Audio writing
- OIT generation
- Final container patching

The writer initially emits a placeholder header and patches finalized metadata once encoding completes.

---

### `oit.rs`

Defines the Offset Index Table.

Each OIT entry stores the absolute byte offset of a frame inside the container.

This allows:

- O(1) frame lookup
- Fast seeking
- Direct decode access

---

### `error.rs`

Defines unified error handling through `AuraError`.

The project uses strongly typed errors instead of string-based propagation wherever possible.

---

# Frame Pipeline

Encoding pipeline:

```text
Raw YUV420p Frame
        ↓
Plane Separation
        ↓
Per-Plane Compression
        ↓
Frame Header Generation
        ↓
Container Write
        ↓
OIT Update
```

Decoding pipeline:

```text
Frame Request
        ↓
OIT Lookup
        ↓
Seek To Byte Offset
        ↓
Read Compressed Planes
        ↓
ZSTD Decompression
        ↓
Decoded YUV420p Output
```

---

# Compression Strategy

Current compression model:

- Independent frame compression
- Independent plane compression
- Zstandard backend
- Optional Paeth preprocessing utilities

Advantages:

- No inter-frame dependency chains
- Simple random access
- Stable decoding cost
- Easier corruption isolation

Tradeoffs:

- Larger files than delivery codecs such as H.264/H.265
- Less temporal compression efficiency
- Higher storage requirements for long-form content

The format is currently oriented more toward tooling and processing workflows than internet delivery.

---

# Audio Support

The container supports optional audio storage.

Audio is stored separately from video frames and chunked into fixed-size audio frames.

Current implementation:

- `f32` samples
- Timestamped audio frames
- Configurable sample rate
- Channel metadata support

---

# Command Line Interface

## Encode

```bash
aurx encode input.yuv output.aura \
  --width 1920 \
  --height 1080 \
  --fps-num 30 \
  --fps-den 1
```

## Decode

```bash
aurx decode input.aura output.yuv
```

## Decode Single Frame

```bash
aurx decode input.aura frame.yuv --frame 120
```

---

# Validation and Safety

The encoder and decoder include multiple validation checks:

- Magic byte verification
- Version validation
- Frame count validation
- Corruption checks
- Frame index verification
- Input size validation
- Output integrity checks

---

# Current Limitations

- YUV420p only
- No inter-frame compression
- No hardware acceleration
- No streaming support
- No entropy coding customization
- No color metadata support
- No subtitles or attachment streams

---

# Project Philosophy

REEL is not intended to compete directly with highly optimized delivery codecs.

The project explores an alternative direction:

- Predictable media processing
- Simpler decode behavior
- Tooling-oriented architecture
- Easier frame-level manipulation
- Transparent container structure

The emphasis is on controllable behavior and systems-oriented design rather than maximum compression efficiency.

---

# Building

## Requirements

- Rust stable
- FFmpeg (for YUV generation/testing)

## Build

```bash
cargo build --release
```

Binary output:

```text
target/release/aurx
```

---

# Future Work

Planned areas of exploration include:

- Parallel decoding improvements
- Additional preprocessing filters
- Better compression strategies
- SIMD acceleration
- Alternative entropy models
- Editing-oriented optimizations
- Streaming experiments
- GPU-assisted processing

---

# License

MIT License
