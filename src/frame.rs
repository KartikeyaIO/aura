use crate::error::{AuraError, AuraResult};
use crate::header::AudioHeader;
use bytemuck::{Pod, Zeroable};
pub const FRAME_HEADER_SIZE: usize = 40;

#[repr(C, packed)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub struct TimeStamp {
    pub pts: i64,
    pub num: u32,
    pub den: u32,
}
impl TimeStamp {
    pub fn to_seconds(&self) -> f64 {
        self.pts as f64 * (self.num as f64 / self.den as f64)
    }
    pub fn rescale(&self, new_num: u32, new_den: u32) -> Self {
        let new_pts =
            self.pts * new_den as i64 * self.num as i64 / (self.den as i64 * new_num as i64);

        Self {
            pts: new_pts,
            num: new_num,
            den: new_den,
        }
    }

    pub fn add(&self, other: &TimeStamp) -> Self {
        let other_rescaled = other.rescale(self.num, self.den);
        Self {
            pts: self.pts + other_rescaled.pts,
            num: self.num,
            den: self.den,
        }
    }
}

#[repr(C, packed)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub struct FrameHeader {
    pub ylen: u32, // compressed Y plane size in bytes
    pub ulen: u32, // compressed Cb plane size in bytes
    pub vlen: u32, // compressed Cr plane size in bytes
    pub index: u64,
    pub time: TimeStamp,
    pub _pad: u32,
}

const _: () = assert!(std::mem::size_of::<FrameHeader>() == FRAME_HEADER_SIZE);

impl FrameHeader {
    pub fn new(ylen: u32, ulen: u32, vlen: u32, index: u64, time: TimeStamp) -> Self {
        Self {
            ylen,
            ulen,
            vlen,
            time,
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
pub struct AudioFrame {
    pub header: AudioHeader,
    pub samples: Vec<f32>,
}
impl AudioFrame {
    pub fn split_audio(samples: Vec<f32>, sample_rate: u32) -> Vec<AudioFrame> {
        let chunk_size = 1024;
        let mut frames = Vec::new();

        for (i, chunk) in samples.chunks(chunk_size).enumerate() {
            let timestamp = TimeStamp {
                pts: (i * chunk_size) as i64,
                num: 1,
                den: sample_rate,
            };

            frames.push(AudioFrame {
                header: AudioHeader {
                    timestamp,
                    sample_rate,
                    channels: 1, // adjust if needed
                },
                samples: chunk.to_vec(),
            });
        }

        frames
    }
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

pub fn paeth_predictor(data: Vec<u8>, width: usize) -> AuraResult<Vec<u8>> {
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

    pub fn compress(&self) -> AuraResult<CompressedFrame> {
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
    pub fn decompress(&self) -> AuraResult<DecodedFrame> {
        let y = zstd::decode_all(&self.ydata[..])
            .map_err(|e| AuraError::Decompression(e.to_string()))?;
        let u = zstd::decode_all(&self.udata[..])
            .map_err(|e| AuraError::Decompression(e.to_string()))?;
        let v = zstd::decode_all(&self.vdata[..])
            .map_err(|e| AuraError::Decompression(e.to_string()))?;

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
