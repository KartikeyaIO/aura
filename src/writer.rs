use crate::{
    error::{ReelError, ReelResult},
    frame::YuvFrame,
    header::{FILEHEADERSIZE, FileHeader},
    oit::{OitEntry, write_oit},
};
use bytemuck::bytes_of;
use std::fs::{File, OpenOptions};
use std::io::{BufWriter, Seek, SeekFrom, Write};

pub struct ReelWriter {
    inner: BufWriter<File>,
    oit: Vec<OitEntry>,
    current_offset: u64,
    frame_count: u64,
    width: u32,
    height: u32,
    audio_offset: u64,
    audio_size: u64,
}

impl ReelWriter {
    pub fn new(path: &str, header: FileHeader) -> ReelResult<Self> {
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
    pub fn write_frame(&mut self, mut frame: YuvFrame, level: i32) -> ReelResult<()> {
        // compress in place — ylen/ulen/vlen in FrameHeader get updated to compressed sizes
        frame.compress(level)?;

        // record OIT entry before writing — current_offset is where this frame starts
        self.oit.push(OitEntry {
            byte_offset: self.current_offset,
        });

        // write frame header
        let frame_header = frame.header();
        self.inner.write_all(bytes_of(&frame_header))?;
        self.current_offset += crate::frame::FRAME_HEADER_SIZE as u64;

        // write compressed planes sequentially
        self.inner.write_all(frame.ydata())?;
        self.current_offset += frame_header.ylen as u64;

        self.inner.write_all(frame.udata())?;
        self.current_offset += frame_header.ulen as u64;

        self.inner.write_all(frame.vdata())?;
        self.current_offset += frame_header.vlen as u64;

        // pad to next 4KB boundary
        let remainder = self.current_offset % 4096;
        if remainder != 0 {
            let padding = 4096 - remainder;
            let zeros = vec![0u8; padding as usize];
            self.inner.write_all(&zeros)?;
            self.current_offset += padding;
        }

        self.frame_count += 1;
        Ok(())
    }

    pub fn write_audio(&mut self, samples: &[f32]) -> ReelResult<()> {
        self.audio_offset = self.current_offset; // record where audio starts
        let bytes = bytemuck::cast_slice::<f32, u8>(samples); // safe, no unsafe needed
        self.inner.write_all(bytes)?;
        self.audio_size = bytes.len() as u64;
        self.current_offset += self.audio_size;
        Ok(())
    }

    pub fn finalize(mut self, fps_num: u32, fps_den: u32) -> ReelResult<()> {
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
