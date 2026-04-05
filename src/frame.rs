use bytemuck::{Pod, Zeroable};

use crate::error::{ReelError, ReelResult};
use lz4_flex::block::{compress_prepend_size, decompress_size_prepended};
pub const FRAME_HEADER_SIZE: usize = 24;
use rayon::join;

#[repr(C, packed)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub struct FrameHeader {
    pub ylen: u32, // compressed Y plane size in bytes
    pub ulen: u32, // compressed Cb plane size in bytes
    pub vlen: u32, // compressed Cr plane size in bytes
    pub index: u64,
    pub _pad: u32,
}

const _: () = assert!(std::mem::size_of::<FrameHeader>() == FRAME_HEADER_SIZE);

impl FrameHeader {
    pub fn new(ylen: u32, ulen: u32, vlen: u32, index: u64) -> Self {
        Self {
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

pub fn paeth_predictor(data: Vec<u8>, width: usize) -> ReelResult<Vec<u8>> {
    let original = data.clone();
    let mut out = data;

    for y in 0..original.len() / width {
        for x in 0..width {
            let i = y * width + x;
            let a = if x > 0 { original[i - 1] as i16 } else { 0 };
            let b = if y > 0 { original[i - width] as i16 } else { 0 };
            let c = if x > 0 && y > 0 {
                original[i - width - 1] as i16
            } else {
                0
            };

            let p = a + b - c;
            let pa = (p - a).abs();
            let pb = (p - b).abs();
            let pc = (p - c).abs();

            let predictor = if pa <= pb && pa <= pc {
                a
            } else if pb <= pc {
                b
            } else {
                c
            };
            out[i] = original[i].wrapping_sub(predictor as u8);
        }
    }
    Ok(out)
}
pub fn paeth_rev(mut data: Vec<u8>, width: usize) -> Vec<u8> {
    let height = data.len() / width;
    for y in 0..height {
        for x in 0..width {
            let i = y * width + x;
            let a = if x > 0 { data[i - 1] } else { 0 };
            let b = if y > 0 { data[i - width] } else { 0 };
            let c = if x > 0 && y > 0 {
                data[i - width - 1]
            } else {
                0
            };

            let p = a as i16 + b as i16 - c as i16;
            let pa = (p - a as i16).abs();
            let pb = (p - b as i16).abs();
            let pc = (p - c as i16).abs();

            let pred = if pa <= pb && pa <= pc {
                a
            } else if pb <= pc {
                b
            } else {
                c
            };
            data[i] = data[i].wrapping_add(pred);
        }
    }
    data
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

    pub fn compress(&self) -> ReelResult<CompressedFrame> {
        let (y, (u, v)) = rayon::join(
            || zstd::encode_all(self.ydata, 1),
            || {
                rayon::join(
                    || zstd::encode_all(self.udata, 1),
                    || zstd::encode_all(self.vdata, 1),
                )
            },
        );
        let y = y?;
        let u = u?;
        let v = v?;
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

        let mut header = self.header;
        header.ylen = y.len() as u32;
        header.ulen = u.len() as u32;
        header.vlen = v.len() as u32;
        Ok(DecodedFrame {
            header: header,
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
