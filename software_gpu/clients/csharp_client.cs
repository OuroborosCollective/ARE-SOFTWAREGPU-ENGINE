/**
 * C# / .NET Client Adapter for SoftwareGPU.
 * Compatible with Unity, Godot (C#), and .NET Core MMORPG Game Servers.
 */

using System;
using System.IO;
using System.Net.Sockets;
using System.Text;
using System.Threading.Tasks;

namespace SoftwareGPU.Client
{
    public class SoftwareGPUClient : IDisposable
    {
        private readonly string _host;
        private readonly int _tcpPort;
        private TcpClient _tcpClient;
        private NetworkStream _stream;

        public SoftwareGPUClient(string host = "127.0.0.1", int tcpPort = 8089)
        {
            _host = host;
            _tcpPort = tcpPort;
        }

        public async Task ConnectAsync()
        {
            _tcpClient = new TcpClient();
            await _tcpClient.ConnectAsync(_host, _tcpPort);
            _stream = _tcpClient.GetStream();
        }

        public async Task<string> CallRpcAsync(string method, string paramsJson = "{}")
        {
            if (_tcpClient == null || !_tcpClient.Connected)
            {
                await ConnectAsync();
            }

            string jsonReq = $"{{\"method\":\"{method}\",\"params\":{paramsJson},\"id\":1}}";
            byte[] payloadBytes = Encoding.UTF8.GetBytes(jsonReq);
            ulong payloadLen = (ulong)payloadBytes.Length;

            // Build 20-byte Header: Magic(4) + Type(4) + Flags(4) + Length(8)
            byte[] header = new byte[20];
            Encoding.ASCII.GetBytes("SGPU").CopyTo(header, 0);

            // Big-endian MsgType = 1
            header[4] = 0; header[5] = 0; header[6] = 0; header[7] = 1;
            // Flags = 0
            header[8] = 0; header[9] = 0; header[10] = 0; header[11] = 0;
            // Big-endian 64-bit Length
            for (int i = 0; i < 8; i++)
            {
                header[19 - i] = (byte)((payloadLen >> (i * 8)) & 0xFF);
            }

            await _stream.WriteAsync(header, 0, 20);
            await _stream.WriteAsync(payloadBytes, 0, payloadBytes.Length);

            // Read response header
            byte[] respHeader = new byte[20];
            await ReadExactAsync(_stream, respHeader, 20);

            ulong respLen = 0;
            for (int i = 0; i < 8; i++)
            {
                respLen = (respLen << 8) | respHeader[12 + i];
            }

            byte[] respBody = new byte[respLen];
            await ReadExactAsync(_stream, respBody, (int)respLen);

            return Encoding.UTF8.GetString(respBody);
        }

        private async Task ReadExactAsync(NetworkStream stream, byte[] buffer, int count)
        {
            int total = 0;
            while (total < count)
            {
                int read = await stream.ReadAsync(buffer, total, count - total);
                if (read == 0) throw new EndOfStreamException("Socket disconnected prematurely");
                total += read;
            }
        }

        public void Dispose()
        {
            _stream?.Dispose();
            _tcpClient?.Dispose();
        }
    }
}
