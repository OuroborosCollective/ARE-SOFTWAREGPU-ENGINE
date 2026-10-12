// Shared bounded native request, response and parity contract.
#pragma once
#include "workrooms.hpp"
#include <iostream>
#include <sstream>
#include <string>
#if defined(_WIN32)
#include <fcntl.h>
#include <io.h>
#endif
namespace are::rooms::wire {
inline void binary_mode() {
#if defined(_WIN32)
    _setmode(_fileno(stdin),_O_BINARY);_setmode(_fileno(stdout),_O_BINARY);
#endif
}
inline std::uint32_t read32() {
    unsigned char b[4];
    if(!std::cin.read(reinterpret_cast<char*>(b),4))throw std::runtime_error("ROOM_TRUNCATED");
    return std::uint32_t(b[0])|std::uint32_t(b[1])<<8|std::uint32_t(b[2])<<16|std::uint32_t(b[3])<<24;
}
inline void write32(std::uint32_t v) {
    const char b[]={char(v),char(v>>8),char(v>>16),char(v>>24)};std::cout.write(b,4);
}
inline unsigned bounded(const char* s,unsigned lo,unsigned hi) {
    std::size_t end=0;const auto v=std::stoul(s,&end);
    if(end!=std::strlen(s)||v<lo||v>hi)throw std::runtime_error("ROOM_CLI_BUDGET");
    return unsigned(v);
}
struct Request {Config config;std::vector<Triangle> scene;std::array<char,32> tag;};
inline Request read_request(unsigned workers) {
    char magic[8];std::array<char,32> tag{};
    if(!std::cin.read(magic,8)||std::memcmp(magic,"ARERIN01",8))throw std::runtime_error("ROOM_PROTOCOL");
    if(!std::cin.read(tag.data(),32))throw std::runtime_error("ROOM_TRUNCATED");
    const Config c{read32(),read32(),read32(),read32()};const auto count=read32();
    validate(c,count,workers);std::vector<Triangle> scene(count);
    for(auto& t:scene) {
        for(auto& v:t.v) {
            std::array<float,4> f{};for(auto& value:f){const auto bits=read32();std::memcpy(&value,&bits,4);}
            v={f[0],f[1],f[2],f[3]};
        }
        if(!std::cin.read(reinterpret_cast<char*>(t.rgba.data()),4))throw std::runtime_error("ROOM_TRUNCATED");
    }
    if(std::cin.peek()!=std::char_traits<char>::eof())throw std::runtime_error("ROOM_TRAILING");
    return {c,std::move(scene),tag};
}
template<class A,class B> void same(const A& a,const B& b) {
    if(a.rgba()!=b.rgba() || a.resolved()!=b.resolved() ||
       std::memcmp(a.depth().data(),b.depth().data(),a.depth().size()*4))
        throw std::runtime_error("ROOM_WORKER_PARITY");
}
inline void values(std::ostringstream& out,const std::vector<double>& data) {
    out<<'[';for(std::size_t i=0;i<data.size();++i){if(i)out<<',';out<<data[i];}out<<']';
}
template<class P> void append_waves(std::ostringstream& receipt,const P& pipeline,unsigned workers,std::size_t count) {
    receipt<<",\"waves\":[";
    for(unsigned k=0;k<4;++k){if(k)receipt<<',';const auto& w=pipeline.waves()[k];
        receipt<<"{\"kind\":\""<<names[k]<<"\",\"color\":\""<<colors[k]
            <<"\",\"executed\":"<<w.executed<<",\"sample_writes\":"<<w.samples
            <<",\"last_ms\":"<<w.milliseconds<<",\"worker_jobs\":[";
        for(unsigned j=0;j<workers;++j){if(j)receipt<<',';receipt<<w.worker_jobs[j];}receipt<<"]}";
    }
    receipt<<"],\"address_examples\":[";
    const std::array<std::size_t,5> ids{0,count,count+pipeline.tiles(),count+2*pipeline.tiles(),pipeline.room_count()-1};
    for(unsigned j=0;j<ids.size();++j){if(j)receipt<<',';auto a=pipeline.address(ids[j]);
        receipt<<'['<<a[0]<<','<<a[1]<<','<<a[2]<<','<<a[3]<<']';}
    receipt<<"]}";
}
template<class P> void write_response(const P& pipeline,const Request& request,const std::string& json) {
    std::cout.write("AREROUT1",8);std::cout.write(request.tag.data(),32);write32(request.config.width);write32(request.config.height);
    std::cout.write(reinterpret_cast<const char*>(pipeline.resolved().data()),pipeline.resolved().size());
    std::cout.write(reinterpret_cast<const char*>(pipeline.rgba().data()),pipeline.rgba().size());
    for(float f:pipeline.depth())write32(::are::bits(f));
    write32(std::uint32_t(json.size()));std::cout.write(json.data(),json.size());
    if(!std::cout)throw std::runtime_error("ROOM_OUTPUT");
}
} // namespace are::rooms::wire
