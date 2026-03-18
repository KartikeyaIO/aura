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

pub struct YuvFrame {
    header: FrameHeader,
    ydata: Vec<u8>,
    udata: Vec<u8>,
    vdata: Vec<u8>,
}

impl YuvFrame {
    pub fn new(header: FrameHeader, ydata: Vec<u8>, udata: Vec<u8>, vdata: Vec<u8>) -> Self {
        Self {
            header,
            ydata,
            udata,
            vdata,
        }
    }
    pub fn compress(&mut self, level: i32) -> ReelResult<()> {
        self.ydata = zstd::encode_all(self.ydata.as_slice(), level)
            .map_err(|e| ReelError::Compression(e.to_string()))?;
        self.udata = zstd::encode_all(self.udata.as_slice(), level)
            .map_err(|e| ReelError::Compression(e.to_string()))?;
        self.vdata = zstd::encode_all(self.vdata.as_slice(), level)
            .map_err(|e| ReelError::Compression(e.to_string()))?;
        self.header.ylen = self.ydata.len() as u32;
        self.header.ulen = self.udata.len() as u32;
        self.header.vlen = self.vdata.len() as u32;
        Ok(())
    }
    pub fn decompress(&mut self) -> ReelResult<()> {
        self.ydata = zstd::decode_all(self.ydata.as_slice())
            .map_err(|e| ReelError::Decompression(e.to_string()))?;
        self.udata = zstd::decode_all(self.udata.as_slice())
            .map_err(|e| ReelError::Decompression(e.to_string()))?;
        self.vdata = zstd::decode_all(self.vdata.as_slice())
            .map_err(|e| ReelError::Decompression(e.to_string()))?;
        Ok(())
    }
}
impl YuvFrame {
    pub fn header(&self) -> FrameHeader {
        self.header
    }
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
