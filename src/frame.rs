use bytemuck::{Pod, Zeroable};

use crate::error::{ReelError, ReelResult};

pub const FRAME_HEADER_SIZE: usize = 32;

#[repr(C, packed)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub struct FrameHeader {
    pub width: u32,
    pub height: u32,
    pub ylen: u32, // compressed Y plane size in bytes
    pub ulen: u32, // compressed Cb plane size in bytes
    pub vlen: u32, // compressed Cr plane size in bytes
    pub index: u64,
    pub _pad: u32,
}

const _: () = assert!(std::mem::size_of::<FrameHeader>() == FRAME_HEADER_SIZE);

impl FrameHeader {
    pub fn new(width: u32, height: u32, ylen: u32, ulen: u32, vlen: u32, index: u64) -> Self {
        Self {
            width,
            height,
            ylen,
            ulen,
            vlen,
            index,
            _pad: 0,
        }
    }
}

pub struct YuvFrame<'a> {
    header: FrameHeader,
    ydata: &'a [u8],
    udata: &'a [u8],
    vdata: &'a [u8],
}

pub struct CompressedFrame {
    pub header: FrameHeader,
    pub ydata: Vec<u8>,
    pub udata: Vec<u8>,
    pub vdata: Vec<u8>,
}
pub struct DecodedFrame {
    pub header: FrameHeader,
    pub ydata: Vec<u8>,
    pub udata: Vec<u8>,
    pub vdata: Vec<u8>,
}

impl<'a> YuvFrame<'a> {
    pub fn new(header: FrameHeader, ydata: &'a [u8], udata: &'a [u8], vdata: &'a [u8]) -> Self {
        Self {
            header,
            ydata,
            udata,
            vdata,
        }
    }
    pub fn compress(&self, level: i32) -> ReelResult<CompressedFrame> {
        let y = zstd::encode_all(self.ydata, level)
            .map_err(|e| ReelError::Compression(e.to_string()))?;
        let u = zstd::encode_all(self.udata, level)
            .map_err(|e| ReelError::Compression(e.to_string()))?;
        let v = zstd::encode_all(self.vdata, level)
            .map_err(|e| ReelError::Compression(e.to_string()))?;

        let mut header = self.header;
        header.ylen = y.len() as u32;
        header.ulen = u.len() as u32;
        header.vlen = v.len() as u32;

        Ok(CompressedFrame {
            header,
            ydata: y,
            udata: u,
            vdata: v,
        })
    }
}
impl<'a> YuvFrame<'a> {
    pub fn header(&self) -> FrameHeader {
        self.header
    }
    pub fn ydata(&self) -> &[u8] {
        self.ydata
    }
    pub fn udata(&self) -> &[u8] {
        self.udata
    }
    pub fn vdata(&self) -> &[u8] {
        self.vdata
    }
}
impl CompressedFrame {
    pub fn decompress(&self) -> ReelResult<DecodedFrame> {
        let y = zstd::decode_all(&self.ydata[..])
            .map_err(|e| ReelError::Decompression(e.to_string()))?;
        let u = zstd::decode_all(&self.udata[..])
            .map_err(|e| ReelError::Decompression(e.to_string()))?;
        let v = zstd::decode_all(&self.vdata[..])
            .map_err(|e| ReelError::Decompression(e.to_string()))?;

        Ok(DecodedFrame {
            header: self.header,
            ydata: y,
            udata: u,
            vdata: v,
        })
    }
}
impl DecodedFrame {
    pub fn ydata(&self) -> &[u8] {
        &self.ydata
    }
    pub fn udata(&self) -> &[u8] {
        &self.udata
    }
    pub fn vdata(&self) -> &[u8] {
        &self.vdata
    }
}
