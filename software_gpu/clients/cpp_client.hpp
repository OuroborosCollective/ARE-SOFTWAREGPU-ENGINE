/**
 * C++ Client Header for SoftwareGPU.
 * Modern C++17 API for Unreal Engine, Godot C++, and Game Servers.
 */

#ifndef SOFTWARE_GPU_CPP_CLIENT_HPP
#define SOFTWARE_GPU_CPP_CLIENT_HPP

#include "c_client.h"
#include <string>
#include <vector>
#include <stdexcept>
#include <sstream>

namespace software_gpu {

class GPUClient {
public:
    GPUClient(const std::string& host = "127.0.0.1", int port = 8089)
        : host_(host), port_(port) {
        if (sgpu_connect(&client_, host_.c_str(), port_) != 0) {
            throw std::runtime_error("Failed to connect to SoftwareGPU server at " + host_ + ":" + std::to_string(port_));
        }
    }

    ~GPUClient() {
        sgpu_disconnect(&client_);
    }

    std::string call(const std::string& method, const std::string& params_json = "{}") {
        std::ostringstream ss;
        ss << "{\"method\":\"" << method << "\",\"params\":" << params_json << ",\"id\":1}";
        std::string request = ss.str();

        char buf[65536];
        int res = sgpu_send_rpc(&client_, request.c_str(), buf, sizeof(buf));
        if (res != 0) {
            throw std::runtime_error("RPC failed with error code: " + std::to_string(res));
        }
        return std::string(buf);
    }

    std::string get_device_info() {
        return call("device_info", "{}");
    }

private:
    std::string host_;
    int port_;
    sgpu_client_t client_;
};

} // namespace software_gpu

#endif // SOFTWARE_GPU_CPP_CLIENT_HPP
