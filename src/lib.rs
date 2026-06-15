pub mod error;
pub mod frame;
pub mod header;
pub mod oit;
pub mod reader;
pub mod writer;

pub enum Aura {
    Reader(reader::AuraReader),
    Writer(writer::AuraWriter),
}

pub fn convert_to_aura(
    width: u32,
    height: u32,
    input: &str,
    output: &str,
    frames: u64,
    fps_num: u32,
    fps_den: u32,
) -> Result<(), Box<dyn std::error::Error>> {
    use crate::frame::{CompressedFrame, FrameHeader, TimeStamp, YuvFrame};
    use crate::header::FileHeader;
    use crate::writer::AuraWriter;
    use rayon::prelude::*;
    use std::fs;
    use std::io::{BufReader, Read};

    let y_size = (width * height) as usize;
    let uv_size = ((width / 2) * (height / 2)) as usize;
    let frame_size = y_size + 2 * uv_size;

    let header = FileHeader::new(frames, width, height, fps_num, fps_den);
    let mut writer = AuraWriter::new(output, header)?;

    let file = fs::File::open(input)?;
    // Restoring original 8MB buffer size to prevent alignment quirks
    let mut reader = BufReader::with_capacity(8 * 1024 * 1024, file);

    let batch_size = 64usize;
    let mut frame_index = 0u64;

    while frame_index < frames {
        // Force explicit casting to prevent type mismatch or over-reading
        let remaining = (frames - frame_index) as usize;
        let current_batch_count = std::cmp::min(batch_size, remaining);

        let mut raw_frames_batch = Vec::with_capacity(current_batch_count);

        // 1. Read sequential raw frames safely from disk
        for i in 0..current_batch_count {
            let mut frame_buf = vec![0u8; frame_size];
            reader.read_exact(&mut frame_buf)?;
            raw_frames_batch.push((frame_index + i as u64, frame_buf));
        }

        // 2. Parallel compression across all available threads
        let compressed_batch: Vec<crate::error::AuraResult<CompressedFrame>> = raw_frames_batch
            .into_par_iter()
            .map(|(idx, buf)| {
                let y_data = &buf[..y_size];
                let u_data = &buf[y_size..y_size + uv_size];
                let v_data = &buf[y_size + uv_size..];

                let timestamp = TimeStamp {
                    pts: idx as i64,
                    num: fps_den,
                    den: fps_num,
                };

                let fh = FrameHeader::new(
                    y_size as u32,
                    uv_size as u32,
                    uv_size as u32,
                    idx,
                    timestamp,
                );
                let frame = YuvFrame::new(fh, y_data, u_data, v_data);
                frame.compress()
            })
            .collect();

        // 3. Write back sequentially to preserve perfect OIT layout
        for res in compressed_batch {
            let compressed_frame = res?;
            writer.write_compressed_frame(compressed_frame)?;
        }

        frame_index += current_batch_count as u64;
    }

    writer.finalize(fps_num, fps_den)?;
    Ok(())
}

pub fn convert_to_yuv(input: &str, output: &str) -> Result<(), Box<dyn std::error::Error>> {
    use crate::reader::AuraReader;
    use std::fs;
    use std::io::BufWriter;

    let mut reader = AuraReader::open(input)?;
    let out_file = fs::File::create(output)?;
    let buffered = BufWriter::with_capacity(64 * 1024 * 1024, out_file);
    reader.decode_all(buffered)?;
    Ok(())
}
