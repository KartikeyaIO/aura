use crate::frame::TimeStamp;
use bytemuck::{Pod, Zeroable};
pub const MAGIC: &[u8; 4] = b"AURA";
pub const VERSION: u16 = 1;
pub const FILEHEADERSIZE: usize = 72;
#[repr(C, packed)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub struct FileHeader {
    pub magic: [u8; 4],
    pub version: u16,
    pub reserved: u16,
    pub total_frames: u64,
    pub width: u32,
    pub height: u32,
    pub fps_num: u32, // playback hint only
    pub fps_den: u32,
    pub audio_offset: u64, // 0 if no audio
    pub audio_size: u64,
    pub oit_offset: u64,

    pub _pad: [u8; 16],
}

const _: () = assert!(std::mem::size_of::<FileHeader>() == FILEHEADERSIZE);

impl FileHeader {
    pub fn new(total_frames: u64, width: u32, height: u32, fps_num: u32, fps_den: u32) -> Self {
        Self {
            magic: *MAGIC,
            version: VERSION,
            reserved: 0,
            total_frames,
            width,
            height,
            fps_num,
            fps_den,
            audio_offset: 0, // filled in by writer on finalize
            audio_size: 0,
            oit_offset: 0, // filled in by writer on finalize
            _pad: [0u8; 16],
        }
    }

    pub fn validate(&self) -> bool {
        &self.magic == MAGIC && self.version == VERSION
    }
}

pub struct AudioHeader {
    pub timestamp: TimeStamp,
    pub sample_rate: u32,
    pub channels: u16,
}
