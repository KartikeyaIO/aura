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
