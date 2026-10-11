// Standalone bounded f32 frame runner. No Python runtime or callbacks.
#include "generated.hpp"
#include <chrono>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#if defined(_WIN32)
#include <fcntl.h>
#include <io.h>
#endif
using Clock = std::chrono::steady_clock;
static volatile std::uint32_t sink = 0;

std::uint32_t read_u32() {
    unsigned char b[4];
    if (!std::cin.read(reinterpret_cast<char*>(b),4)) throw std::runtime_error("TRUNCATED_FRAME");
    return std::uint32_t(b[0]) | std::uint32_t(b[1])<<8 |
           std::uint32_t(b[2])<<16 | std::uint32_t(b[3])<<24;
}
std::vector<std::vector<float>> read_frames(std::size_t cells) {
    char magic[8];
    if (!std::cin.read(magic,8) || std::memcmp(magic,"AREF32V1",8))
        throw std::runtime_error("FRAME_PROTOCOL");
    auto count = read_u32();
    if (!count || count>32 || cells*count>8388608) throw std::runtime_error("FRAME_BUDGET");
    if (read_u32() != cells) throw std::runtime_error("FRAME_SHAPE");
    std::string graph_hash;
    const char* hex="0123456789abcdef";
    for (int i=0; i<32; ++i) {
        int byte=std::cin.get();
        if(byte==std::char_traits<char>::eof()) throw std::runtime_error("TRUNCATED_FRAME");
        graph_hash+=hex[(byte>>4)&15];graph_hash+=hex[byte&15];
    }
    if(graph_hash!=generated_graph.sha256) throw std::runtime_error("FRAME_GRAPH");
    std::vector<std::vector<float>> frames(count, std::vector<float>(cells));
    for (auto& frame : frames) for (float& value : frame) {
        auto word = read_u32(); std::memcpy(&value,&word,4);
    }
    if (std::cin.peek() != std::char_traits<char>::eof()) throw std::runtime_error("TRAILING_DATA");
    return frames;
}
void output_bits(std::ostream& out, const are::Engine& engine) {
    out << '[';
    for (std::size_t j=0; j<generated_graph.outputs.size(); ++j) {
        if (j) out << ',';
        out << '[';
        const auto& values = engine.output(j);
        for (std::size_t k=0; k<values.size(); ++k) { if(k)out<<','; out<<are::bits(values[k]); }
        out << ']';
    }
    out << ']';
}
std::uint32_t consume(const are::Engine& engine) {
    std::uint32_t checksum = 0;
    for (std::size_t i=0; i<generated_graph.outputs.size(); ++i) {
        const auto& out = engine.output(i);
        checksum = checksum * 16777619u + are::bits(out.front()) + 31u * are::bits(out.back());
    }
    sink = checksum; return checksum;
}
void run(const std::vector<std::vector<float>>& frames, bool incremental) {
    are::Engine engine(generated_graph,incremental);
    std::cout << "{\"protocol\":\"are.native-frames.v1\",\"graph_sha256\":\""
              << generated_graph.sha256 << "\",\"frames\":[";
    bool first=true;
    for (const auto& frame : frames) {
        if(!first)std::cout<<',';
        first=false;
        try {
            auto counts=engine.evaluate(frame);
            std::cout << "{\"status\":\"PASS\",\"changed_inputs\":" << counts.changed
                      << ",\"executed_nodes\":" << counts.executed << ",\"bits\":";
            output_bits(std::cout,engine); std::cout << '}';
        } catch (const std::runtime_error& e) {
            std::cout << "{\"status\":\"ERROR\",\"reason\":\"" << e.what() << "\"}";
        }
    }
    std::cout << "]}\n";
}

// Preallocated raw fused path: already validated inputs, no input content scan.
// This timing is reported separately from both checked native APIs.
struct Raw {
    std::vector<std::vector<float>> outputs;
    std::array<std::vector<const float*>,2> inputs;
    std::vector<float*> output_ptrs;
    explicit Raw(const std::vector<std::vector<float>>& frames) {
        for (auto id : generated_graph.outputs) outputs.emplace_back(generated_graph.nodes[id].cells);
        for(auto& out:outputs) output_ptrs.push_back(out.data());
        for(std::size_t f=0;f<2;++f) {
            std::size_t offset=0;
            for(auto id:generated_graph.inputs) {
                inputs[f].push_back(frames[f].data()+offset); offset+=generated_graph.nodes[id].cells;
            }
        }
    }
    ARE_NOINLINE void evaluate(std::size_t f) {
        if(!generated_graph.fused(inputs[f].data(),output_ptrs.data()))
            throw std::runtime_error("NONFINITE_RESULT");
        std::uint32_t checksum=0;
        for(auto& out:outputs) checksum=checksum*16777619u+are::bits(out.front())+31u*are::bits(out.back());
        sink=checksum;
    }
};

