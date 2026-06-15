use crate::{
    error::{AuraError, AuraResult},
    frame::{AudioFrame, CompressedFrame, DecodedFrame, FRAME_HEADER_SIZE, FrameHeader, TimeStamp},
    header::{AudioHeader, FILEHEADERSIZE, FileHeader, MAGIC, VERSION},
    oit::{OIT_ENTRY_SIZE, OitEntry},
};
use bytemuck::from_bytes;
use std::fs::{File, OpenOptions};
use std::io::{BufReader, Read, Seek, SeekFrom};

pub struct AuraReader {
    inner: BufReader<File>,
    pub header: FileHeader,
    oit: Vec<OitEntry>,
}

impl AuraReader {
    pub fn open(path: &str) -> AuraResult<Self> {
        let file = OpenOptions::new().read(true).open(path)?;
        let mut inner = BufReader::new(file);

        // read and validate file header
        let mut hdr_buf = [0u8; FILEHEADERSIZE];
        inner.read_exact(&mut hdr_buf)?;
        let header = *from_bytes::<FileHeader>(&hdr_buf);

        if &header.magic != MAGIC {
            return Err(AuraError::InvalidMagic);
        }
        if header.version != VERSION {
            return Err(AuraError::UnsupportedVersion(header.version));
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

    pub fn read_frame(&mut self, index: u64) -> AuraResult<DecodedFrame> {
        // get byte offset from OIT
        let byte_offset = self
            .oit
            .get(index as usize)
            .ok_or(AuraError::FrameOutOfBounds(index, self.header.total_frames))?
            .byte_offset;

        self.inner.seek(SeekFrom::Start(byte_offset))?;

        // read frame header
        let mut hdr_buf = [0u8; FRAME_HEADER_SIZE];
        self.inner.read_exact(&mut hdr_buf)?;
        let frame_header = *from_bytes::<FrameHeader>(&hdr_buf);

        // corruption check
        if frame_header.index != index {
            return Err(AuraError::CorruptOit);
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

    pub fn read_audio(&mut self) -> AuraResult<Option<Vec<AudioFrame>>> {
        if self.header.audio_offset == 0 {
            return Ok(None);
        }
        self.inner.seek(SeekFrom::Start(self.header.audio_offset))?;
        let end = self.header.audio_offset + self.header.audio_size;
        let mut frames = Vec::new();
        while self.inner.stream_position()? < end {
            let mut buf8 = [0u8; 8];
            let mut buf4 = [0u8; 4];
            let mut buf2 = [0u8; 2];
            self.inner.read_exact(&mut buf8)?;
            let pts = i64::from_le_bytes(buf8);

            self.inner.read_exact(&mut buf4)?;
            let num = u32::from_le_bytes(buf4);

            self.inner.read_exact(&mut buf4)?;
            let den = u32::from_le_bytes(buf4);

            let timestamp = TimeStamp { pts, num, den };

            // ---- metadata ----
            self.inner.read_exact(&mut buf4)?;
            let sample_rate = u32::from_le_bytes(buf4);

            self.inner.read_exact(&mut buf2)?;
            let channels = u16::from_le_bytes(buf2);

            self.inner.read_exact(&mut buf4)?;
            let sample_count = u32::from_le_bytes(buf4);

            // ---- samples ----
            let mut samples = vec![0f32; sample_count as usize];
            let bytes = bytemuck::cast_slice_mut::<f32, u8>(&mut samples);
            self.inner.read_exact(bytes)?;
            let header = AudioHeader {
                timestamp,
                sample_rate,
                channels,
            };

            frames.push(AudioFrame { header, samples });
        }

        Ok(Some(frames))
    }

    pub fn decode_all<W: std::io::Write>(&mut self, mut writer: W) -> AuraResult<()> {
        use std::io::Read as _;

        let width = self.header.width as usize;
        let height = self.header.height as usize;
        let y_decoded_len = width * height;
        let uv_decoded_len = (width / 2) * (height / 2);

        let mut read_buf: Vec<u8> = Vec::with_capacity(y_decoded_len);
        let mut decode_buf: Vec<u8> = vec![0u8; y_decoded_len];

        self.inner.seek(SeekFrom::Start(FILEHEADERSIZE as u64))?;

        for _ in 0..self.header.total_frames {
            let mut hdr_buf = [0u8; FRAME_HEADER_SIZE];
            self.inner.read_exact(&mut hdr_buf)?;
            let frame_header = *from_bytes::<FrameHeader>(&hdr_buf);

            let ylen = frame_header.ylen as usize;
            read_buf.resize(ylen, 0);
            self.inner.read_exact(&mut read_buf[..ylen])?;
            let mut dec = zstd::Decoder::new(&read_buf[..ylen])
                .map_err(|e| AuraError::Decompression(e.to_string()))?;
            dec.read_exact(&mut decode_buf[..y_decoded_len])
                .map_err(|e| AuraError::Decompression(e.to_string()))?;
            writer.write_all(&decode_buf[..y_decoded_len])?;

            let ulen = frame_header.ulen as usize;
            read_buf.resize(ulen, 0);
            self.inner.read_exact(&mut read_buf[..ulen])?;
            let mut dec = zstd::Decoder::new(&read_buf[..ulen])
                .map_err(|e| AuraError::Decompression(e.to_string()))?;
            dec.read_exact(&mut decode_buf[..uv_decoded_len])
                .map_err(|e| AuraError::Decompression(e.to_string()))?;
            writer.write_all(&decode_buf[..uv_decoded_len])?;

            let vlen = frame_header.vlen as usize;
            read_buf.resize(vlen, 0);
            self.inner.read_exact(&mut read_buf[..vlen])?;
            let mut dec = zstd::Decoder::new(&read_buf[..vlen])
                .map_err(|e| AuraError::Decompression(e.to_string()))?;
            dec.read_exact(&mut decode_buf[..uv_decoded_len])
                .map_err(|e| AuraError::Decompression(e.to_string()))?;
            writer.write_all(&decode_buf[..uv_decoded_len])?;
        }

        Ok(())
    }

    pub fn total_frames(&self) -> u64 {
        self.header.total_frames
    }

    pub fn fps(&self) -> f64 {
        self.header.fps_num as f64 / self.header.fps_den as f64
    }
}
