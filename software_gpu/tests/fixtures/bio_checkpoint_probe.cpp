#include "bio_workrooms.hpp"
#include <iostream>
template<class F> void rejects(F fn) {
    try{fn();}catch(const std::runtime_error&){return;}
    throw std::runtime_error("EXPECTED_REJECTION");
}
int main() {
    using namespace are::rooms;
    CheckpointLedger ledger(2);const auto first=ledger.begin();
    rejects([&]{ledger.seal(first);});
    rejects([&]{ledger.require_done(0,first);});
    rejects([&]{ledger.finish(0,first);});
    rejects([&]{ledger.claim(2,first);});
    ledger.claim(0,first);rejects([&]{ledger.claim(0,first);});
    ledger.finish(0,first);rejects([&]{ledger.finish(0,first);});
    rejects([&]{ledger.begin();});ledger.claim(1,first);ledger.finish(1,first);ledger.seal(first);
    const auto second=ledger.begin();rejects([&]{ledger.claim(0,first);});
    rejects([&]{ledger.require_done(0,second);});
    for(std::size_t i=0;i<2;++i){ledger.claim(i,second);ledger.finish(i,second);}ledger.seal(second);
    for(unsigned workers: {1u,4u,8u}) {
        ResidentWorkers pool(workers);std::array<std::atomic<unsigned>,8> visits{};
        for(auto& v:visits)v.store(0);
        for(unsigned frame=0;frame<20;++frame)pool.run([&](unsigned w){visits[w].fetch_add(1);});
        for(unsigned w=0;w<workers;++w)if(visits[w].load()!=20)throw std::runtime_error("WORKER_GENERATION_LOST");
        rejects([&]{pool.run([](unsigned w){if(w==0)throw std::runtime_error("INJECTED_WORKER_ERROR");});});
        pool.run([&](unsigned w){visits[w].fetch_add(1);});
        for(unsigned w=0;w<workers;++w)if(visits[w].load()!=21)throw std::runtime_error("WORKER_RECOVERY_LOST");
    }
    std::cout<<"CHECKPOINTS_AND_WORKERS_OK\n";
}
