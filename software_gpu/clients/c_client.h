/**
 * C Client Header for SoftwareGPU.
 * Portable POSIX C99 implementation for C-based game servers and embedded engines.
 */

#ifndef SOFTWARE_GPU_C_CLIENT_H
#define SOFTWARE_GPU_C_CLIENT_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <stdint.h>

#define SGPU_MAGIC "SGPU"
#define SGPU_HEADER_SIZE 20

typedef struct {
    char host[64];
    int port;
    int socket_fd;
} sgpu_client_t;

static inline int sgpu_connect(sgpu_client_t* client, const char* host, int port) {
    strncpy(client->host, host, sizeof(client->host) - 1);
    client->port = port;

    client->socket_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (client->socket_fd < 0) return -1;

    struct sockaddr_in serv_addr;
    memset(&serv_addr, 0, sizeof(serv_addr));
    serv_addr.sin_family = AF_INET;
    serv_addr.sin_port = htons(port);
    inet_pton(AF_INET, host, &serv_addr.sin_addr);

    if (connect(client->socket_fd, (struct sockaddr*)&serv_addr, sizeof(serv_addr)) < 0) {
        close(client->socket_fd);
        client->socket_fd = -1;
        return -1;
    }
    return 0;
}

static inline void sgpu_disconnect(sgpu_client_t* client) {
    if (client->socket_fd >= 0) {
        close(client->socket_fd);
        client->socket_fd = -1;
    }
}

static inline int sgpu_send_rpc(sgpu_client_t* client, const char* json_request, char* response_buf, size_t max_buf) {
    if (client->socket_fd < 0) return -1;

    uint32_t msg_type = htonl(1);
    uint32_t flags = htonl(0);
    uint64_t payload_len = strlen(json_request);
    
    // Convert 64-bit length to big-endian
    uint32_t len_high = htonl((uint32_t)(payload_len >> 32));
    uint32_t len_low = htonl((uint32_t)(payload_len & 0xFFFFFFFF));

    uint8_t header[20];
    memcpy(header, SGPU_MAGIC, 4);
    memcpy(header + 4, &msg_type, 4);
    memcpy(header + 8, &flags, 4);
    memcpy(header + 12, &len_high, 4);
    memcpy(header + 16, &len_low, 4);

    if (send(client->socket_fd, header, 20, 0) != 20) return -2;
    if (send(client->socket_fd, json_request, payload_len, 0) != (ssize_t)payload_len) return -3;

    // Receive response header
    uint8_t resp_header[20];
    ssize_t received = recv(client->socket_fd, resp_header, 20, MSG_WAITALL);
    if (received != 20) return -4;

    uint32_t r_len_high, r_len_low;
    memcpy(&r_len_high, resp_header + 12, 4);
    memcpy(&r_len_low, resp_header + 16, 4);
    uint64_t resp_len = (((uint64_t)ntohl(r_len_high)) << 32) | ntohl(r_len_low);

    if (resp_len >= max_buf) resp_len = max_buf - 1;
    ssize_t body_recv = recv(client->socket_fd, response_buf, resp_len, MSG_WAITALL);
    if (body_recv < 0) return -5;
    response_buf[body_recv] = '\0';

    return 0;
}

#endif /* SOFTWARE_GPU_C_CLIENT_H */
