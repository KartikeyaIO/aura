pub mod error;
pub mod frame;
pub mod header;
pub mod oit;
pub mod reader;
pub mod writer;

pub struct Reel {
    reader: reader::ReelReader,
    writer: writer::ReelWriter,
}
