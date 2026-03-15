use crate::error::{ReelError, ReelResult};
use bytemuck::{Pod, Zeroable, bytes_of, from_bytes};
use std::io::{Read, Write};

pub const OIT_ENTRY_SIZE: usize = 8;

#[repr(C, packed)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub struct OitEntry {
    pub byte_offset: u64,
}

const _: () = assert!(std::mem::size_of::<OitEntry>() == OIT_ENTRY_SIZE);

pub fn write_oit<W: Write>(writer: &mut W, entries: &[OitEntry]) -> ReelResult<()> {
    for entry in entries {
        writer.write_all(bytes_of(entry))?;
    }
    Ok(())
}

pub fn read_oit<R: Read>(reader: &mut R, frame_count: u64) -> ReelResult<Vec<OitEntry>> {
    let mut oit = Vec::with_capacity(frame_count as usize);
    for _ in 0..frame_count {
        let mut buf = [0u8; OIT_ENTRY_SIZE];
        reader.read_exact(&mut buf)?;
        oit.push(*from_bytes::<OitEntry>(&buf));
    }
    Ok(oit)
}
