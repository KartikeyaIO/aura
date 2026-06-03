use clap::{Parser, Subcommand};
use reel::{convert_to_aura, convert_to_yuv};
use std::fs;
use std::time::Instant;

#[derive(Parser)]
#[command(name = "aurx")]
#[command(version = "1.0")]
#[command(about = "REEL encoder/decoder")]
struct Cli {
    #[arg(long, global = true)]
    quiet: bool,

    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Encode YUV420p -> REEL
    Encode {
        input: String,
        output: String,

        #[arg(long)]
        width: u32,

        #[arg(long)]
        height: u32,

        #[arg(long = "fps-num", default_value_t = 30)]
        fps_num: u32,

        #[arg(long = "fps-den", default_value_t = 1)]
        fps_den: u32,

        #[arg(long)]
        total_frames: Option<u64>,
    },

    /// Decode REEL -> YUV420p
    Decode {
        input: String,
        output: String,
        #[arg(long)]
        frame: Option<u64>,
    },
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let cli = Cli::parse();
    let quiet = cli.quiet;

    match cli.command {
        Commands::Encode {
            input,
            output,
            width,
            height,
            fps_num,
            fps_den,
            total_frames,
        } => {
            // 1. Validate dimensions
            if width % 2 != 0 || height % 2 != 0 {
                return Err("YUV420p requires even width and height".into());
            }

            // 2. Validate FPS denominator
            if fps_den == 0 {
                return Err("fps denominator cannot be zero".into());
            }

            // 3. Validate input file
            let metadata = fs::metadata(&input)?;
            let y_size = (width * height) as u64;
            let uv_size = ((width / 2) * (height / 2)) as u64;
            let frame_size = y_size + 2 * uv_size;
            let file_size = metadata.len();

            // 4. Validate divisibility
            if file_size % frame_size != 0 {
                return Err(format!(
                    "Input size ({}) is not divisible by frame size ({})",
                    file_size, frame_size
                )
                .into());
            }

            let max_frames = file_size / frame_size;
            let frames = match total_frames {
                Some(n) => {
                    if n > max_frames {
                        return Err(format!(
                            "Requested total frames ({}) exceeds available frames in file ({})",
                            n, max_frames
                        )
                        .into());
                    }
                    n
                }
                None => max_frames,
            };

            // 5. Validate frames > 0
            if frames == 0 {
                return Err("No valid frames found!".into());
            }

            let start = Instant::now();

            convert_to_aura(width, height, &input, &output, frames, fps_num, fps_den)?;

            let elapsed = start.elapsed();

            // 6. Verify output file exists
            if !std::path::Path::new(&output).exists() {
                return Err("Output file missing".into());
            }

            // 7. Verify size > header size
            let compressed_size = fs::metadata(&output)?.len();
            if compressed_size <= reel::header::FILEHEADERSIZE as u64 {
                return Err("Compressed output size is too small (header only or empty)".into());
            }

            // 8. Verify frame count matches
            let reader = reel::reader::AuraReader::open(&output)?;
            let total_frames = reader.header.total_frames;
            if total_frames != frames {
                return Err(format!(
                    "Frame count mismatch. Expected {}, got {}",
                    frames, total_frames
                )
                .into());
            }

            if !quiet {
                println!("Encode time: {:?}", elapsed);
                let original_size = fs::metadata(&input)?.len();
                println!(
                    "Compression ratio: {:.2}x",
                    original_size as f64 / compressed_size as f64
                );
                println!("Compressed size = {}", compressed_size);
            }
        }

        Commands::Decode {
            input,
            output,
            frame,
        } => {
            // 1. Verify input file exists
            if !std::path::Path::new(&input).exists() {
                return Err("Input file missing".into());
            }

            let start = Instant::now();

            match frame {
                Some(idx) => {
                    let mut reader = reel::reader::AuraReader::open(&input)?;
                    let out_file = fs::File::create(&output)?;
                    let decoded = reader.read_frame(idx)?;
                    let mut writer = std::io::BufWriter::new(out_file);
                    use std::io::Write;
                    writer.write_all(decoded.ydata())?;
                    writer.write_all(decoded.udata())?;
                    writer.write_all(decoded.vdata())?;
                }
                None => {
                    convert_to_yuv(&input, &output)?;
                }
            }

            let elapsed = start.elapsed();

            // 2. Verify output exists
            if !std::path::Path::new(&output).exists() {
                return Err("Decoded output file missing".into());
            }

            // 3. Verify decoded size matches expected size
            let reader = reel::reader::AuraReader::open(&input)?;
            let total_frames = reader.header.total_frames;
            let y_size = (reader.header.width * reader.header.height) as u64;
            let uv_size = ((reader.header.width / 2) * (reader.header.height / 2)) as u64;
            let frame_size = y_size + 2 * uv_size;

            let expected_decoded_size = match frame {
                Some(_) => frame_size,
                None => total_frames * frame_size,
            };

            let decoded_size = fs::metadata(&output)?.len();
            if decoded_size != expected_decoded_size {
                return Err(format!(
                    "Decoded size mismatch. Expected {}, got {}",
                    expected_decoded_size, decoded_size
                )
                .into());
            }

            if !quiet {
                println!("Decode time: {:?}", elapsed);
            }
        }
    }
    Ok(())
}
