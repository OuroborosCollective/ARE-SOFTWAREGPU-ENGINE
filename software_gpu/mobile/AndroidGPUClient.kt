/**
 * Android Native Client Adapter for SoftwareGPU.
 * Supports Android LocalSocket (Unix Domain Socket / Abstract Namespace)
 * for ultra-low latency mobile IPC and standard TCP for remote/ADB operation.
 */

package com.softwaregpu.client

import android.net.LocalSocket
import android.net.LocalSocketAddress
import org.json.JSONObject
import java.io.InputStream
import java.io.OutputStream
import java.net.Socket
import java.nio.ByteBuffer
import java.nio.ByteOrder

class AndroidGPUClient(
    private val useLocalSocket: Boolean = true,
    private val abstractNamespace: String = "software_gpu",
    private val host: String = "127.0.0.1",
    private val tcpPort: Int = 8089
) : AutoCloseable {

    private var localSocket: LocalSocket? = null
    private var tcpSocket: Socket? = null
    private var inputStream: InputStream? = null
    private var outputStream: OutputStream? = null

    fun connect() {
        if (useLocalSocket) {
            // Android Abstract Namespace LocalSocket: requires no filesystem permissions!
            localSocket = LocalSocket().apply {
                connect(LocalSocketAddress(abstractNamespace, LocalSocketAddress.Namespace.ABSTRACT))
            }
            inputStream = localSocket!!.inputStream
            outputStream = localSocket!!.outputStream
        } else {
            // Standard TCP Socket / ADB reverse connection
            tcpSocket = Socket(host, tcpPort)
            inputStream = tcpSocket!!.inputStream
            outputStream = tcpSocket!!.outputStream
        }
    }

    fun callRpc(method: String, params: JSONObject): JSONObject {
        if (outputStream == null || inputStream == null) {
            connect()
        }

        val requestObj = JSONObject().apply {
            put("method", method)
            put("params", params)
            put("id", 1)
        }
        val payloadBytes = requestObj.toString().toByteArray(Charsets.UTF_8)
        val payloadLen = payloadBytes.size.toLong()

        // 20-byte Header: "SGPU" + Type(4) + Flags(4) + Length(8)
        val header = ByteBuffer.allocate(20).order(ByteOrder.BIG_ENDIAN)
        header.put("SGPU".toByteArray(Charsets.US_ASCII))
        header.putInt(1) // MsgType.JSON_REQUEST
        header.putInt(0) // Flags
        header.putLong(payloadLen)

        outputStream!!.write(header.array())
        outputStream!!.write(payloadBytes)
        outputStream!!.flush()

        // Read 20-byte response header
        val respHeader = ByteArray(20)
        readExact(inputStream!!, respHeader, 20)

        val headerBuf = ByteBuffer.wrap(respHeader).order(ByteOrder.BIG_ENDIAN)
        headerBuf.position(12)
        val respLen = headerBuf.long.toInt()

        val respBody = ByteArray(respLen)
        readExact(inputStream!!, respBody, respLen)

        val responseJson = JSONObject(String(respBody, Charsets.UTF_8))
        if (responseJson.has("error")) {
            throw RuntimeException(responseJson.getString("error"))
        }
        return responseJson.getJSONObject("result")
    }

    private fun readExact(stream: InputStream, buffer: ByteArray, count: Int) {
        var total = 0
        while (total < count) {
            val read = stream.read(buffer, total, count - total)
            if (read == -1) throw java.io.EOFException("Socket disconnected prematurely")
            total += read
        }
    }

    override fun close() {
        localSocket?.close()
        tcpSocket?.close()
    }
}
