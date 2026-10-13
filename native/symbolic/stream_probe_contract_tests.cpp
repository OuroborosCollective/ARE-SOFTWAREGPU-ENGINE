// Native fail-closed admission and parity tests; standalone C++17, no Python.
#include "workrooms.hpp"
#include <cstring>
#include <functional>
#include <iostream>
#include <stdexcept>

using namespace are::rooms;
void require(bool x) {if(!x)throw std::runtime_error("STREAM_TEST_ASSERTION");}
void reject(std::function<void()> f) {
    try{f();}catch(const std::runtime_error&){return;}
    throw std::runtime_error("STREAM_TEST_MUST_REJECT");
}
int main(){
    try{
        are::require_environment();
        const Config hd{1280,720,32,0},sd{640,360,32,0};
        require(validate(hd,12,2,Admission::stream_probe)==std::size_t(1280)*720);
        require(validate(sd,12,1,Admission::stream_probe)==std::size_t(640)*360);
        reject([&]{validate(hd,12,2,Admission::model_probe);});
        reject([&]{validate(hd,12,2,Admission::legacy);});
        reject([&]{validate({1281,720,32,0},12,2,Admission::stream_probe);});
        reject([&]{validate({1280,721,32,0},12,2,Admission::stream_probe);});
        reject([&]{validate(hd,0,2,Admission::stream_probe);});
        reject([&]{validate(hd,65,2,Admission::stream_probe);});
        reject([&]{validate({1280,720,8,0},12,2,Admission::stream_probe);});
        reject([&]{validate(hd,12,9,Admission::stream_probe);});
        const std::vector<Triangle> geometry{{{{{-0.8f,-0.7f,.3f,1.0f},
                       {0.0f,.8f,.3f,1.0f},{.8f,-.7f,.3f,1.0f}}},{{200,40,80,255}}}};
        Pipeline ref({96,64,16,0},geometry,1,Admission::stream_probe);
        Pipeline many({96,64,16,0},geometry,2,Admission::stream_probe);
        ref.execute();many.execute();
        require(ref.rgba()==many.rgba());
        require(ref.resolved()==many.resolved());
        require(std::memcmp(ref.depth().data(),many.depth().data(),
                            ref.depth().size()*sizeof(float))==0);
        require(many.waves()[1].samples>0);
        std::cout<<"ARE_STREAM_NATIVE_ADMISSION_PARITY_OK\n";
        return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 2;}
}
