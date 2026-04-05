use crate::{
    error::{ReelError, ReelResult},
    frame::{CompressedFrame, DecodedFrame, FRAME_HEADER_SIZE, FrameHeader},
    header::{FILEHEADERSIZE, FileHeader, MAGIC, VERSION},
    oit::{OIT_ENTRY_SIZE, OitEntry},
};
use bytemuck::from_bytes;
use std::fs::{File, OpenOptions};
use std::io::{BufReader, Read, Seek, SeekFrom};

pub struct ReelReader {
    inner: BufReader<File>,
    pub header: FileHeader,
    oit: Vec<OitEntry>,
}

impl ReelReader {
    pub fn open(path: &str) -> ReelResult<Self> {
        let file = OpenOptions::new().read(true).open(path)?;
        let mut inner = BufReader::with_capacity(64 * 1024 * 1024, file);

        // read and validate file header
        let mut hdr_buf = [0u8; FILEHEADERSIZE];
        inner.read_exact(&mut hdr_buf)?;
        let header = *from_bytes::<FileHeader>(&hdr_buf);

        if &header.magic != MAGIC {
            return Err(ReelError::InvalidMagic);
        }
        if header.version != VERSION {
            return Err(ReelError::UnsupportedVersion(header.version));
        }

        // read footer — last 8 bytes are oit_offset
        inner.seek(SeekFrom::End(-8))?;
        let mut footer_buf = [0u8; 8];
        inner.read_exact(&mut footer_buf)?;
        let oit_offset = u64::from_le_bytes(footer_buf);

        // load entire OIT into RAM
        inner.seek(SeekFrom::Start(oit_offset))?;
        let mut oit = Vec::with_capacity(header.total_frames as usize);
        for _ in 0..header.total_frames {
            let mut entry_buf = [0u8; OIT_ENTRY_SIZE];
            inner.read_exact(&mut entry_buf)?;
            oit.push(*from_bytes::<OitEntry>(&entry_buf));
        }

        Ok(Self { inner, header, oit })
    }

    pub fn read_frame(&mut self, index: u64) -> ReelResult<DecodedFrame> {
        // get byte offset from OIT
        let byte_offset = self
            .oit
            .get(index as usize)
            .ok_or(ReelError::FrameOutOfBounds(index, self.header.total_frames))?
            .byte_offset;

        self.inner.seek(SeekFrom::Start(byte_offset))?;

        // read frame header
        let mut hdr_buf = [0u8; FRAME_HEADER_SIZE];
        self.inner.read_exact(&mut hdr_buf)?;
        let frame_header = *from_bytes::<FrameHeader>(&hdr_buf);

        // corruption check
        if frame_header.index != index {
            return Err(ReelError::CorruptOit);
        }

        // read compressed planes
        let mut ydata = vec![0u8; frame_header.ylen as usize];
        let mut udata = vec![0u8; frame_header.ulen as usize];
        let mut vdata = vec![0u8; frame_header.vlen as usize];

        self.inner.read_exact(&mut ydata)?;
        self.inner.read_exact(&mut udata)?;
        self.inner.read_exact(&mut vdata)?;

        let compressed = CompressedFrame {
            header: frame_header,
            ydata,
            udata,
            vdata,
        };

        // decompress using your function
        let decoded = compressed.decompress()?;

        Ok(decoded)
    }

    pub fn read_audio(&mut self) -> ReelResult<Option<Vec<f32>>> {
        if self.header.audio_offset == 0 {
            return Ok(None);
        }
        self.inner.seek(SeekFrom::Start(self.header.audio_offset))?;
        let sample_count = self.header.audio_size / 4;
        let mut samples = vec![0f32; sample_count as usize];
        let bytes = bytemuck::cast_slice_mut::<f32, u8>(&mut samples);
        self.inner.read_exact(bytes)?;
        Ok(Some(samples))
    }

    pub fn total_frames(&self) -> u64 {
        self.header.total_frames
    }

    pub fn fps(&self) -> f64 {
        self.header.fps_num as f64 / self.header.fps_den as f64
    }
}
