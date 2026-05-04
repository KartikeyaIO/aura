# The Reel Format

Reel is an intermediate video container format designed for **Editron**. It focuses on simplicity, fast random access, and predictable decoding rather than aggressive compression.

---

# Core Features

- YUV420 planar video storage
- Independent per-frame compression using **Zstandard (zstd)**
- **O(1) random frame access** via Offset Index Table (OIT)
- Separate audio stream (non-interleaved)
- Simple binary layout for fast parsing

---

# Architecture

## File Header (72 bytes)

Defined in `header.rs`

The file begins with a fixed-size header:

- Magic bytes: `REEL`
- Version (`u16`)
- Total number of frames (`u64`)
- Resolution: `width`, `height`
- FPS: `fps_num / fps_den`
- Audio:
  - `audio_offset`
  - `audio_size`
- OIT offset (`oit_offset`)

### Notes

- Header is written initially and **patched during finalization**
- Validation checks:
  - Magic must match
  - Version must match

---

## Frame Layout

Defined in `frame.rs`

Each frame is stored independently.

### Frame Header (40 bytes)

Contains:

- `ylen`, `ulen`, `vlen` → compressed plane sizes
- `index` → frame index (used for integrity validation)
- `timestamp` → presentation timestamp (`TimeStamp`)
- padding


---

### Frame Data

Immediately follows the header:

- Y plane (compressed)
- U plane (compressed)
- V plane (compressed)

### Format

- Y: full resolution (`width × height`)
- U: quarter resolution (`width/2 × height/2`)
- V: quarter resolution (`width/2 × height/2`)

---

## Compression Pipeline

Implemented in `frame.rs`

- Each plane is compressed independently using **zstd**
- Compression is parallelized using `rayon`

### Optional Preprocessing

- Includes **Paeth predictor** (lossless transform)
- Functions:
  - `paeth_predictor`
  - `paeth_rev`

Currently not automatically applied in pipeline.

---

## Offset Index Table (OIT)

Defined in `oit.rs`

- Located near end of file
- Enables direct frame access

### Structure

- Array of `u64` offsets
- Size = `total_frames × 8 bytes`

### Access Flow

1. Read OIT offset from file footer
2. Load OIT into memory
3. Seek directly to frame using offset

---

## Footer

- The last 8 bytes store `oit_offset`
- Used to locate OIT without scanning the file

---

## Audio Format

Defined across `frame.rs` and `reader.rs`

Audio is stored separately as a contiguous block.

### Structure per Audio Frame

Each chunk contains:

- Timestamp:
  - `pts` (`i64`)
  - `num`, `den`
- Metadata:
  - `sample_rate`
  - `channels`
  - `sample_count`
- Samples:
  - `f32` PCM data

### Chunking

- Audio is split into chunks of **1024 samples**
- Converted into multiple `AudioFrame`s

---

## Reader

Implemented in `reader.rs`

### Responsibilities

- Validate file header
- Load OIT into memory

### Methods

#### `read_frame(index)`

- Uses OIT for direct seek
- Reads compressed data
- Decompresses into `DecodedFrame`

#### `read_audio()`

- Reads entire audio block
- Returns `Vec<AudioFrame>`

---

## Writer

Implemented in `writer.rs`

### Workflow

1. Write placeholder header
2. Write frames sequentially
3. Track offsets for OIT
4. Optionally write audio
5. Write OIT
6. Write footer (`oit_offset`)
7. Patch header with final metadata

---

## Error Handling

Defined in `error.rs`

Custom error type includes:

- IO errors
- Compression / decompression failures
- Invalid magic / version
- Corrupt OIT
- Frame out-of-bounds
- Invalid frame header

---

## Design Goals

- Deterministic decoding
- Fast random access (O(1))
- Minimal container complexity
- Easy debugging and tooling
- Suitable for intermediate processing (not final delivery)

---

## Limitations

- No inter-frame compression (larger file sizes)
- No color metadata (assumes YUV420)
- No streaming support
- No advanced indexing beyond OIT
- Audio is not compressed

---

## Summary

Reel trades compression efficiency for:

- speed
- simplicity
- controllability

### Best suited for:

- editing pipelines
- intermediate storage
- deterministic processing systems

### Not suited for:

- distribution
- bandwidth-constrained environments