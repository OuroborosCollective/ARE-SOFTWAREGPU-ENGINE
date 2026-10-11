// Bounded standalone C++17 rendering runtime. No Python linkage or callback.
#include "workrooms.hpp"
#include <ctime>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#if defined(_WIN32)
#include <fcntl.h>
#include <io.h>
#endif
namespace {
std::uint32_t read32() {
    unsigned char b[4];
    if(!std::cin.read(reinterpret_cast<char*>(b),4))throw std::runtime_error("ROOM_TRUNCATED");
    return std::uint32_t(b[0])|std::uint32_t(b[1])<<8|std::uint32_t(b[2])<<16|std::uint32_t(b[3])<<24;
}
void write32(std::uint32_t v) {
    const char b[]={char(v),char(v>>8),char(v>>16),char(v>>24)};std::cout.write(b,4);
}
unsigned bounded(const char* s,unsigned lo,unsigned hi) {
    std::size_t end=0;const auto v=std::stoul(s,&end);
    if(end!=std::strlen(s)||v<lo||v>hi)throw std::runtime_error("ROOM_CLI_BUDGET");
    return unsigned(v);
}
void same(const are::rooms::Pipeline& a,const are::rooms::Pipeline& b) {
    if(a.rgba()!=b.rgba() || a.resolved()!=b.resolved() ||
       std::memcmp(a.depth().data(),b.depth().data(),a.depth().size()*4))
        throw std::runtime_error("ROOM_WORKER_PARITY");
}
}
int main(int argc,char** argv) {
    try {
#if defined(_WIN32)
        _setmode(_fileno(stdin),_O_BINARY);_setmode(_fileno(stdout),_O_BINARY);
#endif
        if(argc!=3)throw std::runtime_error("USAGE: workrooms workers repeats");
        const unsigned workers=bounded(argv[1],1,8),repeats=bounded(argv[2],1,30);
        char magic[8];std::array<char,32> tag{};
        if(!std::cin.read(magic,8)||std::memcmp(magic,"ARERIN01",8))throw std::runtime_error("ROOM_PROTOCOL");
        if(!std::cin.read(tag.data(),32))throw std::runtime_error("ROOM_TRUNCATED");
        are::rooms::Config c{read32(),read32(),read32(),read32()};const auto count=read32();
        are::rooms::validate(c,count,workers);
        std::vector<are::rooms::Triangle> scene(count);
        for(auto& t:scene) {
            for(auto& v:t.v) {
                std::array<float,4> values{};
                for(auto& f:values){const auto bits=read32();std::memcpy(&f,&bits,4);}
                v={values[0],values[1],values[2],values[3]};
            }
            if(!std::cin.read(reinterpret_cast<char*>(t.rgba.data()),4))throw std::runtime_error("ROOM_TRUNCATED");
        }
        if(std::cin.peek()!=std::char_traits<char>::eof())throw std::runtime_error("ROOM_TRAILING");
        are::rooms::Pipeline reference(c,scene,1),pipeline(c,scene,workers);
        reference.execute();pipeline.execute();same(reference,pipeline); // untimed warmup
        std::vector<double> milliseconds,cpu_milliseconds;
        for(unsigned i=0;i<repeats;++i) {
            const auto cpu_start=std::clock();
            const auto start=std::chrono::steady_clock::now();pipeline.execute();
            milliseconds.push_back(std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count());
            cpu_milliseconds.push_back(1000.0*double(std::clock()-cpu_start)/CLOCKS_PER_SEC);
            same(reference,pipeline); // consume every output, outside timed interval
        }
        std::ostringstream receipt;receipt<<std::setprecision(17)
            <<"{\"protocol\":\"are.workrooms.receipt.v1\",\"python_in_runtime\":false,"
            <<"\"workers\":"<<workers<<",\"frame\":"<<c.frame<<",\"triangles\":"<<count
            <<",\"tile\":"<<c.tile<<",\"rooms_executed\":"<<pipeline.room_count()
            <<",\"handoff_ready\":true,\"hardware_gpu_submitted\":false,\"worker_parity\":true,"
            <<"\"warmups\":1,\"samples_ms\":[";
        for(unsigned i=0;i<repeats;++i){if(i)receipt<<',';receipt<<milliseconds[i];}
        receipt<<"],\"cpu_samples_ms\":[";
        for(unsigned i=0;i<repeats;++i){if(i)receipt<<',';receipt<<cpu_milliseconds[i];}
        receipt<<"],\"waves\":[";
        for(unsigned k=0;k<4;++k){if(k)receipt<<',';const auto& w=pipeline.waves()[k];
            receipt<<"{\"kind\":\""<<are::rooms::names[k]<<"\",\"color\":\""<<are::rooms::colors[k]
                <<"\",\"executed\":"<<w.executed<<",\"sample_writes\":"<<w.samples
                <<",\"last_ms\":"<<w.milliseconds<<",\"worker_jobs\":[";
            for(unsigned j=0;j<workers;++j){if(j)receipt<<',';receipt<<w.worker_jobs[j];}receipt<<"]}";
        }
        receipt<<"],\"address_examples\":[";
        const std::array<std::size_t,5> ids{0,count,count+pipeline.tiles(),count+2*pipeline.tiles(),pipeline.room_count()-1};
        for(unsigned j=0;j<ids.size();++j){if(j)receipt<<',';auto a=pipeline.address(ids[j]);
            receipt<<'['<<a[0]<<','<<a[1]<<','<<a[2]<<','<<a[3]<<']';}
        receipt<<"]}";const auto json=receipt.str();
        std::cout.write("AREROUT1",8);std::cout.write(tag.data(),32);write32(c.width);write32(c.height);
        std::cout.write(reinterpret_cast<const char*>(pipeline.resolved().data()),pipeline.resolved().size());
        std::cout.write(reinterpret_cast<const char*>(pipeline.rgba().data()),pipeline.rgba().size());
        for(float f:pipeline.depth())write32(are::bits(f));
        write32(std::uint32_t(json.size()));std::cout.write(json.data(),json.size());
        if(!std::cout)throw std::runtime_error("ROOM_OUTPUT");
        return 0;
    }catch(const std::exception& e){std::cerr<<"NATIVE_REJECTED:"<<e.what()<<'\n';return 2;}
}
