/**
 * Node.js / TypeScript Client Adapter for SoftwareGPU.
 * Zero-dependency native Node.js implementation using 'http' and 'net' modules.
 */

const http = require('http');
const net = require('net');

class SoftwareGPUClient {
    constructor(options = {}) {
        this.host = options.host || '127.0.0.1';
        this.httpPort = options.httpPort || 8088;
        this.tcpPort = options.tcpPort || 8089;
    }

    /**
     * Queries GPU device properties via HTTP endpoint.
     */
    async getDeviceInfo() {
        return new Promise((resolve, reject) => {
            http.get(`http://${this.host}:${this.httpPort}/health`, (res) => {
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
                const reqJson = JSON.stringify({ method, params, id: 1 });
                const payloadBuf = Buffer.from(reqJson, 'utf-8');

                // Header: Magic(4) + MsgType(4) + Flags(4) + PayloadLen(8) = 20 Bytes
                const header = Buffer.alloc(20);
                header.write('SGPU', 0, 4, 'ascii');
                header.writeUInt32BE(1, 4); // MsgType.JSON_REQUEST
                header.writeUInt32BE(0, 8); // Flags
                header.writeBigUInt64BE(BigInt(payloadBuf.length), 12);

                client.write(Buffer.concat([header, payloadBuf]));
            });

            let responseBuffer = Buffer.alloc(0);
            let expectedLen = null;

            client.on('data', (chunk) => {
                responseBuffer = Buffer.concat([responseBuffer, chunk]);

                if (expectedLen === null && responseBuffer.length >= 20) {
                    expectedLen = Number(responseBuffer.readBigUInt64BE(12));
                }

                if (expectedLen !== null && responseBuffer.length >= 20 + expectedLen) {
                    const body = responseBuffer.slice(20, 20 + expectedLen);
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
