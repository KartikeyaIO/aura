pub mod error;
pub mod frame;
pub mod header;
pub mod oit;
pub mod reader;
pub mod writer;

pub enum Reel {
    Reader(reader::ReelReader),
    Writer(writer::ReelWriter),
}
