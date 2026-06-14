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
    use crate::frame::{FrameHeader, TimeStamp, YuvFrame};
    use crate::header::FileHeader;
    use crate::writer::AuraWriter;
    use std::fs;
    use std::io::{BufReader, Read};

    let y_size = (width * height) as usize;
    let uv_size = ((width / 2) * (height / 2)) as usize;
    let frame_size = y_size + 2 * uv_size;

    let header = FileHeader::new(frames, width, height, fps_num, fps_den);
    let mut writer = AuraWriter::new(output, header)?;

    let file = fs::File::open(input)?;
    let mut reader = BufReader::with_capacity(8 * 1024 * 1024, file);
    let mut frame_buf = vec![0u8; frame_size];

    for i in 0..frames {
        reader.read_exact(&mut frame_buf)?;

        let y_data = &frame_buf[..y_size];
        let u_data = &frame_buf[y_size..y_size + uv_size];
        let v_data = &frame_buf[y_size + uv_size..];

        let timestamp = TimeStamp {
            pts: i as i64,
            num: fps_den,
            den: fps_num,
        };

        let fh = FrameHeader::new(y_size as u32, uv_size as u32, uv_size as u32, i, timestamp);
        let frame = YuvFrame::new(fh, y_data, u_data, v_data);
        writer.write_frame(frame)?;
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
