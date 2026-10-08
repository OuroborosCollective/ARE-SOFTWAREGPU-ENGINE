// Go Client Adapter for SoftwareGPU.
// High-concurrency client for multiplayer game server clusters and microservices.

package software_gpu

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"net"
)

type Client struct {
	conn net.Conn
}

func Connect(host string, port int) (*Client, error) {
	addr := fmt.Sprintf("%s:%d", host, port)
	conn, err := net.Dial("tcp", addr)
	if err != nil {
		return nil, err
	}
	return &Client{conn: conn}, nil
}

func (c *Client) Close() error {
	return c.conn.Close()
}

func (c *Client) CallRpc(method string, params map[string]interface{}) (map[string]interface{}, error) {
	reqMap := map[string]interface{}{
		"method": method,
		"params": params,
		"id":     1,
	}
	payload, err := json.Marshal(reqMap)
	if err != nil {
		return nil, err
	}

	// 20-byte Header: "SGPU" + Type(4) + Flags(4) + Length(8)
	header := make([]byte, 20)
	copy(header[0:4], "SGPU")
	binary.BigEndian.PutUint32(header[4:8], 1) // MsgType.JSON_REQUEST
	binary.BigEndian.PutUint32(header[8:12], 0)
	binary.BigEndian.PutUint64(header[12:20], uint64(len(payload)))

	if _, err := c.conn.Write(append(header, payload...)); err != nil {
		return nil, err
	}

	// Read response header
	respHeader := make([]byte, 20)
	if _, err := io.ReadFull(c.conn, respHeader); err != nil {
		return nil, err
	}

	respLen := binary.BigEndian.Uint64(respHeader[12:20])
	respBody := make([]byte, respLen)
	if _, err := io.ReadFull(c.conn, respBody); err != nil {
		return nil, err
	}

	var respMap map[string]interface{}
	if err := json.Unmarshal(respBody, &respMap); err != nil {
		return nil, err
	}

	if errMsg, ok := respMap["error"]; ok && errMsg != nil {
		return nil, fmt.Errorf("rpc error: %v", errMsg)
	}

	return respMap["result"].(map[string]interface{}), nil
}