void benchmark(const std::vector<std::vector<float>>& frames, int repeats, int loops) {
    if(frames.size()!=2) throw std::runtime_error("BENCHMARK_TWO_FRAMES");
    are::Engine fused(generated_graph,false), incremental(generated_graph,true);
    Raw raw(frames);
    // Actual byte comparison outside timed batches, including local edits.
    for(std::size_t f: {0u,1u,0u}) {
        fused.evaluate(frames[f]); incremental.evaluate(frames[f]); raw.evaluate(f);
        for(std::size_t j=0;j<generated_graph.outputs.size();++j) {
            auto& a=fused.output(j); auto& b=incremental.output(j);
            if(std::memcmp(a.data(),b.data(),a.size()*4) ||
               std::memcmp(a.data(),raw.outputs[j].data(),a.size()*4))
                throw std::runtime_error("NATIVE_PARITY");
        }
    }
    std::array<std::vector<double>,3> samples;
    std::array<are::Counts,2> last{};
    // One untimed warm-up batch and rotated per-repeat order.
    for(int repeat=-1;repeat<repeats;++repeat) {
        for(int slot=0;slot<3;++slot) {
            int mode=(slot+repeat+3)%3;
            const auto start=Clock::now();
            for(int i=0;i<loops*2;++i) {
                const std::size_t f=(i+1)%2;
                if(mode==0)raw.evaluate(f);
                else if(mode==1) {last[0]=fused.evaluate(frames[f]);consume(fused);}
                else {last[1]=incremental.evaluate(frames[f]);consume(incremental);}
            }
            double ns=std::chrono::duration<double,std::nano>(Clock::now()-start).count()/(loops*2);
            if(repeat>=0)samples[mode].push_back(ns);
        }
    }
    std::cout<<std::setprecision(17)<<"{\"protocol\":\"are.native-benchmark.v1\",\"graph_sha256\":\""
             <<generated_graph.sha256<<"\",\"repeats\":"<<repeats<<",\"frames_per_sample\":"<<loops*2
             <<",\"warmup_batches\":1,\"workers\":1,\"native_parity\":true,\"samples_ns\":{";
    const char* names[]={"fused-kernel","fused-checked","incremental-checked"};
    for(int mode=0;mode<3;++mode) {
        if(mode)std::cout<<',';
        std::cout<<'"'<<names[mode]<<"\":[";
        for(int r=0;r<repeats;++r){if(r)std::cout<<',';std::cout<<samples[mode][r];}
        std::cout<<']';
    }
    std::cout<<"},\"last_incremental_executed_nodes\":"<<last[1].executed
             <<",\"last_incremental_changed_inputs\":"<<last[1].changed
             <<",\"result_bits\":";output_bits(std::cout,fused);std::cout<<"}\n";
}
int bounded_integer(const char* s,int low,int high) {
    std::size_t used=0; int value=std::stoi(s,&used);
    if(used!=std::strlen(s)||value<low||value>high)throw std::runtime_error("CLI_BUDGET");
    return value;
}
int main(int argc,char** argv) {
    try {
#if defined(_WIN32)
        _setmode(_fileno(stdin),_O_BINARY);
#endif
        are::require_environment();
        if(argc==2&&std::string(argv[1])=="info") {
            std::cout<<"{\"language\":\"C++17\",\"python_in_runtime\":false,\"graph_sha256\":\""
                     <<generated_graph.sha256<<"\",\"contract\":\"ordered-f32-v1\"}\n";return 0;
        }
        if(argc!=3&&argc!=4)throw std::runtime_error("USAGE: run fused|incremental OR bench repeats loops");
        const std::string command=argv[1];
        if(command=="run"&&argc==3) {
            const std::string mode=argv[2];
            if(mode!="fused"&&mode!="incremental")throw std::runtime_error("CLI_MODE");
            are::Engine schema(generated_graph,mode=="incremental");
            run(read_frames(schema.input_cells()),mode=="incremental");
        } else if(command=="bench"&&argc==4) {
            int repeats=bounded_integer(argv[2],15,30), loops=bounded_integer(argv[3],1,10000);
            are::Engine schema(generated_graph,false);
            benchmark(read_frames(schema.input_cells()),repeats,loops);
        } else throw std::runtime_error("CLI_MODE");
        return 0;
    } catch(const std::exception& e) {std::cerr<<"NATIVE_REJECTED:"<<e.what()<<'\n';return 2;}
}
