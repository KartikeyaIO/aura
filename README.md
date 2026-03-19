# The Reel Format

- It is an intermediate Format for [Editron](https://github.com/KartikeyaIO/Editron)
- This format stores data in YUV420 pixel format and uses Zstandard Compression algorithm to compress the channels.
- It has O(1) frame access.
- Audio is stored separately from the frames and as a single unit, so we can replace and process audio easily.

---

# The Architecture

## File Header

- The file header is of 72 bytes  
- It contains:
  - Magic bytes: `REEL` (used to validate file type)
  - Version number (for forward compatibility)
  - Total number of frames
  - Frame width and height
  - FPS represented as a rational number (`fps_num / fps_den`)
  - Audio metadata:
    - `audio_offset` (0 if no audio)
    - `audio_size`
  - `oit_offset` (offset to the Offset Index Table)
- The header is written once at the beginning and patched during finalization.

---

## Frame Layout

Each frame is stored independently and consists of:

### 1. Frame Header (32 bytes)

- Width and height
- Compressed sizes of:
  - Y plane (`ylen`)
  - U plane (`ulen`)
  - V plane (`vlen`)
- Frame index (used for integrity validation)

### 2. Frame Data

- Compressed Y plane  
- Compressed U plane  
- Compressed V plane  

All planes are stored in **YUV420 format**:
- Y: full resolution (`width × height`)
- U: quarter resolution (`width/2 × height/2`)
- V: quarter resolution (`width/2 × height/2`)

Each plane is compressed independently using **Zstandard (zstd)**.

---

## Offset Index Table (OIT)

- The OIT enables **O(1) random frame access**
- It is stored near the end of the file
- Each entry contains:
  - Byte offset of a frame

### Structure

- `total_frames` entries
- Each entry is 8 bytes (`u64` offset)

### Access

To access frame `i`:
1. Read `OIT[i]`
2. Seek directly to that byte offset
3. Decode the frame

---

## Footer

- The last 8 bytes of the file store the `oit_offset`
- This allows the reader to locate the OIT quickly without scanning the file

---

## Audio Storage

- Audio is stored as a **single contiguous block**
- Format:
  - 32-bit floating point samples (`f32`)
- Located at:
  - `audio_offset` in the file header
- Size:
  - `audio_size`

### Design Choice

- Audio is separated from video frames to:
  - simplify editing
  - allow independent replacement
  - avoid interleaving complexity

---

## Compression

- Each frame’s Y, U, and V planes are compressed independently using **Zstandard**
- Compression level is configurable during encoding

### Important

- Frame header stores **compressed sizes**, not raw sizes
- This ensures correct decoding and prevents buffer mismatches

---

## Design Goals

- Fast random access (O(1) frame seeking)
- Simple decoding pipeline
- Efficient compression with minimal complexity
- Suitable as an **intermediate format for editing workflows**
- Easy integration with tools like FFmpeg

---

## Limitations

- No inter-frame compression (larger file sizes compared to codecs like H.264)
- No built-in color space metadata (assumes YUV420)
- No streaming support (requires full file access)
- Minimal error resilience
