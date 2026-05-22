use thiserror::Error;

#[derive(Debug, Error)]
pub enum AuraError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Compression error: {0}")]
    Compression(String),

    #[error("Decompression error: {0}")]
    Decompression(String),

    #[error("Invalid magic bytes — not a Reel file")]
    InvalidMagic,

    #[error("Unsupported format version: {0}")]
    UnsupportedVersion(u16),

    #[error("Frame index {0} out of bounds (total frames: {1})")]
    FrameOutOfBounds(u64, u64),

    #[error("Corrupt OIT — entry count mismatch")]
    CorruptOit,

    #[error("Invalid frame header at offset {0}")]
    InvalidFrameHeader(u64),
}

pub type AuraResult<T> = Result<T, AuraError>;
