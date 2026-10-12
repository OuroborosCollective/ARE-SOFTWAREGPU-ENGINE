// Bounded standalone C++17 rendering runtime. No Python linkage or callback.
#include "workrooms.hpp"
#include <ctime>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include "workrooms_wire.hpp"
using namespace are::rooms::wire;
int main(int argc,char** argv) {
    try {
        binary_mode();
        if(argc!=3)throw std::runtime_error("USAGE: workrooms workers repeats");
        const unsigned workers=bounded(argv[1],1,8),repeats=bounded(argv[2],1,30);
        const auto request=read_request(workers);const auto c=request.config;
        const auto& scene=request.scene;const auto count=scene.size();
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
        receipt<<']';

        append_waves(receipt,pipeline,workers,count);
        write_response(pipeline,request,receipt.str());
        return 0;
    }catch(const std::exception& e){std::cerr<<"NATIVE_REJECTED:"<<e.what()<<'\n';return 2;}
}
