//! Rust Client Adapter for SoftwareGPU.
//! Supports Bevy, Fyrox, and Veloren game engine architectures.

use std::io::{Read, Write};
use std::net::TcpStream;

pub struct SoftwareGPUClient {
    stream: TcpStream,
}

impl SoftwareGPUClient {
    pub fn connect(host: &str, port: u16) -> std::io::Result<Self> {
        let stream = TcpStream::connect((host, port))?;
        Ok(Self { stream })
    }

    pub fn call_rpc(&mut self, method: &str, params_json: &str) -> std::io::Result<String> {
        let request = format!(
            "{{\"method\":\"{}\",\"params\":{},\"id\":1}}",
            method, params_json
        );
        let payload = request.as_bytes();
        let payload_len = payload.len() as u64;

        // Header: Magic (4B) + MsgType (4B) + Flags (4B) + Length (8B)
        let mut header = [0u8; 20];
        header[0..4].copy_from_slice(b"SGPU");
        header[4..8].copy_from_slice(&1u32.to_be_bytes());
        header[8..12].copy_from_slice(&0u32.to_be_bytes());
        header[12..20].copy_from_slice(&payload_len.to_be_bytes());

        self.stream.write_all(&header)?;
        self.stream.write_all(payload)?;

        // Read response header
        let mut resp_header = [0u8; 20];
        self.stream.read_exact(&mut resp_header)?;

        let mut len_bytes = [0u8; 8];
        len_bytes.copy_from_slice(&resp_header[12..20]);
        let resp_len = u64::from_be_bytes(len_bytes) as usize;

        let mut body = vec![0u8; resp_len];
        self.stream.read_exact(&mut body)?;

        String::from_utf8(body).map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))
    }
}
