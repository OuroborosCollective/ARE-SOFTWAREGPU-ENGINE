const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const net = require('node:net');
const { test } = require('node:test');
const { SoftwareGPUClient } = require('../clients/node_client');

const MAX_PAYLOAD_BYTES = 1_048_576;

function responseHeader(length) {
    const header = Buffer.alloc(20);
    header.write('SGPU');
    header.writeUInt32BE(2, 4); // JSON_RESPONSE
    header.writeBigUInt64BE(BigInt(length), 12);
    return header;
}

// Deliver exact data event boundaries without depending on TCP coalescing.
function startRpc(t) {
    const socket = new EventEmitter();
    socket.connect = () => {};
    socket.destroy = t.mock.fn();
    const constructor = t.mock.method(net, 'Socket', function () { return socket; });
    try {
        const client = new SoftwareGPUClient({ token: 'test-token' });
        return { socket, response: client.callRpc('gemm') };
    } finally {
        constructor.mock.restore();
    }
}

test('accepts a fragmented response at the protocol payload ceiling', async (t) => {
    const { socket, response } = startRpc(t);
    const header = responseHeader(MAX_PAYLOAD_BYTES);
    const body = Buffer.alloc(MAX_PAYLOAD_BYTES, ' ');
    body.write('{"result":{"value":42}}');

    socket.emit('data', header.subarray(0, 13));
    socket.emit('data', Buffer.concat([header.subarray(13), body.subarray(0, 7)]));
    for (let start = 7; start < body.length; start += 8192) {
        socket.emit('data', body.subarray(start, start + 8192));
    }

    assert.deepEqual(await response, { value: 42 });
    assert.equal(socket.destroy.mock.callCount(), 1);
});

test('rejects an out-of-range length on receipt of the complete header', async (t) => {
    const { socket, response } = startRpc(t);
    const header = responseHeader(MAX_PAYLOAD_BYTES + 1);
    socket.emit('data', header.subarray(0, 19));
    assert.equal(socket.destroy.mock.callCount(), 0);
    socket.emit('data', header.subarray(19));
    assert.equal(socket.destroy.mock.callCount(), 1);
    await assert.rejects(response, { message: 'FRAME_TOO_LARGE' });
});
