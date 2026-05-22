use crate::{
    error::AuraResult,
    frame::{AudioFrame, YuvFrame},
    header::{FILEHEADERSIZE, FileHeader},
    oit::{OitEntry, write_oit},
};
use bytemuck::bytes_of;
use std::fs::{File, OpenOptions};
use std::io::{BufWriter, Seek, SeekFrom, Write};

pub struct AuraWriter {
    inner: BufWriter<File>,
    oit: Vec<OitEntry>,
    current_offset: u64,
    frame_count: u64,
    width: u32,
    height: u32,
    audio_offset: u64,
    audio_size: u64,
}

impl AuraWriter {
    pub fn new(path: &str, header: FileHeader) -> AuraResult<Self> {
        let file = OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .open(path)?;
        let mut inner = BufWriter::with_capacity(64 * 1024 * 1024, file);
        inner.write_all(bytes_of(&header))?;
        Ok(Self {
            inner,
            oit: Vec::new(),
            current_offset: FILEHEADERSIZE as u64,
            frame_count: 0,
            width: header.width,
            height: header.height,
            audio_offset: 0,
            audio_size: 0,
        })
    }
    pub fn write_frame(&mut self, frame: YuvFrame) -> AuraResult<()> {
        let compressed = frame.compress()?;

        self.oit.push(OitEntry {
            byte_offset: self.current_offset,
        });

        let frame_header = compressed.header;
        self.inner.write_all(bytes_of(&frame_header))?;
        self.current_offset += crate::frame::FRAME_HEADER_SIZE as u64;

        self.inner.write_all(&compressed.ydata)?;
        self.current_offset += frame_header.ylen as u64;

        self.inner.write_all(&compressed.udata)?;
        self.current_offset += frame_header.ulen as u64;

        self.inner.write_all(&compressed.vdata)?;
        self.current_offset += frame_header.vlen as u64;

        self.frame_count += 1;
        Ok(())
    }
    fn write_audio_frame(&mut self, frame: &AudioFrame) -> AuraResult<()> {
        // 1. Write header (timestamp + metadata)

        self.inner
            .write_all(&frame.header.timestamp.pts.to_le_bytes())?;
        self.inner
            .write_all(&frame.header.timestamp.num.to_le_bytes())?;
        self.inner
            .write_all(&frame.header.timestamp.den.to_le_bytes())?;

        self.inner
            .write_all(&frame.header.sample_rate.to_le_bytes())?;
        self.inner.write_all(&frame.header.channels.to_le_bytes())?;

        let sample_count = frame.samples.len() as u32;
        self.inner.write_all(&sample_count.to_le_bytes())?;

        // 2. Write samples
        let bytes = bytemuck::cast_slice::<f32, u8>(&frame.samples);
        self.inner.write_all(bytes)?;

        // 3. Update offset
        self.current_offset += (8 + 4 + 4) + // timestamp
        4 + 2 +       // sample_rate + channels
        4 +           // sample_count
        bytes.len() as u64;

        Ok(())
    }
    pub fn write_audio(&mut self, samples: &[f32], sample_rate: u32) -> AuraResult<()> {
        self.audio_offset = self.current_offset;

        let frames = AudioFrame::split_audio(samples.to_vec(), sample_rate);

        for frame in frames {
            self.write_audio_frame(&frame)?;
        }

        self.audio_size = self.current_offset - self.audio_offset;
        Ok(())
    }

    pub fn finalize(mut self, fps_num: u32, fps_den: u32) -> AuraResult<()> {
        let oit_offset = self.current_offset;
        write_oit(&mut self.inner, &self.oit)?;
        self.inner.write_all(&oit_offset.to_le_bytes())?;
        self.inner.flush()?;

        let file = self.inner.get_mut();
        file.seek(SeekFrom::Start(0))?;

        let patched = FileHeader {
            magic: *crate::header::MAGIC,
            version: crate::header::VERSION,
            reserved: 0,
            total_frames: self.frame_count,
            width: self.width,
            height: self.height,
            fps_num,
            fps_den,
            audio_offset: self.audio_offset,
            audio_size: self.audio_size,
            oit_offset,
            _pad: [0u8; 16],
        };
        file.write_all(bytes_of(&patched))?;
        Ok(())
    }
}
