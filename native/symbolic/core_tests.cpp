// Native invariant checks, also runnable without the Python test harness.
#include "core.hpp"
#include <iostream>
#include <functional>
#include <string>

bool add(const float* const* in,float* const* out) {
    out[0][0]=in[0][0]+in[1][0];return !are::nonfinite(out[0][0]);
}
void check(bool condition) {if(!condition)throw std::runtime_error("CHECK_FAILED");}
void rejected(const std::function<void()>& call,const char* expected) {
    try {call();}catch(const std::runtime_error& e) {check(std::string(e.what())==expected);return;}
    throw std::runtime_error("EXPECTED_REJECTION");
}
int main() {
    const are::Graph valid{{{are::Op::input,0,0,1},{are::Op::input,0,0,1},
                           {are::Op::add,0,1,1}},{0,1},{2},add,"test"};
    auto bad=valid;bad.nodes.clear();
    rejected([&]{are::Engine e(bad,true);},"GRAPH_SCHEMA");
    bad=valid;bad.nodes.resize(129);
    rejected([&]{are::Engine e(bad,true);},"GRAPH_SCHEMA");
    bad=valid;bad.fused=nullptr;
    rejected([&]{are::Engine e(bad,true);},"GRAPH_SCHEMA");
    bad=valid;bad.outputs.clear();
    rejected([&]{are::Engine e(bad,true);},"GRAPH_SCHEMA");
    for(std::size_t size:{0u,1048577u,524289u}) {
        bad=valid;bad.nodes[0].cells=size;bad.nodes[1].cells=size;
        rejected([&]{are::Engine e(bad,true);},"GRAPH_BUDGET");
    }
    bad=valid;bad.nodes[2].a=2;
    rejected([&]{are::Engine e(bad,true);},"GRAPH_DEPENDENCY");
    bad=valid;bad.nodes[2].b=3;
    rejected([&]{are::Engine e(bad,true);},"GRAPH_DEPENDENCY");
    bad=valid;bad.nodes[2].op=static_cast<are::Op>(99);
    rejected([&]{are::Engine e(bad,true);},"GRAPH_DEPENDENCY");
    bad=valid;bad.nodes[0].cells=2;
    rejected([&]{are::Engine e(bad,true);},"GRAPH_DEPENDENCY");
    bad=valid;bad.inputs={1,0};
    rejected([&]{are::Engine e(bad,true);},"GRAPH_INPUTS");
    bad=valid;bad.outputs={3};
    rejected([&]{are::Engine e(bad,true);},"GRAPH_OUTPUTS");
    bad=valid;bad.outputs={2,2};
    rejected([&]{are::Engine e(bad,true);},"GRAPH_OUTPUTS");
    for(bool incremental:{false,true}) {
        are::Engine e(valid,incremental);
        rejected([&]{e.output(0);},"NO_VALID_FRAME");
        rejected([&]{e.evaluate({1});},"INPUT_SIZE");
        rejected([&]{e.evaluate({0,std::numeric_limits<float>::infinity()});},"NONFINITE_INPUT");
        e.evaluate({-0.0f,-0.0f});check(are::bits(e.output(0)[0])==0x80000000u);
        auto count=e.evaluate({0.0f,-0.0f});check(count.changed==1);check(are::bits(e.output(0)[0])==0);
        rejected([&]{e.evaluate({std::numeric_limits<float>::max(),std::numeric_limits<float>::max()});},"NONFINITE_RESULT");
        check(are::bits(e.output(0)[0])==0);
        count=e.evaluate({0.0f,-0.0f});check(count.changed==0);
        check(count.executed==(incremental?0u:1u));
        int previous=std::fegetround();
        check(std::fesetround(FE_DOWNWARD)==0);
        rejected([&]{e.evaluate({1,2});},"ROUNDING_MODE");
        check(std::fesetround(previous)==0);
#if defined(__SSE__)
        auto csr=_mm_getcsr();_mm_setcsr(csr|(1u<<15));
        rejected([&]{e.evaluate({1,2});},"FLUSH_TO_ZERO");
        _mm_setcsr(csr);
#endif
    }
    std::cout<<"NATIVE_CORE_INVARIANTS_PASS\n";
}
