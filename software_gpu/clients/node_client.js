/**
 * Node.js / TypeScript Client Adapter for SoftwareGPU.
 * Zero-dependency native Node.js implementation using 'http' and 'net' modules.
 */

const http = require('http');
const net = require('net');

const HEADER_SIZE = 20;
const MAX_FRAME_BYTES = 1_048_576n; // Payload ceiling in network/protocol.py.

class SoftwareGPUClient {
    constructor(options = {}) {
        this.host = options.host || '127.0.0.1';
        this.httpPort = options.httpPort || 8088;
        this.tcpPort = options.tcpPort || 8089;
        this.token = options.token || process.env.SOFTWAREGPU_AUTH_TOKEN;
        if (!this.token) throw new Error('SOFTWAREGPU_AUTH_TOKEN required');
    }

    /**
     * Queries GPU device properties via HTTP endpoint.
     */
    async getDeviceInfo() {
        return new Promise((resolve, reject) => {
            http.get(`http://${this.host}:${this.httpPort}/health`, {headers: {Authorization: `Bearer ${this.token}`}}, (res) => {
                let data = '';
                res.on('data', chunk => data += chunk);
                res.on('end', () => {
                    try {
                        const json = JSON.parse(data);
                        resolve(json.gpu);
                    } catch (e) {
                        reject(e);
                    }
                });
            }).on('error', reject);
        });
    }

    /**
     * Executes JSON-RPC method over high-speed TCP binary socket.
     */
    async callRpc(method, params = {}) {
        return new Promise((resolve, reject) => {
            const client = new net.Socket();
            client.connect(this.tcpPort, this.host, () => {
                const reqJson = JSON.stringify({ method, params, id: 1, token: this.token });
                const payloadBuf = Buffer.from(reqJson, 'utf-8');

                // Header: Magic(4) + MsgType(4) + Flags(4) + PayloadLen(8) = 20 Bytes
                const header = Buffer.alloc(HEADER_SIZE);
                header.write('SGPU', 0, 4, 'ascii');
                header.writeUInt32BE(1, 4); // MsgType.JSON_REQUEST
                header.writeUInt32BE(0, 8); // Flags
                header.writeBigUInt64BE(BigInt(payloadBuf.length), 12);

                client.write(Buffer.concat([header, payloadBuf]));
            });

            const responseHeader = Buffer.alloc(HEADER_SIZE);
            let headerBytes = 0;
            let body = null;
            let bodyBytes = 0;

            client.on('data', (chunk) => {
                let offset = 0;
                if (body === null) {
                    offset = chunk.copy(responseHeader, headerBytes);
                    headerBytes += offset;
                    if (headerBytes < HEADER_SIZE) return;

                    const length = responseHeader.readBigUInt64BE(12);
                    if (length > MAX_FRAME_BYTES) {
                        client.destroy();
                        reject(new Error('FRAME_TOO_LARGE'));
                        return;
                    }
                    body = Buffer.alloc(Number(length));
                }

                bodyBytes += chunk.copy(body, bodyBytes, offset);
                if (bodyBytes === body.length) {
                    client.destroy();
                    try {
                        const parsed = JSON.parse(body.toString('utf-8'));
                        if (parsed.error) reject(new Error(parsed.error));
                        else resolve(parsed.result);
                    } catch (err) {
                        reject(err);
                    }
                }
            });

            client.on('error', (err) => {
                reject(err);
            });
        });
    }

    /**
     * Offloads Matrix Multiplication.
     */
    async gemm(matrixA, matrixB) {
        return this.callRpc('gemm', { a: matrixA, b: matrixB });
    }
}

module.exports = { SoftwareGPUClient };
