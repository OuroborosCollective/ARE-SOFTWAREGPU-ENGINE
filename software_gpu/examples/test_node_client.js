/**
 * Test script for Node.js SoftwareGPU client adapter.
 */

const { SoftwareGPUClient } = require('../clients/node_client');

async function main() {
    console.log("Starting Node.js SoftwareGPU Client Test...");
    const client = new SoftwareGPUClient({
        host: '127.0.0.1',
        httpPort: 8188,
        tcpPort: 8189
    });

    try {
        // 1. HTTP device info
        const info = await client.getDeviceInfo();
        console.log("Device Info received:", info.name, "SMs:", info.sm_count);

        // 2. TCP RPC GEMM test
        const A = [[1, 2], [3, 4]];
        const B = [[5, 6], [7, 8]];
        const res = await client.gemm(A, B);
        console.log("GEMM via TCP Socket succeeded! Result shape:", res.result.shape);
        console.log("Node.js client verified successfully!");
    } catch (err) {
        console.error("Test failed:", err);
        process.exit(1);
    }
}

main();
