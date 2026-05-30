use clap::{Parser, Subcommand};
use reel::frame::{FrameHeader, TimeStamp, YuvFrame};
use reel::header::FileHeader;
use reel::reader::AuraReader;
use reel::writer::AuraWriter;
use std::fs;
use std::io::{BufReader, Read, Write};

#[derive(Parser)]
#[command(name = "reel", version, about = "REEL video format CLI — encode, decode, and inspect .reel files")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Encode raw YUV420p video to .reel format
    Encode {
        /// Path to input raw YUV420p file
        input: String,
        /// Path to output .reel file
        output: String,
        /// Frame width in pixels
        #[arg(long)]
        width: u32,
        /// Frame height in pixels
        #[arg(long)]
        height: u32,
        /// FPS numerator (default: 30)
        #[arg(long, default_value_t = 30)]
        fps_num: u32,
        /// FPS denominator (default: 1)
        #[arg(long, default_value_t = 1)]
        fps_den: u32,
    },
    /// Decode .reel file to raw YUV420p
    Decode {
        /// Path to input .reel file
        input: String,
        /// Path to output raw YUV420p file
        output: String,
        /// Decode only a single frame by index (O(1) random access)
        #[arg(long)]
        frame: Option<u64>,
    },
    /// Print .reel file metadata as JSON
    Info {
        /// Path to input .reel file
        input: String,
    },
}

fn main() {
    let cli = Cli::parse();

    let result = match cli.command {
        Commands::Encode {
            input,
            output,
            width,
            height,
            fps_num,
            fps_den,
        } => encode(&input, &output, width, height, fps_num, fps_den),
        Commands::Decode {
            input,
            output,
            frame,
        } => decode(&input, &output, frame),
        Commands::Info { input } => info(&input),
    };

    if let Err(e) = result {
        eprintln!("Error: {e}");
        std::process::exit(1);
    }
}

fn encode(
    input: &str,
    output: &str,
    width: u32,
    height: u32,
    fps_num: u32,
    fps_den: u32,
) -> Result<(), Box<dyn std::error::Error>> {
    let y_size = (width * height) as usize;
    let uv_size = ((width / 2) * (height / 2)) as usize;
    let frame_size = y_size + 2 * uv_size;

    let file_size = fs::metadata(input)?.len() as usize;
    let total_frames = file_size / frame_size;

    if total_frames == 0 {
        return Err("Input file too small — no complete frames found".into());
    }

    eprintln!(
        "Encoding {total_frames} frames ({width}x{height} @ {fps_num}/{fps_den} fps)"
    );

    let header = FileHeader::new(total_frames as u64, width, height, fps_num, fps_den);
    let mut writer = AuraWriter::new(output, header)?;

    let file = fs::File::open(input)?;
    let mut reader = BufReader::with_capacity(8 * 1024 * 1024, file);
    let mut frame_buf = vec![0u8; frame_size];

    for i in 0..total_frames {
        reader.read_exact(&mut frame_buf)?;

        let y_data = &frame_buf[..y_size];
        let u_data = &frame_buf[y_size..y_size + uv_size];
        let v_data = &frame_buf[y_size + uv_size..];

        let timestamp = TimeStamp {
            pts: i as i64,
            num: fps_den,
            den: fps_num,
        };

        let fh = FrameHeader::new(
            y_size as u32,
            uv_size as u32,
            uv_size as u32,
            i as u64,
            timestamp,
        );
        let frame = YuvFrame::new(fh, y_data, u_data, v_data);
        writer.write_frame(frame)?;

        if (i + 1) % 100 == 0 || i + 1 == total_frames {
            eprintln!("  frame {}/{total_frames}", i + 1);
        }
    }

    writer.finalize(fps_num, fps_den)?;

    let out_size = fs::metadata(output)?.len();
    let ratio = file_size as f64 / out_size as f64;
    eprintln!(
        "Done. {total_frames} frames -> {output} ({out_size} bytes, {ratio:.2}x compression)"
    );
    Ok(())
}

fn decode(
    input: &str,
    output: &str,
    frame_index: Option<u64>,
) -> Result<(), Box<dyn std::error::Error>> {
    let mut reader = AuraReader::open(input)?;
    let mut out_file = fs::File::create(output)?;

    match frame_index {
        Some(idx) => {
            eprintln!("Decoding frame {idx} from {input}");
            let decoded = reader.read_frame(idx)?;
            out_file.write_all(decoded.ydata())?;
            out_file.write_all(decoded.udata())?;
            out_file.write_all(decoded.vdata())?;
            eprintln!("Done. Frame {idx} -> {output}");
        }
        None => {
            let total = reader.total_frames();
            eprintln!("Decoding {total} frames from {input}");
            for i in 0..total {
                let decoded = reader.read_frame(i)?;
                out_file.write_all(decoded.ydata())?;
                out_file.write_all(decoded.udata())?;
                out_file.write_all(decoded.vdata())?;

                if (i + 1) % 100 == 0 || i + 1 == total {
                    eprintln!("  frame {}/{total}", i + 1);
                }
            }
            eprintln!("Done. {total} frames -> {output}");
        }
    }

    Ok(())
}

fn info(input: &str) -> Result<(), Box<dyn std::error::Error>> {
    let reader = AuraReader::open(input)?;
    let h = reader.header;

    let file_size = fs::metadata(input)?.len();
    let total_frames = h.total_frames;
    let width = h.width;
    let height = h.height;
    let fps_num = h.fps_num;
    let fps_den = h.fps_den;
    let duration = if fps_num > 0 {
        total_frames as f64 * fps_den as f64 / fps_num as f64
    } else {
        0.0
    };

    let json = serde_json::json!({
        "file": input,
        "file_size_bytes": file_size,
        "total_frames": total_frames,
        "width": width,
        "height": height,
        "fps_num": fps_num,
        "fps_den": fps_den,
        "fps": if fps_den > 0 { fps_num as f64 / fps_den as f64 } else { 0.0 },
        "duration_s": duration,
        "has_audio": h.audio_offset != 0,
        "audio_offset": h.audio_offset,
        "audio_size": h.audio_size,
        "oit_offset": h.oit_offset,
    });

    println!("{}", serde_json::to_string_pretty(&json)?);
    Ok(())
}
